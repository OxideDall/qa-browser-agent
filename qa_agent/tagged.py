"""Tagged DSL — structured, LLM-less assertion runner.

Counterpart to the natural-language `agent.py::run_task` flow. Where
that path uses an LLM to interpret a screenshot and a DSL snapshot,
this path takes an explicit list of typed steps and executes them
deterministically against Playwright. No vision, no evidence gate,
no loop detection — assertions either pass or the run FAILs at the
first one that doesn't.

Use this for:
  * smoke tests where the assertions are well-known up front
  * CI checks where you want zero LLM cost and deterministic timing
  * regressions where you'd otherwise be fighting vision hallucinations
    on a step that's a one-line DOM check

Use the LLM path for:
  * exploratory / "log in and find X" tasks
  * any flow where the page structure varies run to run
  * cases where the agent needs to react to mid-run state

Grammar (one step per line; `#` starts a comment, blank lines skipped):

    click <selector>
    type <selector> "text"
    goto <url>
    wait <ms>
    wait_for <selector> [timeout_ms]
    press <key>
    scroll up|down
    evaluate <jsExpr>
    screenshot

    expect_visible <selector> [timeout_ms]
    expect_hidden <selector> [timeout_ms]
    expect_text "<substring>"
    expect_url <regex>
    expect_count <selector> <op> <n>
    expect_eval <jsExpr> <op> "<expected>"
        # op ∈ {equals, contains, matches, ==, !=, >, >=, <, <=}

Selectors:
    button "OK"            -> page.get_by_role("button", name="OK")
    dialog                 -> page.get_by_role("dialog")
    "Click me"             -> page.get_by_text("Click me")
    .alert-row             -> page.locator(".alert-row")
    [data-testid=foo]      -> page.locator("[data-testid=foo]")
"""

from __future__ import annotations

import json
import re
import shlex
from dataclasses import dataclass, field
from typing import Any

from playwright.sync_api import Page, TimeoutError as PwTimeout


# ---------------------------------------------------------------------------
# Step dataclass + parser
# ---------------------------------------------------------------------------

# Verbs the parser knows. Anything else is a parse error.
_ACTION_VERBS = frozenset({
    "click", "type", "goto", "wait", "wait_for", "press", "scroll",
    "evaluate", "screenshot", "macro",
})
_ASSERT_VERBS = frozenset({
    "expect_visible", "expect_hidden", "expect_text", "expect_url",
    "expect_count", "expect_eval",
})
ALL_VERBS = _ACTION_VERBS | _ASSERT_VERBS

# Roles we accept after `<role> "name"`. Mirrors Playwright's get_by_role
# valid set; missing role here -> falls through to text/css resolver.
_ROLES = frozenset({
    "alert", "alertdialog", "application", "article", "banner",
    "blockquote", "button", "caption", "cell", "checkbox", "code",
    "columnheader", "combobox", "complementary", "contentinfo",
    "definition", "deletion", "dialog", "directory", "document",
    "emphasis", "feed", "figure", "form", "generic", "grid",
    "gridcell", "group", "heading", "img", "insertion", "link",
    "list", "listbox", "listitem", "log", "main", "marquee", "math",
    "meter", "menu", "menubar", "menuitem", "menuitemcheckbox",
    "menuitemradio", "navigation", "none", "note", "option",
    "paragraph", "presentation", "progressbar", "radio", "radiogroup",
    "region", "row", "rowgroup", "rowheader", "scrollbar", "search",
    "searchbox", "separator", "slider", "spinbutton", "status",
    "strong", "subscript", "superscript", "switch", "tab", "table",
    "tablist", "tabpanel", "term", "textbox", "time", "timer",
    "toolbar", "tooltip", "tree", "treegrid", "treeitem",
})

# Comparison ops for expect_count / expect_eval.
_OPS = frozenset({"==", "!=", ">", ">=", "<", "<=",
                  "equals", "contains", "matches"})


class TaggedParseError(ValueError):
    """Raised when parse_tagged hits a malformed step."""


@dataclass
class Step:
    verb: str
    args: list[str]
    line_no: int
    raw: str

    def __str__(self) -> str:
        return f"{self.verb} {' '.join(self.args)}".strip()


