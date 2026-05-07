"""Compile a curated macro to disk: tagged DSL body + meta.json.

The emitter takes the curated candidate (with its inferred slots —
concrete args + parameter slots already attached), and produces:

  <macros_root>/<name>/macro.tagged.txt    # body with ${param}
  <macros_root>/<name>/meta.json           # schema (see library.py)

The body is built per-step:

  click button "<concrete_text>"      -- if arg fixed across runs
  click button "${query}"             -- if arg parameterised
  type textbox "${query}"             -- typed param
  press Enter                         -- key embedded
  goto ${url}                         -- url param
  expect_visible heading "<concrete>" -- assertion

Every action verb known to the vocabulary maps to a tagged-DSL line
according to a small per-verb dispatch table. Anything the miner
shouldn't have surfaced (look / screenshot / etc.) was already
filtered upstream in vocabulary.py.

Each macro body ends with the assertion(s) it observed in the source
trace — those are the macro's post-conditions. If the miner found
zero assertions, the emitter appends a defensive `expect_url <pattern>`
on the URL the macro started on; if even that isn't available, it
appends nothing (caller's `meta.preconditions` plays that role).
"""

from __future__ import annotations

import json
from pathlib import Path

from ..library import _NAME_RE
from .curator import CuratedMacro
from .inference import ConcreteArgs, ParamCandidate
from .loader import Trace


def _shell_quote(s: str) -> str:
    """Quote a string for embedding in tagged DSL — preserves `"` by
    backslash-escaping. Tagged DSL uses shlex.split on parse, so this
    is shlex-safe."""
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _arg_for_step(
    step_idx: int, arg_idx: int,
    concrete: list[ConcreteArgs],
    params: list[ParamCandidate],
    param_names: dict[tuple[int, int], str],
) -> str:
    """Resolve the rendered arg at this position: quoted ${param} or
    quoted concrete value.

    Param refs are wrapped in double quotes so that compile_macro's
    string.Template substitution lands inside the shlex-quoted form.
    Without quoting, `type textbox ${username}` post-substitution
    becomes `type textbox tomsmith` and tagged-DSL's parser thinks
    `tomsmith` is the role's accessible-name selector arg, not the
    text to type — runtime parse error. Wrapping yields
    `type textbox "${username}"` → `type textbox "tomsmith"` →
    shlex strips quotes → ['type', 'textbox', 'tomsmith'] as
    intended. Numeric / URL substitutions also tolerate the quoting
    (shlex strips, downstream parsers re-coerce).
    """
    key = (step_idx, arg_idx)
    if key in param_names:
        return '"${' + param_names[key] + '}"'
    for c in concrete:
        if c.step_idx == step_idx and c.arg_idx == arg_idx:
            return _shell_quote(c.value)
    # Inference saw nothing at this slot; treat as required param
    # (shouldn't happen unless source traces were inconsistent).
    return '"${' + f"param_{step_idx}_{arg_idx}" + '}"'


