"""Action DSL: parse + execute. DSL is what the LLM emits (click/type/goto/...)."""

import json
import re
from datetime import datetime

from playwright.sync_api import Page, TimeoutError as PwTimeout

from .config import MAX_WAIT_MS, SCREENSHOT_DIR, STEP_TIMEOUT, NAV_TIMEOUT

# Cap for stringified `evaluate` result returned to the LLM. Past this we
# truncate so a runaway DOM-dump can't blow the context window. Whole
# untruncated value goes into ctx.last_result for the recorder.
EVAL_RESULT_MAX = 1500


def parse_action(response_text: str) -> tuple[str, list[str]]:
    """Parse one-line DSL action from LLM response. Returns (command, args).

    Tolerant to markdown fences and extra lines — picks first recognized command.
    """
    line = response_text.strip()
    for candidate in line.split("\n"):
        candidate = candidate.strip()
        if candidate and candidate.split()[0] in (
            "click", "type", "select", "hover", "scroll",
            "goto", "wait", "done", "screenshot", "look", "tab", "press",
            "evaluate", "macro",
        ):
            line = candidate
            break

    parts = line.split(None, 1)
    if not parts:
        return ("error", ["Empty response"])

    cmd = parts[0].lower()
    rest = parts[1] if len(parts) > 1 else ""

    if cmd == "click":
        # Tolerate "[5]" and "5" — strip the surrounding brackets the LLM
        # sometimes copies verbatim from the DSL snapshot header format.
        raw = rest.strip()
        m = re.match(r"^[\[<(]?(\d+)[\]>)]?\s*$", raw)
        if m:
            return ("click", [m.group(1)])
        return ("click", [raw])
    if cmd == "type":
        m = (re.match(r'[\[<(]?(\d+)[\]>)]?\s+"(.*)"', rest)
             or re.match(r"[\[<(]?(\d+)[\]>)]?\s+'(.*)'", rest))
        if m:
            return ("type", [m.group(1), m.group(2)])
        m = re.match(r"[\[<(]?(\d+)[\]>)]?\s+(.*)", rest)
        if m:
            return ("type", [m.group(1), m.group(2)])
        return ("error", [f"Cannot parse type args: {rest}"])
    if cmd == "select":
        m = (re.match(r'[\[<(]?(\d+)[\]>)]?\s+"(.*)"', rest)
             or re.match(r"[\[<(]?(\d+)[\]>)]?\s+'(.*)'", rest))
        if m:
            return ("select", [m.group(1), m.group(2)])
        return ("error", [f"Cannot parse select args: {rest}"])
    if cmd == "hover":
        raw = rest.strip()
        m = re.match(r"^[\[<(]?(\d+)[\]>)]?\s*$", raw)
        return ("hover", [m.group(1) if m else raw])
    if cmd == "scroll":
        direction = rest.strip().lower()
        return ("scroll", [direction if direction in ("up", "down") else "down"])
    if cmd == "goto":
        return ("goto", [rest.strip()])
    if cmd == "wait":
        try:
            ms = str(max(0, min(int(rest.strip()), MAX_WAIT_MS)))
        except ValueError:
            ms = "500"
        return ("wait", [ms])
    if cmd == "done":
        m = re.match(r'(PASS|FAIL)\s+"?(.*?)"?\s*$', rest, re.IGNORECASE)
        if m:
            return ("done", [m.group(1).upper(), m.group(2)])
        return ("done", ["PASS" if "pass" in rest.lower() else "FAIL", rest])
    if cmd == "screenshot":
        return ("screenshot", [])
    if cmd == "look":
        return ("look", [])
    if cmd == "tab":
        return ("tab", [rest.strip()])
    if cmd == "evaluate":
        # Whole rest of the line is JS — no quote-stripping (the JS itself
        # may need single/double quotes for selectors / strings).
        expr = rest.strip()
        if not expr:
            return ("error", ["evaluate: empty expression"])
        return ("evaluate", [expr])
    if cmd == "macro":
        # macro <name> [k=v] [k=v] ...  First token is the macro name,
        # rest are key=value param pairs (shell-style).
        import shlex
        try:
            tokens = shlex.split(rest, posix=True)
        except ValueError as e:
            return ("error", [f"macro: shlex error: {e}"])
        if not tokens:
            return ("error", ["macro: missing name"])
        return ("macro", tokens)
    if cmd == "press":
        key = rest.strip()
        # Normalize common variants
        alias = {
            "enter": "Enter", "return": "Enter",
            "esc": "Escape", "escape": "Escape",
            "tab": "Tab",
            "backspace": "Backspace", "bksp": "Backspace",
            "delete": "Delete", "del": "Delete",
            "up": "ArrowUp", "down": "ArrowDown",
            "left": "ArrowLeft", "right": "ArrowRight",
            "space": "Space", "pageup": "PageUp", "pagedown": "PageDown",
            "home": "Home", "end": "End",
        }
        key = alias.get(key.lower(), key)
        return ("press", [key])
    return ("error", [f"Unknown action: {cmd}"])