def parse_tagged(text: str) -> list[Step]:
    """Parse a tagged-DSL block. Raises TaggedParseError on first
    malformed step (we want hard-fail at parse time, not surprise
    failures at runtime)."""
    steps: list[Step] = []
    for i, raw_line in enumerate(text.splitlines(), start=1):
        # Strip a leading `- ` (operator preference; copy-pastable
        # from a YAML-ish bulleted list) and trailing whitespace.
        line = raw_line.strip()
        if line.startswith("- "):
            line = line[2:].strip()
        if not line or line.startswith("#"):
            continue

        # First token is the verb; rest goes to per-verb arg parser.
        # shlex.split handles quoted strings ("hello world" stays one token).
        try:
            tokens = shlex.split(line, posix=True)
        except ValueError as e:
            raise TaggedParseError(
                f"line {i}: shlex error: {e}: {raw_line!r}"
            ) from e

        if not tokens:
            continue
        verb = tokens[0].lower()
        if verb not in ALL_VERBS:
            raise TaggedParseError(
                f"line {i}: unknown verb {verb!r}. Known: "
                f"{sorted(ALL_VERBS)}"
            )

        args = tokens[1:]
        _validate_args(verb, args, i)
        steps.append(Step(verb=verb, args=args, line_no=i, raw=raw_line))

    return steps


def _validate_args(verb: str, args: list[str], line_no: int) -> None:
    """Per-verb minimum-arity checks. Catches typos at parse time."""
    def need(min_n: int, hint: str) -> None:
        if len(args) < min_n:
            raise TaggedParseError(
                f"line {line_no}: {verb} needs {hint}, got {args!r}"
            )

    if verb in ("click", "wait_for", "expect_visible", "expect_hidden"):
        need(1, "<selector> [timeout_ms]")
    elif verb == "type":
        need(2, '<selector> "text"')
    elif verb == "goto":
        need(1, "<url>")
    elif verb == "wait":
        need(1, "<ms>")
        try:
            int(args[0])
        except ValueError:
            raise TaggedParseError(
                f"line {line_no}: wait expects integer ms, got {args[0]!r}"
            )
    elif verb == "press":
        need(1, "<key>")
    elif verb == "scroll":
        need(1, "up|down")
        if args[0] not in ("up", "down"):
            raise TaggedParseError(
                f"line {line_no}: scroll expects up|down, got {args[0]!r}"
            )
    elif verb == "evaluate":
        need(1, "<jsExpr>")
    elif verb == "macro":
        need(1, "<name> [k=v ...]")
        # Validate that any param tokens look like `key=value`.
        for tok in args[1:]:
            if "=" not in tok:
                raise TaggedParseError(
                    f"line {line_no}: macro params must be key=value, "
                    f"got {tok!r}"
                )
    elif verb == "expect_text":
        need(1, '"<substring>"')
    elif verb == "expect_url":
        need(1, "<regex>")
    elif verb == "expect_count":
        need(3, "<selector> <op> <n>")
        if args[1] not in _OPS:
            raise TaggedParseError(
                f"line {line_no}: expect_count op must be one of "
                f"{sorted(_OPS)}, got {args[1]!r}"
            )
        try:
            int(args[2])
        except ValueError:
            raise TaggedParseError(
                f"line {line_no}: expect_count needs integer count, "
                f"got {args[2]!r}"
            )
    elif verb == "expect_eval":
        need(3, '<jsExpr> <op> "<expected>"')
        if args[1] not in _OPS:
            raise TaggedParseError(
                f"line {line_no}: expect_eval op must be one of "
                f"{sorted(_OPS)}, got {args[1]!r}"
            )


# ---------------------------------------------------------------------------
# Selector resolver
# ---------------------------------------------------------------------------

def resolve_selector(page: Page, sel: str):
    """Turn a tagged-DSL selector string into a Playwright Locator."""
    sel = sel.strip()
    if not sel:
        raise ValueError("empty selector")

    # role: `button "name"`, `dialog`, `tab "Activity"`. Role optionally
    # followed by a quoted accessible name. shlex already stripped the
    # quotes — args[0] would be just `button` here, with the name in
    # args[1] — but resolve_selector also handles the un-split form
    # (used by callers that pass the trailing tokens in one string).
    m = re.match(r'^([a-z]+)(?:\s+"([^"]+)")?\s*$', sel)
    if m and m.group(1) in _ROLES:
        role = m.group(1)
        name = m.group(2)
        loc = (page.get_by_role(role, name=name)
               if name else page.get_by_role(role))
        return loc.first

    # `text:"..."` explicit text matcher
    m = re.match(r'^text:"([^"]+)"\s*$', sel)
    if m:
        return page.get_by_text(m.group(1)).first

    # Bare quoted string -> text matcher (operator shorthand).
    m = re.match(r'^"([^"]+)"\s*$', sel)
    if m:
        return page.get_by_text(m.group(1)).first

    # Anything else: hand it to Playwright's locator engine. Covers
    # CSS, [attr=value], data-testid=foo, xpath= etc.
    return page.locator(sel).first


