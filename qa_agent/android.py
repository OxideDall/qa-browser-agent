"""Android driver: uiautomator2 analogue of browser.py + extract.py + actions.py.

Wraps a u2.Device so the rest of the agent (FSM, evidence gate, LLM,
loop-detect) can stay identical. The boundary is `snapshot_android(ctx)`
and `execute_action_android(ctx)` — drop-in replacements for
`runtime.actions.snapshot_page` and `qa_agent.actions.execute_action`
when `ctx.driver_kind == "android"`.

DSL mapping — only the subset that makes sense on a phone:
  click <id>       -> d.click(cx, cy)                    (from element bbox)
  type <id> "text" -> focus element, d.send_keys(text, clear=True)
  scroll up|down   -> d.swipe(cx, y1, cx, y2)
  wait <ms>        -> time.sleep
  press <key>      -> d.press(back|home|enter|menu|search|...)
  screenshot       -> d.screenshot(path)
  look             -> same, handled in the FSM layer via vision.py
  done PASS|FAIL   -> handled by the FSM, identical to browser path.
Unsupported on Android: goto (no URL), tab (no tab concept), hover.
"""

from __future__ import annotations

import re
import time
from typing import Any
from xml.etree import ElementTree as ET


import os
DEFAULT_SERIAL = os.environ.get("ANDROID_SERIAL", "localhost:5555")

# Matches "[x1,y1][x2,y2]" bounds strings from UIAutomator hierarchy dumps.
_BOUNDS_RX = re.compile(r"\[(-?\d+),(-?\d+)\]\[(-?\d+),(-?\d+)\]")


def connect_device(serial: str = DEFAULT_SERIAL):
    """Connect to a device. Caller is expected to ensure ADB is already
    connected (e.g. via `adb connect <serial>`)."""
    import uiautomator2 as u2
    return u2.connect(serial)


# ---------------------------------------------------------------------------
# Extraction — hierarchy dump → elements list + DSL text.
# ---------------------------------------------------------------------------

def _parse_bounds(raw: str) -> tuple[int, int, int, int] | None:
    m = _BOUNDS_RX.match(raw or "")
    if not m:
        return None
    return tuple(int(x) for x in m.groups())  # type: ignore[return-value]


def _short_class(cls: str) -> str:
    return cls.rsplit(".", 1)[-1] if cls else ""


def _resource_tail(rid: str) -> str:
    return rid.split("/", 1)[-1] if rid else ""


def _node_tag(cls: str, editable: bool) -> str:
    if editable:
        return "in"
    name = _short_class(cls).lower()
    if "button" in name:
        return "btn"
    if "image" in name:
        return "img"
    if "checkbox" in name:
        return "chk"
    if "switch" in name:
        return "sw"
    if "radio" in name:
        return "rad"
    if "recyclerview" in name or "viewpager" in name or "listview" in name:
        return "list"
    if "textview" in name or "text" in name:
        return "txt"
    return "view"


def _element_text(node_attrs: dict) -> tuple[str, str]:
    """Returns (primary_text, placeholder). primary_text is what's shown to
    the agent as the identifying label; placeholder is a secondary
    content-desc shown in parentheses if text is empty."""
    txt = (node_attrs.get("text") or "").strip()
    desc = (node_attrs.get("content-desc") or "").strip()
    if txt:
        return txt, desc
    return "", desc


