"""Action DSL: parse + execute. DSL is what the LLM emits (click/type/goto/...)."""

import re
from datetime import datetime

from playwright.sync_api import Page, TimeoutError as PwTimeout

from .config import MAX_WAIT_MS, SCREENSHOT_DIR, STEP_TIMEOUT, NAV_TIMEOUT


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