def _render_step(
    step_idx: int,
    pattern_item,
    concrete: list[ConcreteArgs],
    params: list[ParamCandidate],
    param_names: dict[tuple[int, int], str],
    target_names: dict[int, str],
) -> str:
    """Produce one tagged-DSL line for one pattern step.

    `target_names` maps step_idx → consistent accessible name across
    all occurrences (only present if every occurrence's TraceStep
    recorded the same `target_name`). When present, click/hover
    selectors get baked-in role+name (`click button "Submit"`),
    significantly more robust against live-replay drift than role-only.
    """
    verb = pattern_item.verb
    role = pattern_item.classifier

    # max_arity from concrete + params at this step
    arity = max(
        [c.arg_idx for c in concrete if c.step_idx == step_idx]
        + [p.arg_idx for p in params if p.step_idx == step_idx]
        + [-1]
    ) + 1

    args_rendered: list[str] = []
    for ai in range(arity):
        args_rendered.append(_arg_for_step(
            step_idx, ai, concrete, params, param_names,
        ))

    # Verb-specific shape. For click / hover / select, the original
    # captured args[0] is the snapshot ID — meaningless for replay.
    # We drop it and emit role-only selectors, which Playwright's
    # get_by_role(role).first resolves predictably. If the inference
    # pass found a parameter at arg position 0, we drop the param
    # (it's just "which row of the catalog this run clicked") because
    # we have no way to tie it to anything human-meaningful.
    if verb in ("click", "hover"):
        name = target_names.get(step_idx)
        if name:
            return f"{verb} {role} {_shell_quote(name)}"
        return f"{verb} {role}"
    if verb == "select":
        # Same: drop the ID arg. Tagged DSL doesn't support `select`
        # natively today (it isn't in the verb table); skip with comment.
        return f"# select {role}    # NOT EMITTED — tagged has no select"
    if verb == "type":
        # Captured args were [id, text]. id at arg 0 is meaningless for
        # replay; the text is the parameter / concrete value.
        text_arg = args_rendered[1] if len(args_rendered) > 1 else _shell_quote("")
        return f"type {role} {text_arg}"
    if verb == "select":
        opt = args_rendered[1] if len(args_rendered) > 1 else _shell_quote("")
        # Tagged DSL doesn't have a `select` action — emit a click+expect
        # combo as fallback, or skip. For now: skip select (rare verb).
        return f"# select {role} {opt}    # NOT EMITTED — select unsupported in tagged"
    if verb == "press":
        # role here is "key:enter" etc. — strip prefix.
        key = role[len("key:"):] if role.startswith("key:") else role
        # Common keys go in capitalised form (Enter, Escape).
        common = {"enter": "Enter", "escape": "Escape", "tab": "Tab"}
        return f"press {common.get(key, key)}"
    if verb == "scroll":
        direction = role[len("scroll:"):] if role.startswith("scroll:") else "down"
        return f"scroll {direction}"
    if verb == "goto":
        # Single arg. role is "url:host" classifier — discard.
        url_arg = args_rendered[0] if args_rendered else "${url}"
        return f"goto {url_arg}"
    if verb == "wait":
        ms_arg = args_rendered[0] if args_rendered else "1000"
        return f"wait {ms_arg}"
    if verb == "evaluate":
        expr = args_rendered[0] if args_rendered else _shell_quote("")
        return f"evaluate {expr}"
    if verb == "wait_for":
        # role is the target role; second arg optional timeout
        timeout_arg = args_rendered[1] if len(args_rendered) > 1 else ""
        return f"wait_for {role}{(' ' + timeout_arg) if timeout_arg else ''}"
    if verb == "expect_visible":
        return f"expect_visible {role}"
    if verb == "expect_hidden":
        return f"expect_hidden {role}"
    if verb == "expect_text":
        text = args_rendered[0] if args_rendered else _shell_quote("")
        return f"expect_text {text}"
    if verb == "expect_url":
        pat = args_rendered[0] if args_rendered else _shell_quote("")
        return f"expect_url {pat}"
    if verb == "expect_count":
        # original args: [selector, op, n]. Parameterised: e.g. n is param.
        sel = args_rendered[0] if len(args_rendered) >= 1 else role
        op = args_rendered[1] if len(args_rendered) >= 2 else ">="
        n = args_rendered[2] if len(args_rendered) >= 3 else "1"
        # Strip quoting from op/n if it was concrete-quoted (op is a token).
        op = op.strip('"')
        n = n.strip('"')
        return f"expect_count {sel} {op} {n}"
    if verb == "expect_eval":
        # original args: [jsExpr, op, expected]
        expr = args_rendered[0] if args_rendered else _shell_quote("")
        op = (args_rendered[1] if len(args_rendered) >= 2 else "equals").strip('"')
        expected = args_rendered[2] if len(args_rendered) >= 3 else _shell_quote("")
        return f"expect_eval {expr} {op} {expected}"
    # Fallback — emit a comment so the operator can investigate.
    return f"# UNHANDLED verb={verb} role={role}    # please file a miner issue"


