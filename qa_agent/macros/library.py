"""Macro storage discovery + load.

Storage layout per macro:

    <root>/<name>/
        macro.tagged.txt    -- body, tagged DSL with ${param} placeholders
        meta.json           -- schema (see Macro dataclass)

Default root is `~/.config/qa_agent/macros/`. Bench / test code can
override via the `root` kwarg or `QA_MACROS_DIR` env var.

Validation: load_macro fails fast on a malformed meta.json or missing
body. Tagged-DSL parse errors don't surface here — they surface at
compile time, when params are substituted and the body is parsed.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


MACROS_DIR_DEFAULT = Path.home() / ".config" / "qa_agent" / "macros"


def MACROS_DIR() -> Path:
    """Resolve the macros root directory at call time, honouring
    `QA_MACROS_DIR` env override. Function (not constant) so tests
    can `monkeypatch.setenv` between cases."""
    override = os.environ.get("QA_MACROS_DIR")
    return Path(override).expanduser() if override else MACROS_DIR_DEFAULT


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class MacroNotFound(LookupError):
    """Raised when load_macro can't find the named macro on disk."""


class MacroParamError(ValueError):
    """Raised when compile_macro is given params that don't match the
    macro's declared schema (missing required, unknown name, wrong type)."""


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

# Param types we accept in meta.json. Kept tight on purpose — every
# additional type is one more thing the substitution code has to
# understand. Add only when a real macro needs it.
_PARAM_TYPES = frozenset({"string", "int", "url"})


@dataclass(frozen=True)
class ParamSpec:
    name: str
    type: str = "string"        # ∈ _PARAM_TYPES
    required: bool = True
    default: Any = None
    description: str = ""

    def __post_init__(self) -> None:
        if not _NAME_RE.match(self.name):
            raise MacroParamError(
                f"param name {self.name!r} must match {_NAME_RE.pattern}"
            )
        if self.type not in _PARAM_TYPES:
            raise MacroParamError(
                f"param {self.name!r}: unknown type {self.type!r}; "
                f"allowed: {sorted(_PARAM_TYPES)}"
            )
        if not self.required and self.default is None:
            # Optional params must have a default — otherwise compile_macro
            # has nothing to substitute when the caller omits the value.
            raise MacroParamError(
                f"param {self.name!r}: optional params need a default value"
            )


_NAME_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")


@dataclass
class Macro:
    """Loaded macro definition.

    `body` is the raw tagged-DSL text WITH unresolved ${param}
    placeholders. Use `compile_macro(macro, params)` to get a
    substituted body ready to feed into `qa_agent.tagged.parse_tagged`.
    """

    name: str
    version: int
    description: str
    params: list[ParamSpec]
    preconditions: dict
    body: str
    meta: dict
    path: Path                         # the directory, not a file
    learned_from_runs: list[str] = field(default_factory=list)
    support_count: int = 0
    success_rate: float = 1.0


# ---------------------------------------------------------------------------
# Loaders
# ---------------------------------------------------------------------------

def _read_meta(path: Path) -> dict:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise MacroParamError(
            f"{path}: meta.json must be a JSON object, got {type(raw).__name__}"
        )
    return raw


def _parse_params(raw_params: Any, macro_name: str) -> list[ParamSpec]:
    if raw_params is None:
        return []
    if not isinstance(raw_params, list):
        raise MacroParamError(
            f"macro {macro_name!r}: meta.params must be a list, "
            f"got {type(raw_params).__name__}"
        )
    out: list[ParamSpec] = []
    seen: set[str] = set()
    for i, p in enumerate(raw_params):
        if not isinstance(p, dict):
            raise MacroParamError(
                f"macro {macro_name!r}: params[{i}] must be an object"
            )
        if "name" not in p:
            raise MacroParamError(
                f"macro {macro_name!r}: params[{i}] missing `name`"
            )
        spec = ParamSpec(
            name=str(p["name"]),
            type=str(p.get("type", "string")),
            required=bool(p.get("required", True)),
            default=p.get("default"),
            description=str(p.get("description", "")),
        )
        if spec.name in seen:
            raise MacroParamError(
                f"macro {macro_name!r}: duplicate param {spec.name!r}"
            )
        seen.add(spec.name)
        out.append(spec)
    return out


def load_macro(name: str, root: Path | None = None) -> Macro:
    """Load a macro from disk.

    Raises MacroNotFound if the directory or body is missing.
    Raises MacroParamError on a malformed meta.json.
    """
    if not _NAME_RE.match(name):
        raise MacroNotFound(
            f"invalid macro name {name!r}: must match {_NAME_RE.pattern}"
        )
    root = root if root is not None else MACROS_DIR()
    macro_dir = root / name
    body_path = macro_dir / "macro.tagged.txt"
    meta_path = macro_dir / "meta.json"
    if not body_path.is_file():
        raise MacroNotFound(
            f"macro {name!r}: body not found at {body_path}"
        )
    if not meta_path.is_file():
        raise MacroNotFound(
            f"macro {name!r}: meta.json not found at {meta_path}"
        )

    body = body_path.read_text(encoding="utf-8")
    meta = _read_meta(meta_path)

    if str(meta.get("name", name)) != name:
        # Mismatch means someone renamed the directory without
        # editing meta.json. Refuse — silent rename = silent bug.
        raise MacroParamError(
            f"macro {name!r}: meta.name = {meta.get('name')!r} doesn't "
            f"match directory name. Rename meta.name or the directory."
        )

    return Macro(
        name=name,
        version=int(meta.get("version", 1)),
        description=str(meta.get("description", "")),
        params=_parse_params(meta.get("params"), name),
        preconditions=dict(meta.get("preconditions") or {}),
        body=body,
        meta=meta,
        path=macro_dir,
        learned_from_runs=list(meta.get("learned_from_runs") or []),
        support_count=int(meta.get("support_count", 0)),
        success_rate=float(meta.get("success_rate", 1.0)),
    )


def list_macros(root: Path | None = None) -> list[dict]:
    """Return a summary entry per installed macro. Sorted by name.

    Each entry: {name, version, description, params (count),
    support_count, success_rate, path}. Errors on individual macros
    are surfaced as `{name, error: "..."}` rather than aborting the
    whole listing — bad macros shouldn't break the catalog view.
    """
    root = root if root is not None else MACROS_DIR()
    if not root.is_dir():
        return []
    out: list[dict] = []
    for child in sorted(root.iterdir()):
        if not child.is_dir():
            continue
        if not _NAME_RE.match(child.name):
            continue
        try:
            m = load_macro(child.name, root=root)
            out.append({
                "name": m.name,
                "version": m.version,
                "description": m.description,
                "n_params": len(m.params),
                "support_count": m.support_count,
                "success_rate": m.success_rate,
                "path": str(m.path),
            })
        except (MacroNotFound, MacroParamError, OSError, ValueError) as e:
            out.append({
                "name": child.name,
                "error": f"{type(e).__name__}: {e}",
                "path": str(child),
            })
    return out