def extract_elements(device) -> tuple[list[dict], str, bool]:
    """Parse the current UI hierarchy. Returns (elements, dsl_text, is_fallback).

    Elements shape matches qa_agent.extract.extract_elements output closely
    enough that runtime/fsm_actions._el_info + loop_detect + recorder all
    work unchanged:
      {"id": int, "tag": str, "text": str, "ph": str,
       "_sel": str (resource-id tail), "_bbox": {x,y,width,height},
       "_cx": int, "_cy": int, "_editable": bool}

    is_fallback is always False for Android: the hierarchy dump is the
    primary (and only) source; there's no LavaMoat-style fallback to flag.
    """
    xml = device.dump_hierarchy(compressed=True, pretty=False)
    try:
        root = ET.fromstring(xml)
    except ET.ParseError:
        return [], "(hierarchy parse error)", False

    sw, sh = device.window_size()
    elements: list[dict] = []
    next_id = 1

    for node in root.iter("node"):
        a = node.attrib
        cls = a.get("class", "") or ""
        enabled = a.get("enabled", "false") == "true"
        if not enabled:
            continue

        clickable = a.get("clickable", "false") == "true"
        long_clickable = a.get("long-clickable", "false") == "true"
        focusable = a.get("focusable", "false") == "true"
        scrollable = a.get("scrollable", "false") == "true"
        editable = "EditText" in cls

        is_interactive = clickable or long_clickable or editable or (
            focusable and not scrollable  # raw ScrollView nodes are spammy
        )
        if not is_interactive:
            continue

        bounds = _parse_bounds(a.get("bounds", ""))
        if not bounds:
            continue
        x1, y1, x2, y2 = bounds
        if x2 <= x1 or y2 <= y1:
            continue
        # Skip nodes fully off-screen.
        if x2 <= 0 or y2 <= 0 or x1 >= sw or y1 >= sh:
            continue
        # Skip huge full-screen containers (usually layout roots, not tap targets).
        if (x2 - x1) >= sw and (y2 - y1) >= sh * 0.8:
            continue

        text, desc = _element_text(a)
        if not (text or desc or editable or _resource_tail(a.get("resource-id", ""))):
            # Node has no identifier the LLM can use — skip.
            continue

        cx = (x1 + x2) // 2
        cy = (y1 + y2) // 2
        elements.append({
            "id": next_id,
            "tag": _node_tag(cls, editable),
            "text": text[:160],
            "ph": desc[:120],
            "_sel": _resource_tail(a.get("resource-id", "")),
            "_bbox": {"x": x1, "y": y1, "width": x2 - x1, "height": y2 - y1},
            "_cx": cx,
            "_cy": cy,
            "_editable": editable,
            "_cls": _short_class(cls),
            "_clickable": clickable,
            "_long": long_clickable,
        })
        next_id += 1

    # Build the DSL text the LLM sees. Keep close to the browser format:
    #   [N] tag "text" (placeholder) #resource-id
    lines: list[str] = []
    for el in elements:
        parts = [f"[{el['id']}]", el["tag"]]
        if el["text"]:
            parts.append(f'"{el["text"][:40]}"')
        elif el["ph"]:
            parts.append(f'({el["ph"][:40]})')
        if el["_sel"]:
            parts.append(f"#{el['_sel'][:25]}")
        if el["_editable"]:
            parts.append("in:text")
        lines.append(" ".join(parts))

    # Top of the DSL: include current app + activity so the LLM can orient.
    current = device.app_current() or {}
    header = f"@ {current.get('package', '?')} / {current.get('activity', '?')}"
    body = "\n".join(lines) if lines else "(no interactive elements found)"
    dsl_text = header + "\n" + body

    return elements, dsl_text, False


# ---------------------------------------------------------------------------
# Execution — DSL actions → u2 ops.
# ---------------------------------------------------------------------------

_KEY_MAP = {
    "back": "back", "home": "home", "menu": "menu",
    "enter": "enter", "search": "search", "delete": "del",
    "power": "power", "recent": "recent",
    # Aliases common from the browser DSL:
    "return": "enter", "escape": "back", "esc": "back",
}


def _find_el(elements: list[dict], eid_str: str) -> dict | None:
    """Resolve a DSL element id. Tolerates both `5` and `[5]` forms
    (the LLM sometimes echoes the bracketed header format back)."""
    if eid_str is None:
        return None
    cleaned = eid_str.strip().strip("[]<>()")
    try:
        eid = int(cleaned)
    except (ValueError, TypeError):
        return None
    for el in elements:
        if el["id"] == eid:
            return el
    return None


def execute_action(device, action: str, args: list[str],
                   elements: list[dict]) -> str:
    """Dispatch a DSL action on the phone. Returns a short human-readable
    result line (mirroring qa_agent.actions.execute_action semantics:
    "clicked #ok" on success, "TIMEOUT: ..." / "ERROR: ..." on failure)."""
    try:
        if action == "click":
            el = _find_el(elements, args[0] if args else "")
            if not el:
                return f"ERROR: element {args[0]!r} not in snapshot"
            device.click(el["_cx"], el["_cy"])
            label = (el["text"] or el["ph"] or el["_sel"] or el["tag"])[:40]
            return f"clicked [{el['id']}] {el['tag']} {label!r}"

        if action == "type":
            if len(args) < 2:
                return "ERROR: type needs <id> \"text\""
            el = _find_el(elements, args[0])
            if not el:
                return f"ERROR: element {args[0]!r} not in snapshot"
            text = args[1]
            # Focus by tapping, then send keys via IME with clear-first.
            device.click(el["_cx"], el["_cy"])
            time.sleep(0.3)
            device.send_keys(text, clear=True)
            return f"typed {text[:30]!r} into [{el['id']}]"

        if action == "scroll":
            direction = (args[0] if args else "down").lower()
            sw, sh = device.window_size()
            cx = sw // 2
            if direction == "up":
                y1, y2 = int(sh * 0.3), int(sh * 0.75)
            else:
                y1, y2 = int(sh * 0.75), int(sh * 0.3)
            device.swipe(cx, y1, cx, y2, duration=0.2)
            return f"scrolled {direction}"

        if action == "wait":
            ms = 500
            if args:
                try:
                    ms = max(50, min(5000, int(args[0])))
                except ValueError:
                    pass
            time.sleep(ms / 1000.0)
            return f"waited {ms}ms"

        if action == "press":
            raw = (args[0] if args else "back").lower().strip()
            key = _KEY_MAP.get(raw, raw)
            device.press(key)
            return f"pressed {key!r}"

        if action == "screenshot":
            from .config import SCREENSHOT_DIR
            SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
            path = SCREENSHOT_DIR / f"android_{int(time.time())}.png"
            device.screenshot(str(path))
            return f"screenshot saved to {path}"

        if action in ("hover", "select", "goto", "tab"):
            return f"ERROR: '{action}' not supported on Android driver"

        return f"ERROR: unknown action '{action}'"

    except Exception as e:
        return f"ERROR: {type(e).__name__}: {e}"


