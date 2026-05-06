"""Substitute ${param} placeholders in a macro body and validate
the resulting tagged-DSL.

Uses Python's `string.Template` for substitution — same `${name}` /
`$name` syntax operators are already used to from shell / docker.
Returns the substituted body verbatim; the caller hands it to
`qa_agent.tagged.parse_tagged` for execution.

Type coercion is intentionally minimal — params are passed as Python
values, the body is text. We coerce to the right `str` form per
declared param type:

    string -> as-is (already text)
    int    -> str(int(v))         — rejects float-looking strings
    url    -> as-is, but validated to look URL-shaped (scheme + host)

Anything that doesn't pass coercion raises MacroParamError so the
caller sees a clear "you gave int=`abc`" instead of a baffling
tagged-DSL parse error five frames deep.
"""

from __future__ import annotations

import re
from string import Template
from typing import Any

from .library import Macro, MacroParamError, ParamSpec


_URL_LIKE = re.compile(r"^[a-z][a-z0-9+.\-]*://[^\s/$.?#].[^\s]*$", re.IGNORECASE)


def _coerce(spec: ParamSpec, raw: Any) -> str:
    """Validate + stringify one param value per its declared type."""
    if spec.type == "string":
        if not isinstance(raw, (str, int, float)):
            raise MacroParamError(
                f"param {spec.name!r}: expected string-castable, got "
                f"{type(raw).__name__}"
            )
        return str(raw)
    if spec.type == "int":
        try:
            i = int(raw)
        except (TypeError, ValueError) as e:
            raise MacroParamError(
                f"param {spec.name!r}: expected int, got {raw!r}"
            ) from e
        return str(i)
    if spec.type == "url":
        if not isinstance(raw, str):
            raise MacroParamError(
                f"param {spec.name!r}: url must be a string, got "
                f"{type(raw).__name__}"
            )
        if not _URL_LIKE.match(raw):
            raise MacroParamError(
                f"param {spec.name!r}: doesn't look like a URL: {raw!r}"
            )
        return raw
    # library.ParamSpec.__post_init__ guards the type set, so this is
    # only reachable if someone bypasses it.
    raise MacroParamError(f"param {spec.name!r}: unknown type {spec.type!r}")


def compile_macro(macro: Macro, params: dict[str, Any]) -> str:
    """Substitute params into the macro body. Returns ready-to-parse
    tagged DSL.

    Raises MacroParamError on missing required, unknown name, or type
    mismatch. Does NOT validate the resulting tagged-DSL grammar —
    that's `qa_agent.tagged.parse_tagged`'s job.
    """
    if not isinstance(params, dict):
        raise MacroParamError(
            f"params must be a dict, got {type(params).__name__}"
        )

    by_name = {p.name: p for p in macro.params}

    # 1. Reject unknown param names — caller's typo or stale param list.
    unknown = set(params) - set(by_name)
    if unknown:
        raise MacroParamError(
            f"macro {macro.name!r}: unknown params {sorted(unknown)}. "
            f"Declared: {sorted(by_name)}"
        )

    # 2. Build the substitution map: required params must be supplied,
    #    optional ones fall back to their declared default.
    subs: dict[str, str] = {}
    for spec in macro.params:
        if spec.name in params:
            subs[spec.name] = _coerce(spec, params[spec.name])
            continue
        if spec.required:
            raise MacroParamError(
                f"macro {macro.name!r}: missing required param "
                f"{spec.name!r} (type {spec.type})"
            )
        # Optional with default — coerce the default the same way.
        subs[spec.name] = _coerce(spec, spec.default)

    # 3. Substitute. Template raises KeyError on a placeholder that
    #    isn't in `subs` — turn that into a typed error so the macro
    #    author sees "your body references ${foo} but no such param".
    try:
        return Template(macro.body).substitute(subs)
    except KeyError as e:
        raise MacroParamError(
            f"macro {macro.name!r}: body references ${{{e.args[0]}}} "
            f"but it's not declared in meta.params"
        ) from e
    except ValueError as e:
        # Malformed `$` syntax in the body.
        raise MacroParamError(
            f"macro {macro.name!r}: malformed substitution syntax: {e}"
        ) from e