def _execute_macro(page: Page, args: list[str]) -> str:
    """LLM-path execution of `macro <name> k=v ...`.

    Loads the named macro, substitutes params, parses the resulting
    tagged DSL, runs each sub-step on the live `page`. Returns a
    one-line human summary that the runtime feeds back into the
    conversation so the LLM knows what just happened.

    Post-macro state-delta gating (S2): captures page signature
    before and after sub-steps. If `url_template` AND `struct_hash`
    both unchanged, the macro "executed" but didn't actually move
    the page state forward — login form rejected creds, click had
    no effect, etc. The result string includes the marker
    `[page-state unchanged]` so the runtime can:
      - skip the run-lifetime success-lock (allow retry)
      - inform the LLM that the macro was inert
    """
    name = args[0]
    params: dict[str, str] = {}
    for tok in args[1:]:
        if "=" in tok:
            k, _, v = tok.partition("=")
            params[k] = v

    try:
        from .macros import compile_macro, load_macro
        from .runtime.page_signature import compute_signature
        from .tagged import execute_step, parse_tagged
        from .extract import extract_elements
    except Exception as e:
        return f"ERROR: macro module unavailable: {type(e).__name__}: {e}"

    try:
        macro = load_macro(name)
    except Exception as e:
        return f"ERROR: macro {name!r}: {type(e).__name__}: {e}"

    try:
        body = compile_macro(macro, params)
    except Exception as e:
        return f"ERROR: macro {name!r} compile: {type(e).__name__}: {e}"

    try:
        steps = parse_tagged(body)
    except Exception as e:
        return f"ERROR: macro {name!r} parse: {type(e).__name__}: {e}"

    # Capture pre-execution signature for state-delta gating.
    pre_sig: dict | None = None
    try:
        elements_pre, _, _, text_pre = extract_elements(page)
        pre_sig = compute_signature(page.url, elements_pre, text_pre)
    except Exception:
        pre_sig = None

    n_pass = 0
    failed_at: int | None = None
    failed_msg = ""
    for i, step in enumerate(steps, start=1):
        res = execute_step(page, step)
        if res.status == "PASS":
            n_pass += 1
        else:
            failed_at = i
            failed_msg = res.message[:200]
            break

    if failed_at is not None:
        return (
            f"macro {name!r} FAILED at sub-step {failed_at}/{len(steps)}: "
            f"{failed_msg}. Now on {page.url[:80]!r}."
        )

    # All sub-steps PASS — but did the page actually move?
    state_marker = ""
    try:
        elements_post, _, _, text_post = extract_elements(page)
        post_sig = compute_signature(page.url, elements_post, text_post)
        if (pre_sig is not None
                and pre_sig.get("url_template") == post_sig.get("url_template")
                and pre_sig.get("struct_hash") == post_sig.get("struct_hash")):
            state_marker = " [page-state unchanged]"
    except Exception:
        pass

    return (
        f"macro {name!r} OK: {n_pass}/{len(steps)} sub-steps "
        f"completed (params={params!r}). "
        f"Now on {page.url[:80]!r}.{state_marker}"
    )