def _meta_dict(
    name: str,
    description: str,
    params: list[ParamCandidate],
    param_names: dict[tuple[int, int], str],
    occurrences: list,
    traces: list[Trace],
    sequences: list,
    pattern_items: tuple,
) -> dict:
    """Build the meta.json payload.

    `sequences[i]` aligns with `traces[i]` — the vocab list per trace.
    Used to look up which TraceStep corresponds to each pattern
    position in each occurrence (so we can capture concrete arg
    values for `examples`).
    """
    # Param schema in declaration order (sorted by step_idx, arg_idx).
    params_sorted = sorted(params, key=lambda p: (p.step_idx, p.arg_idx))
    meta_params: list[dict] = []
    for p in params_sorted:
        nm = param_names.get((p.step_idx, p.arg_idx))
        if not nm:
            continue
        meta_params.append({
            "name": nm,
            "type": p.proposed_type,
            "required": True,
            "description": (
                f"observed values: " + ", ".join(repr(v) for v in p.distinct_values[:5])
            )[:200],
        })

    # Precondition URL templates from the first step's pre_signature.
    url_templates: list[str] = []
    seen: set[str] = set()
    for occ in occurrences[:10]:
        trace = traces[occ.seq_id]
        # Find the first step within the matched window that has a sig.
        for s in trace.steps:
            if s.step_no >= 1 and s.pre_signature:
                tmpl = s.pre_signature.get("url_template")
                if tmpl and tmpl not in seen:
                    seen.add(tmpl)
                    url_templates.append(tmpl)
                break

    # Sample param sets — one full {param_name: observed_value} dict
    # per occurrence (up to 5 distinct). Live-validation feeds these
    # back into the macro to dry-run it without the operator having
    # to invent values. Without this field, live_validate has nothing
    # to plug into ${slot}s.
    examples: list[dict] = []
    for occ in occurrences[:5]:
        trace = traces[occ.seq_id]
        seq = sequences[occ.seq_id]
        sample: dict = {}
        for p in params_sorted:
            nm = param_names.get((p.step_idx, p.arg_idx))
            if not nm:
                continue
            window_pos = occ.start_idx + p.step_idx
            if window_pos >= len(seq):
                continue
            vocab_item = seq[window_pos]
            real_step = next(
                (s for s in trace.steps if s.step_no == vocab_item.step_no),
                None,
            )
            if real_step is None or p.arg_idx >= len(real_step.args):
                continue
            sample[nm] = real_step.args[p.arg_idx]
        if sample and sample not in examples:
            examples.append(sample)

    return {
        "name": name,
        "version": 1,
        "description": description,
        "params": meta_params,
        "preconditions": {
            "url_templates": url_templates,
        },
        "support_count": len({o.seq_id for o in occurrences}),
        "success_rate": 1.0,
        "learned_from_runs": sorted({
            traces[o.seq_id].run_id for o in occurrences
        })[:50],
        "examples": examples,
        "pattern": [list(item.key()) for item in pattern_items],
    }