def _resolve_role_pair(role: str, name: str | None, page: Page):
    """Helper for callers that already have role + name as separate
    tokens (shlex-split). Used by `click button "OK"` etc."""
    if name is not None:
        return page.get_by_role(role, name=name).first
    return page.get_by_role(role).first


def _resolve_selector_args(args: list[str], page: Page):
    """Resolve one selector from leading tokens of `args`. Returns
    (locator, consumed_token_count) so callers can read remaining
    args (e.g. timeout_ms) past the selector."""
    if not args:
        raise ValueError("missing selector")
    head = args[0]
    # role + optional quoted name (shlex consumed quotes; if the second
    # token would otherwise look like an operator, callers must pass
    # the name explicitly via `text:`).
    if head in _ROLES:
        if len(args) >= 2 and not _looks_like_op_or_int(args[1]):
            return _resolve_role_pair(head, args[1], page), 2
        return _resolve_role_pair(head, None, page), 1
    # bare CSS / text / etc.
    return resolve_selector(page, head), 1


def _looks_like_op_or_int(tok: str) -> bool:
    """A trailing token after the selector that is clearly NOT an
    accessible name — used to decide where the selector ends."""
    if tok in _OPS:
        return True
    try:
        int(tok)
        return True
    except ValueError:
        return False


# ---------------------------------------------------------------------------
# Step executor
# ---------------------------------------------------------------------------

DEFAULT_STEP_TIMEOUT = 5000   # ms — Playwright default for assertions
DEFAULT_TYPE_DELAY = 20       # ms per keystroke


@dataclass
class StepResult:
    step_no: int
    verb: str
    args: list[str]
    status: str                       # "PASS" | "FAIL" | "ERROR"
    message: str = ""
    eval_result: Any = None
    latency_ms: int = 0


def execute_step(page: Page, step: Step) -> StepResult:
    """Run one step. Always returns a StepResult; status `PASS` if it
    succeeded, `FAIL` for assertion miss / element not found / JS
    throw, `ERROR` for unexpected internal errors. The caller decides
    whether to continue.
    """
    import time as _time
    t0 = _time.time()
    res = StepResult(step_no=step.line_no, verb=step.verb,
                     args=list(step.args), status="ERROR")
    try:
        handler = _HANDLERS.get(step.verb)
        if handler is None:
            res.status = "ERROR"
            res.message = f"no handler for verb {step.verb!r}"
        else:
            handler(page, step, res)
            if res.status == "ERROR":
                # handler didn't set status — implicit PASS
                res.status = "PASS"
    except PwTimeout as e:
        res.status = "FAIL"
        res.message = f"TIMEOUT: {str(e)[:300]}"
    except AssertionError as e:
        res.status = "FAIL"
        res.message = str(e)[:500]
    except Exception as e:
        res.status = "FAIL"
        res.message = f"{type(e).__name__}: {str(e)[:300]}"
    res.latency_ms = int((_time.time() - t0) * 1000)
    return res


# Per-verb handlers. Each takes (page, step, res) and either:
#   * sets res.status = "FAIL" + res.message on miss, or
#   * raises (Playwright timeouts / asserts get caught above), or
#   * leaves res.status = "ERROR" — caller flips to PASS.

def _h_click(page: Page, step: Step, res: StepResult) -> None:
    loc, _ = _resolve_selector_args(step.args, page)
    loc.click(timeout=DEFAULT_STEP_TIMEOUT)
    res.message = f"clicked {' '.join(step.args)}"


def _h_type(page: Page, step: Step, res: StepResult) -> None:
    # type <selector> "text" — selector may be 1 or 2 tokens (role + name).
    loc, consumed = _resolve_selector_args(step.args, page)
    rest = step.args[consumed:]
    if not rest:
        raise ValueError(f"type missing text after selector: {step.args!r}")
    text = rest[0]
    loc.click(timeout=DEFAULT_STEP_TIMEOUT)
    page.keyboard.press("Control+a")
    page.keyboard.press("Delete")
    loc.type(text, delay=DEFAULT_TYPE_DELAY)
    res.message = f"typed {text!r}"