def _execute_evaluate(page: Page, js_expr: str) -> str:
    """Run a JS expression in the page; return a stringified result.

    Wraps the expression as a function so multi-statement / arrow forms
    "just work". Stringifies via JSON for objects/arrays, falls back to
    `String(...)` for cyclic / non-serialisable values. Truncates at
    EVAL_RESULT_MAX so a runaway dump can't blow the LLM context.
    """
    expr = js_expr.strip()
    # If user already wrote a function literal, use as-is. Otherwise wrap
    # so a bare expression / multi-statement IIFE both work.
    if expr.startswith(("()", "function", "async ", "(async")):
        wrapped = expr
    else:
        wrapped = (
            "() => { try { const __r = ("
            + expr
            + "); if (__r === undefined) return '<undefined>';"
            + "  if (__r === null) return null;"
            + "  if (typeof __r === 'object') {"
            + "    try { return JSON.parse(JSON.stringify(__r)); }"
            + "    catch (e) { return String(__r); }"
            + "  }"
            + "  return __r;"
            + "} catch (e) { return '__EVAL_THROW__:' + (e && e.message || String(e)); } }"
        )
    try:
        result = page.evaluate(wrapped)
    except Exception as e:
        return f"EVAL_ERROR: {type(e).__name__}: {str(e)[:300]}"

    if isinstance(result, str) and result.startswith("__EVAL_THROW__:"):
        return f"EVAL_THROW: {result[len('__EVAL_THROW__:'):][:400]}"

    if result is None:
        return "eval -> null"
    if isinstance(result, bool):
        return f"eval -> {str(result).lower()}"
    if isinstance(result, (int, float)):
        return f"eval -> {result}"
    if isinstance(result, str):
        s = result
    else:
        try:
            s = json.dumps(result, ensure_ascii=False, default=str)
        except Exception:
            s = str(result)
    if len(s) > EVAL_RESULT_MAX:
        s = s[:EVAL_RESULT_MAX] + f"... [+{len(s) - EVAL_RESULT_MAX} chars truncated]"
    return f"eval -> {s}"


def _find_element(elements: list[dict], eid: str) -> dict | None:
    try:
        eid_int = int(eid)
    except ValueError:
        return None
    for el in elements:
        if el["id"] == eid_int:
            return el
    return None


def _el_info(elements: list[dict], eid: str) -> str:
    try:
        eid_int = int(eid)
    except ValueError:
        return f"#{eid}"
    for el in elements:
        if el["id"] == eid_int:
            desc = el["tag"]
            if el.get("text"):
                desc += f' "{el["text"][:30]}"'
            elif el.get("ph"):
                desc += f' ({el["ph"][:30]})'
            return f"[{eid}] {desc}"
    return f"#{eid} (not found)"


def _click_element(page: Page, elements: list[dict], eid: str, is_fallback: bool) -> None:
    """Click via best available selector. Falls back to coordinate click for pointer-events:none."""
    if not is_fallback:
        el_data = _find_element(elements, eid)
        try:
            page.click(f'[data-qa-id="{eid}"]', timeout=STEP_TIMEOUT)
            return
        except Exception:
            # pointer-events:none fallback — use coords from cursor:pointer second pass
            if el_data and el_data.get("_cx"):
                page.mouse.click(el_data["_cx"], el_data["_cy"])
                return
            raise

    el = _find_element(elements, eid)
    if not el:
        raise Exception(f"Element {eid} not found")

    if el.get("_sel"):
        try:
            page.click(el["_sel"], timeout=STEP_TIMEOUT)
            return
        except Exception:
            pass

    text = el.get("text", "")
    tag = el["tag"]
    if text:
        try:
            page.locator(f'{tag}:has-text("{text[:40]}")').first.click(timeout=STEP_TIMEOUT)
            return
        except Exception:
            pass
        if tag == "button" or el.get("role") == "button":
            try:
                page.get_by_role("button", name=text[:40]).first.click(timeout=STEP_TIMEOUT)
                return
            except Exception:
                pass

    # Last resort — coordinate click via stored bbox
    if el.get("_bbox"):
        b = el["_bbox"]
        page.mouse.click(b["x"] + b["width"] / 2, b["y"] + b["height"] / 2)
        return
    raise Exception(f"No viable selector for element {eid}")