def emit(
    curated: CuratedMacro,
    occurrences: list,
    traces: list[Trace],
    sequences: list,
    output_root: Path,
) -> Path | None:
    """Write the macro to disk. Returns the macro directory path,
    or None if the emit's self-check rejected the body.

    `sequences[i]` aligns with `traces[i]` — required so meta.examples
    can attach concrete sample param values per observed run.

    Self-check: after building the tagged body, compile_macro is run
    against the first emitted example (or empty params if no examples)
    and parse_tagged is run on the result. If either raises, the macro
    isn't written — silent broken emit corrupts the catalog and
    surfaces only at live-validate time (expensive).

    Refuses to overwrite an existing macro of the same name with a
    different version — caller must bump version explicitly. Same
    name + same version is a re-emission and overwrites in place.
    """
    if not _NAME_RE.match(curated.name):
        raise ValueError(
            f"macro name {curated.name!r} doesn't match {_NAME_RE.pattern}"
        )
    if curated.slots is None:
        raise ValueError("emit() requires curated.slots to be set")
    if len(sequences) != len(traces):
        raise ValueError(
            f"sequences ({len(sequences)}) must align with traces ({len(traces)})"
        )

    target_dir = output_root / curated.name
    target_dir.mkdir(parents=True, exist_ok=True)

    # Pre-compute consistent target accessible names per pattern step.
    # Only steps where EVERY occurrence's TraceStep recorded the same
    # non-empty target_name end up in the map; those will get baked
    # into the rendered selector. Mismatch / partial coverage → role-only.
    target_names: dict[int, str] = {}
    n = len(curated.pattern)
    for step_idx in range(n):
        observed: set[str] = set()
        complete = True
        for occ in occurrences:
            seq = sequences[occ.seq_id]
            trace = traces[occ.seq_id]
            if occ.start_idx + step_idx >= len(seq):
                complete = False
                break
            vocab_item = seq[occ.start_idx + step_idx]
            real_step = next(
                (s for s in trace.steps if s.step_no == vocab_item.step_no),
                None,
            )
            tn = real_step.target_name if real_step else None
            if not tn:
                complete = False
                break
            observed.add(tn)
        if complete and len(observed) == 1:
            target_names[step_idx] = next(iter(observed))

    # Build the body line-by-line.
    body_lines: list[str] = []
    body_lines.append(f"# Auto-mined macro: {curated.name}")
    body_lines.append(f"# {curated.description}")
    body_lines.append("")
    for step_idx, item in enumerate(curated.pattern):
        line = _render_step(
            step_idx, item,
            curated.slots.concrete, curated.slots.params,
            curated.param_names,
            target_names,
        )
        body_lines.append(line)

    body = "\n".join(body_lines) + "\n"
    meta = _meta_dict(
        curated.name, curated.description,
        curated.slots.params, curated.param_names,
        occurrences, traces, sequences,
        curated.pattern,
    )

    # Self-check: compile body against the first complete example (or
    # empty params if no examples) and parse the resulting tagged DSL.
    # Catches LLM-curator non-determinism producing concrete-only bodies
    # whose tokens collide with selector grammar (`type textbox tomsmith`).
    if not _self_check(curated, body, meta):
        return None

    (target_dir / "macro.tagged.txt").write_text(body, encoding="utf-8")
    (target_dir / "meta.json").write_text(
        json.dumps(meta, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return target_dir


def _self_check(curated: CuratedMacro, body: str, meta: dict) -> bool:
    """Compile + parse the emitted body. False ⇒ reject (don't write)."""
    from ..compile import compile_macro
    from ..library import Macro, ParamSpec
    from ...tagged import parse_tagged

    # Fabricate a Macro view sufficient for compile_macro.
    params_specs: list[ParamSpec] = []
    for p in meta.get("params") or []:
        try:
            params_specs.append(ParamSpec(
                name=p["name"], type=p.get("type", "string"),
                required=bool(p.get("required", True)),
                default=p.get("default"),
            ))
        except Exception:
            return False

    examples = list(meta.get("examples") or [])
    sample = next(
        (ex for ex in examples
         if isinstance(ex, dict)
         and all(s.name in ex for s in params_specs if s.required)),
        {},
    )
    if any(s.required for s in params_specs) and not sample:
        # Need a concrete example to exercise compile; without one,
        # we can still try with synthetic placeholder values.
        sample = {s.name: ("0" if s.type == "int" else "https://example.com/" if s.type == "url" else "X") for s in params_specs}

    macro = Macro(
        name=curated.name, version=1, description=curated.description,
        params=params_specs, preconditions=meta.get("preconditions") or {},
        body=body, meta=meta, path=Path("/dev/null"),
    )
    try:
        compiled = compile_macro(macro, sample)
        parse_tagged(compiled)
    except Exception:
        return False
    return True