# ---------------------------------------------------------------------------
# Thin ctx-level adapters used by runtime.actions.snapshot_page and
# runtime.fsm_actions.act_exec when ctx.driver_kind == "android".
# Keep these small: they just bridge ctx → driver calls and back.
# ---------------------------------------------------------------------------

def snapshot_android(ctx: Any) -> dict:
    """Runtime snapshot callback for Android. Returns the same shape that
    the browser's `snapshot_page` produces so downstream FSM code can stay
    uniform.

    Note: `step_image` is None on the happy path; `look` action captures
    a fresh screenshot separately via vision.py when the LLM asks for it.
    """
    device = ctx.android_device
    elements, elements_text, is_fallback = extract_elements(device)
    if not elements:
        elements_text = elements_text + "\n(tip: try `scroll down` or `wait 500`)"
    return {
        "elements": elements,
        "elements_text": elements_text,
        "is_fallback": is_fallback,
        "step_image": None,
    }


def execute_android(ctx: Any) -> str:
    """Runtime exec callback for Android. Thin wrapper used by act_exec."""
    device = ctx.android_device
    elements = ctx.snapshot["elements"]
    return execute_action(device, ctx.action, ctx.args, elements)


def capture_annotated_screenshot_android(
    device, elements: list[dict], max_height: int = 900,
) -> str:
    """Annotate the current screen with element IDs and return the result
    as a base64-encoded JPEG string, matching the shape of
    `vision.capture_annotated_screenshot` so `ask_llm(image_b64=...)` works
    uniformly across drivers (llm.ask_llm hard-codes image/jpeg).

    Downscales to `max_height` to keep vision token cost in check (Android
    screens are tall — 1080x2340 would otherwise burn ~2.5 MPix through
    the vision channel)."""
    import base64
    from io import BytesIO
    from PIL import Image, ImageDraw, ImageFont

    raw = device.screenshot(format="pillow")  # PIL.Image.Image
    img = raw.convert("RGB")
    draw = ImageDraw.Draw(img, "RGBA")
    try:
        # Try common DejaVu locations (Debian, Fedora, macOS brew, etc.).
        for fp in ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
                    "/usr/share/fonts/dejavu-sans-fonts/DejaVuSans-Bold.ttf",
                    "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf"):
            try:
                font = ImageFont.truetype(fp, 26)
                break
            except Exception:
                continue
        else:
            font = ImageFont.load_default()
            font  # noqa: pointless but silences the linter about unused
    except Exception:
        font = ImageFont.load_default()

    for el in elements:
        b = el.get("_bbox")
        if not b:
            continue
        x1, y1 = b["x"], b["y"]
        x2, y2 = x1 + b["width"], y1 + b["height"]
        draw.rectangle([x1, y1, x2, y2], outline=(255, 40, 40, 220), width=3)
        label = f"[{el['id']}]"
        lx, ly = x1 + 4, max(0, y1 - 30)
        try:
            lw, lh = draw.textbbox((lx, ly), label, font=font)[2:]
        except Exception:
            lw, lh = lx + 40, ly + 26
        draw.rectangle([lx - 2, ly - 2, lw + 4, lh + 2], fill=(255, 220, 0, 230))
        draw.text((lx, ly), label, fill=(0, 0, 0), font=font)

    # Downscale so vision tokens stay reasonable.
    if img.height > max_height:
        ratio = max_height / img.height
        img = img.resize((int(img.width * ratio), max_height))

    buf = BytesIO()
    img.save(buf, format="JPEG", quality=82)
    return base64.b64encode(buf.getvalue()).decode("ascii")