def _h_goto(page: Page, step: Step, res: StepResult) -> None:
    page.goto(step.args[0], timeout=15000, wait_until="domcontentloaded")
    res.message = f"navigated to {step.args[0]}"


def _h_wait(page: Page, step: Step, res: StepResult) -> None:
    page.wait_for_timeout(int(step.args[0]))
    res.message = f"waited {step.args[0]}ms"


def _h_wait_for(page: Page, step: Step, res: StepResult) -> None:
    loc, consumed = _resolve_selector_args(step.args, page)
    rest = step.args[consumed:]
    timeout = int(rest[0]) if rest else DEFAULT_STEP_TIMEOUT
    loc.wait_for(state="visible", timeout=timeout)
    res.message = f"appeared: {' '.join(step.args[:consumed])}"


def _h_press(page: Page, step: Step, res: StepResult) -> None:
    page.keyboard.press(step.args[0])
    res.message = f"pressed {step.args[0]}"


def _h_scroll(page: Page, step: Step, res: StepResult) -> None:
    delta = -500 if step.args[0] == "up" else 500
    page.mouse.wheel(0, delta)
    page.wait_for_timeout(200)
    res.message = f"scrolled {step.args[0]}"


def _h_screenshot(page: Page, step: Step, res: StepResult) -> None:
    # The actual screenshot is taken by the runner's per-step shot —
    # this is a no-op marker so users can request a manual checkpoint.
    res.message = "screenshot checkpoint"


def _h_evaluate(page: Page, step: Step, res: StepResult) -> None:
    # Reuse the LLM-path evaluator so wrapping / truncation is identical.
    from .actions import _execute_evaluate
    out = _execute_evaluate(page, " ".join(step.args))
    res.eval_result = out
    res.message = out
    if out.startswith(("EVAL_ERROR:", "EVAL_THROW:")):
        res.status = "FAIL"


def _h_expect_visible(page: Page, step: Step, res: StepResult) -> None:
    loc, consumed = _resolve_selector_args(step.args, page)
    rest = step.args[consumed:]
    timeout = int(rest[0]) if rest else DEFAULT_STEP_TIMEOUT
    loc.wait_for(state="visible", timeout=timeout)
    res.message = f"visible: {' '.join(step.args[:consumed])}"


def _h_expect_hidden(page: Page, step: Step, res: StepResult) -> None:
    loc, consumed = _resolve_selector_args(step.args, page)
    rest = step.args[consumed:]
    timeout = int(rest[0]) if rest else DEFAULT_STEP_TIMEOUT
    loc.wait_for(state="hidden", timeout=timeout)
    res.message = f"hidden: {' '.join(step.args[:consumed])}"


def _h_expect_text(page: Page, step: Step, res: StepResult) -> None:
    needle = step.args[0]
    body = page.locator("body").inner_text(timeout=DEFAULT_STEP_TIMEOUT)
    if needle not in body:
        res.status = "FAIL"
        sample = body.replace("\n", " ")[:200]
        res.message = f"text {needle!r} not on page. body[0:200]={sample!r}"
        return
    res.message = f"text found: {needle!r}"


def _h_expect_url(page: Page, step: Step, res: StepResult) -> None:
    pattern = step.args[0]
    cur = page.url
    if not re.search(pattern, cur):
        res.status = "FAIL"
        res.message = f"url {cur!r} does not match /{pattern}/"
        return
    res.message = f"url matches: {cur}"


def _h_expect_count(page: Page, step: Step, res: StepResult) -> None:
    sel, op, expected = step.args[0], step.args[1], int(step.args[2])
    loc = resolve_selector(page, sel)
    # Locator.first was used for actions; for count we need the full set.
    # Re-resolve without `.first`.
    if sel in _ROLES:
        full = page.get_by_role(sel)
    else:
        full = page.locator(sel)
    actual = full.count()
    if not _compare_int(actual, op, expected):
        res.status = "FAIL"
        res.message = f"expect_count {sel!r}: actual={actual} {op} {expected} -> false"
        return
    res.message = f"count {actual} {op} {expected}"