def _focus_element(page: Page, elements: list[dict], eid: str, is_fallback: bool):
    """Focus input before typing. Returns locator if possible, else None for coord-only."""
    if not is_fallback:
        sel = f'[data-qa-id="{eid}"]'
        page.click(sel, timeout=STEP_TIMEOUT)
        return page.locator(sel).first

    el = _find_element(elements, eid)
    if not el:
        raise Exception(f"Element {eid} not found")
    if el.get("_sel"):
        try:
            loc = page.locator(el["_sel"]).first
            loc.click(timeout=STEP_TIMEOUT)
            return loc
        except Exception:
            pass
    if el.get("ph"):
        try:
            loc = page.get_by_placeholder(el["ph"][:40]).first
            loc.click(timeout=STEP_TIMEOUT)
            return loc
        except Exception:
            pass
    if el.get("_bbox"):
        b = el["_bbox"]
        page.mouse.click(b["x"] + b["width"] / 2, b["y"] + b["height"] / 2)
        return None
    raise Exception(f"No viable selector for element {eid}")


def execute_action(page: Page, action: str, args: list[str],
                   elements: list[dict], is_fallback: bool = False) -> str:
    """Execute a parsed action. Returns human-readable result string.

    Errors are returned as 'TIMEOUT:' or 'ERROR:' prefixed strings (fed back to LLM).
    """
    try:
        if action == "click":
            desc = _el_info(elements, args[0])
            _click_element(page, elements, args[0], is_fallback)
            return f"Clicked {desc}"
        if action == "type":
            eid, text = args[0], args[1]
            desc = _el_info(elements, eid)
            loc = _focus_element(page, elements, eid, is_fallback)
            # Clear then type char-by-char (keystroke simulation beats .fill() on React forms)
            page.keyboard.press("Control+a")
            page.keyboard.press("Delete")
            if loc:
                loc.type(text, delay=20)
            else:
                page.keyboard.type(text, delay=20)
            return f"Typed '{text}' into {desc}"
        if action == "select":
            eid, value = args[0], args[1]
            desc = _el_info(elements, eid)
            if not is_fallback:
                page.select_option(f'[data-qa-id="{eid}"]', label=value, timeout=STEP_TIMEOUT)
            else:
                el = _find_element(elements, eid)
                sel = el.get("_sel", "select") if el else "select"
                page.select_option(sel, label=value, timeout=STEP_TIMEOUT)
            return f"Selected '{value}' in {desc}"
        if action == "hover":
            desc = _el_info(elements, args[0])
            if not is_fallback:
                page.hover(f'[data-qa-id="{args[0]}"]', timeout=STEP_TIMEOUT)
            else:
                el = _find_element(elements, args[0])
                if el and el.get("_bbox"):
                    b = el["_bbox"]
                    page.mouse.move(b["x"] + b["width"] / 2, b["y"] + b["height"] / 2)
                elif el and el.get("_sel"):
                    page.hover(el["_sel"], timeout=STEP_TIMEOUT)
            return f"Hovered {desc}"
        if action == "scroll":
            delta = -500 if args[0] == "up" else 500
            page.mouse.wheel(0, delta)
            page.wait_for_timeout(300)
            return f"Scrolled {args[0]}"
        if action == "press":
            key = args[0]
            page.keyboard.press(key)
            page.wait_for_timeout(200)
            return f"Pressed {key}"
        if action == "goto":
            page.goto(args[0], timeout=NAV_TIMEOUT, wait_until="domcontentloaded")
            return f"Navigated to {args[0]}"
        if action == "wait":
            ms = int(args[0])
            page.wait_for_timeout(ms)
            return f"Waited {ms}ms"
        if action == "evaluate":
            return _execute_evaluate(page, args[0])
        if action == "macro":
            return _execute_macro(page, args)
        if action == "screenshot":
            SCREENSHOT_DIR.mkdir(exist_ok=True)
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            path = SCREENSHOT_DIR / f"qa_{ts}.png"
            page.screenshot(path=str(path))
            return f"Screenshot saved: {path}"
        if action == "done":
            return f"DONE: {args[0]} - {args[1]}"
        if action == "error":
            return f"Parse error: {args[0]}"
        return f"Unknown action: {action}"
    except PwTimeout:
        eid = args[0] if args else "?"
        return f"TIMEOUT: Element {eid} not found or not interactable within {STEP_TIMEOUT}ms"
    except Exception as e:
        return f"ERROR: {type(e).__name__}: {str(e)[:200]}"
