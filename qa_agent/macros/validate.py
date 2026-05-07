"""Live-page macro validation.

Phase 1 (offline miner) ships macros whose tagged-DSL bodies pass
*structural* alignment against captured traces. That catches inference
errors where the parameter slots / concrete args were misclassified
relative to the source data, but it does NOT catch:

  * a role-only selector that doesn't actually resolve on the live
    page (e.g. the captures had a `button "Submit"` accessible name
    but the role-only `button` selector binds to a different button)
  * site drift between mining time and validation time
  * timing assumptions baked into the macro that weren't apparent
    in static traces (race conditions on a slow backend)

`live_validate` actually drives a browser through the compiled macro
and reports per-step verdicts. Cost: one full browser launch per
candidate. Use selectively (e.g. behind miner's `--live-validate`
flag, or on operator demand for hand-curated macros).

This is Phase 1.5 in the macro design — separate from the miner
(it's an *optional* validator, not a mining stage) but living
alongside the macro library because it's a public service: any
operator can run it after writing a macro by hand.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .compile import compile_macro
from .library import Macro


@dataclass
class LiveValidationResult:
    """Outcome of a single live-validation run."""
    passed: bool
    macro_name: str
    params_used: dict
    status: str                          # PASS / FAIL / ERROR
    description: str
    n_steps: int
    n_passed: int
    score: float                         # n_passed / n_steps (0.0 if n=0)
    failed_step: int | None              # 1-based; None if all PASS
    failed_message: str = ""
    confidence: float | None = None
    elapsed: float = 0.0
    capture_path: str | None = None      # JSONL of the validation run
    screenshots_dir: str | None = None
    step_results: list[dict] = field(default_factory=list)


def _pick_example_params(macro: Macro) -> dict:
    """First entry from meta.examples that covers every required param.
    Falls back to defaults of optional params + best-effort first
    example for required ones. Raises ValueError if a required param
    has no example value anywhere — caller must supply explicitly.

    Tolerates two shapes (matching online/actions._params_from_examples):
      * Anchored: `{"url_template": "...", "params": {...}}` — current.
      * Flat:     `{"key": "value", ...}`                   — legacy.
    """
    examples = list(macro.meta.get("examples") or [])
    required = [p.name for p in macro.params if p.required]

    def _params_of(ex: dict) -> dict:
        """Extract the inner params dict from either example shape."""
        if "params" in ex and isinstance(ex.get("params"), dict):
            return ex["params"]
        return ex

    for ex in examples:
        if not isinstance(ex, dict):
            continue
        params = _params_of(ex)
        if all(name in params for name in required):
            return dict(params)

    # No complete example — assemble best-effort from per-key first
    # occurrence in any example, plus optional defaults.
    sample: dict = {}
    for name in required:
        for ex in examples:
            if not isinstance(ex, dict):
                continue
            params = _params_of(ex)
            if name in params:
                sample[name] = params[name]
                break
    for p in macro.params:
        if not p.required and p.name not in sample and p.default is not None:
            sample[p.name] = p.default

    missing = [n for n in required if n not in sample]
    if missing:
        raise ValueError(
            f"macro {macro.name!r}: no examples for required params {missing}; "
            f"supply --param explicitly"
        )
    return sample


def live_validate(
    macro: Macro,
    *,
    params: dict | None = None,
    url: str | None = None,
    headless: bool = True,
    http_credentials: dict | None = None,
    trace: bool = False,
) -> LiveValidationResult:
    """Replay `macro` against a real browser and score the result.

    `params` overrides the param dict; if None, picks a sample set from
    `meta.examples` (the miner emits one per observed occurrence). If
    the macro has no examples and no params are passed, raises
    ValueError — operator must supply values explicitly.

    `url` overrides the URL precondition; if None, the macro's first
    `meta.preconditions.url_templates` entry is used (must be a
    concrete URL — templates with `<num>` / `<slug>` placeholders
    can't be re-navigated and require explicit `url=`).

    Returns a LiveValidationResult — does NOT raise on macro failure;
    a FAIL run is a valid validation outcome. Raises only if the run
    couldn't start (compile error, missing required params, browser
    couldn't launch).
    """
    # Resolve params first so we can fail fast on missing values
    # before paying for a browser launch.
    if params is None:
        params = _pick_example_params(macro)

    # Compile to verify the body parses with these params; catches
    # placeholder typos / type mismatches before browser startup.
    compile_macro(macro, params)

    # URL: explicit > meta.preconditions.url_templates[0] (if concrete).
    effective_url = url
    if effective_url is None:
        for tmpl in (macro.preconditions.get("url_templates") or []):
            if "<" not in tmpl:        # not a template, real URL
                effective_url = tmpl
                break

    # Defer the import to runtime — keeps `python -m qa_agent.macros`
    # imports cheap when the user is not actually validating.
    from ..agent import run_macro_task

    summary: dict[str, Any] = {}

    def _capture(rec: dict) -> None:
        summary.update(rec)

    status, description, steps_used = run_macro_task(
        macro.name, params,
        url=effective_url,
        headless=headless,
        http_credentials=http_credentials,
        trace=trace,
        on_finish=_capture,
        macros_root=macro.path.parent,
    )

    step_results = list(summary.get("step_results") or [])
    n_steps = len(step_results)
    n_passed = sum(
        1 for r in step_results if str(r.get("status")) == "PASS"
    )
    score = n_passed / n_steps if n_steps else 0.0

    failed_step: int | None = None
    failed_message = ""
    for i, r in enumerate(step_results, start=1):
        if str(r.get("status")) != "PASS":
            failed_step = i
            failed_message = str(r.get("message") or "")[:300]
            break

    return LiveValidationResult(
        passed=status == "PASS",
        macro_name=macro.name,
        params_used=dict(params),
        status=status,
        description=description,
        n_steps=n_steps,
        n_passed=n_passed,
        score=round(score, 4),
        failed_step=failed_step,
        failed_message=failed_message,
        confidence=summary.get("confidence"),
        elapsed=float(summary.get("wall_seconds") or 0.0),
        capture_path=None,                 # populated by run_macro_task via capture writer
        screenshots_dir=summary.get("screenshots_dir"),
        step_results=step_results,
    )