def _h_macro(page: Page, step: Step, res: StepResult) -> None:
    """Resolve the named macro, substitute params, recursively execute
    its compiled body. Failure of any sub-step propagates up — this
    macro step's status becomes that sub-step's status, and the
    sub-step's message is prefixed with the macro name + line index."""
    from .macros import compile_macro, load_macro
    name = step.args[0]
    params: dict[str, str] = {}
    for tok in step.args[1:]:
        k, _, v = tok.partition("=")
        params[k] = v

    try:
        macro = load_macro(name)
    except Exception as e:
        res.status = "FAIL"
        res.message = f"macro {name!r}: {type(e).__name__}: {e}"
        return

    try:
        body = compile_macro(macro, params)
    except Exception as e:
        res.status = "FAIL"
        res.message = f"macro {name!r} compile: {type(e).__name__}: {e}"
        return

    try:
        nested_steps = parse_tagged(body)
    except Exception as e:
        res.status = "FAIL"
        res.message = f"macro {name!r} parse: {type(e).__name__}: {e}"
        return

    sub_results: list[dict] = []
    for n, sub in enumerate(nested_steps, start=1):
        sub_res = execute_step(page, sub)
        sub_results.append({
            "n": n, "verb": sub.verb, "args": list(sub.args),
            "status": sub_res.status, "message": sub_res.message,
            "latency_ms": sub_res.latency_ms,
        })
        if sub_res.status != "PASS":
            res.status = sub_res.status
            res.message = (
                f"macro {name!r} step {n} ({sub.verb}) "
                f"{sub_res.status}: {sub_res.message}"
            )
            res.eval_result = sub_results
            return

    res.message = f"macro {name!r} ok ({len(nested_steps)} steps)"
    res.eval_result = sub_results


def _h_expect_eval(page: Page, step: Step, res: StepResult) -> None:
    from .actions import _execute_evaluate
    js_expr = step.args[0]
    op = step.args[1]
    expected_raw = step.args[2]
    out = _execute_evaluate(page, js_expr)
    if out.startswith(("EVAL_ERROR:", "EVAL_THROW:")):
        res.status = "FAIL"
        res.message = f"expect_eval threw: {out}"
        return

    # _execute_evaluate returns "eval -> <stringified>". Strip prefix.
    actual_str = out[len("eval -> "):] if out.startswith("eval -> ") else out
    res.eval_result = actual_str

    # Try to compare numerically when both look numeric; otherwise string.
    if op in ("==", "!=", ">", ">=", "<", "<="):
        try:
            actual_n = float(actual_str)
            expected_n = float(expected_raw)
            ok = _compare_float(actual_n, op, expected_n)
            res.message = f"{actual_n} {op} {expected_n} -> {ok}"
            if not ok:
                res.status = "FAIL"
            return
        except ValueError:
            ok = _compare_str(actual_str, op, expected_raw)
            res.message = f"{actual_str!r} {op} {expected_raw!r} -> {ok}"
            if not ok:
                res.status = "FAIL"
            return
    if op == "equals":
        ok = actual_str == expected_raw
        res.message = f"{actual_str!r} == {expected_raw!r} -> {ok}"
        if not ok:
            res.status = "FAIL"
        return
    if op == "contains":
        ok = expected_raw in actual_str
        res.message = f"{expected_raw!r} in {actual_str!r} -> {ok}"
        if not ok:
            res.status = "FAIL"
        return
    if op == "matches":
        ok = re.search(expected_raw, actual_str) is not None
        res.message = f"/{expected_raw}/ ~ {actual_str!r} -> {ok}"
        if not ok:
            res.status = "FAIL"
        return
    res.status = "FAIL"
    res.message = f"unknown op {op!r}"


def _compare_int(a: int, op: str, b: int) -> bool:
    return _compare_float(float(a), op, float(b))


def _compare_float(a: float, op: str, b: float) -> bool:
    if op == "==":
        return a == b
    if op == "!=":
        return a != b
    if op == ">":
        return a > b
    if op == ">=":
        return a >= b
    if op == "<":
        return a < b
    if op == "<=":
        return a <= b
    raise ValueError(f"bad numeric op {op!r}")


def _compare_str(a: str, op: str, b: str) -> bool:
    if op == "==":
        return a == b
    if op == "!=":
        return a != b
    raise ValueError(f"string compare doesn't support op {op!r}")


_HANDLERS = {
    "click": _h_click,
    "type": _h_type,
    "goto": _h_goto,
    "wait": _h_wait,
    "wait_for": _h_wait_for,
    "press": _h_press,
    "scroll": _h_scroll,
    "screenshot": _h_screenshot,
    "evaluate": _h_evaluate,
    "macro": _h_macro,
    "expect_visible": _h_expect_visible,
    "expect_hidden": _h_expect_hidden,
    "expect_text": _h_expect_text,
    "expect_url": _h_expect_url,
    "expect_count": _h_expect_count,
    "expect_eval": _h_expect_eval,
}
