"""Android screen capture with bbox overlays from UI hierarchy."""

import re
import base64
import io
from PIL import Image, ImageDraw, ImageFont

# Color palette for bbox overlays (high contrast)
_BBOX_COLORS = [
    "#FF0000", "#00FF00", "#0066FF", "#FF00FF",
    "#FFAA00", "#00FFFF", "#FF6666", "#66FF66",
]

# Elements worth annotating
_CLICKABLE_CLASSES = {
    "android.widget.Button", "android.widget.ImageButton",
    "android.widget.EditText", "android.widget.CheckBox",
    "android.widget.RadioButton", "android.widget.Switch",
    "android.widget.ToggleButton", "android.widget.Spinner",
}


def parse_hierarchy_bboxes(xml: str, screen_w: int = 1080, screen_h: int = 2340):
    """Extract interactive elements with bounding boxes from hierarchy XML.

    Returns list of dicts: {id, x, y, w, h, text, desc, cls, clickable}
    """
    bboxes = []
    idx = 0

    def _attr(node_str, name):
        m = re.search(rf'{name}="([^"]*)"', node_str)
        return m.group(1) if m else ""

    for node_match in re.finditer(r'<node [^>]+>', xml):
        node = node_match.group(0)
        cls = _attr(node, "class")
        text = _attr(node, "text")
        desc = _attr(node, "content-desc")
        clickable = _attr(node, "clickable")
        bounds = re.search(r'bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', node)
        if not bounds:
            continue
        x1, y1, x2, y2 = [int(v) for v in bounds.groups()]
        long_clickable = _attr(node, "long-clickable")
        focusable = _attr(node, "focusable")

        is_interactive = (
            clickable == "true"
            or long_clickable == "true"
            or cls in _CLICKABLE_CLASSES
        )
        has_label = bool(text.strip() or desc.strip())

        # Include: interactive with label, OR text views (for data extraction)
        if not has_label:
            continue
        if not is_interactive and cls not in (
            "android.widget.TextView", "android.view.View",
        ):
            continue

        # Skip tiny or full-screen elements
        w, h = x2 - x1, y2 - y1
        if w < 10 or h < 10 or (w >= screen_w and h >= screen_h):
            continue
        # Skip status bar area
        if y2 < 60:
            continue

        bboxes.append({
            "id": idx,
            "x": x1, "y": y1, "w": w, "h": h,
            "text": text.strip(),
            "desc": desc.strip(),
            "cls": cls.split(".")[-1],
            "clickable": clickable == "true",
        })
        idx += 1

    return bboxes


def capture_annotated(d, max_height: int = 480) -> tuple[str, list[dict]]:
    """Take screenshot, resize to max_height, draw bbox overlays.

    Args:
        d: uiautomator2 device
        max_height: resize height in pixels

    Returns:
        (base64_png, bboxes) - b64-encoded annotated image and bbox list
    """
    # Screenshot
    img = d.screenshot()  # returns PIL Image

    # Get hierarchy and parse bboxes
    xml = d.dump_hierarchy()
    orig_w, orig_h = img.size
    bboxes = parse_hierarchy_bboxes(xml, orig_w, orig_h)

    # Resize
    scale = max_height / orig_h
    new_w = int(orig_w * scale)
    img = img.resize((new_w, max_height), Image.LANCZOS)

    # Draw bboxes
    if bboxes:
        draw = ImageDraw.Draw(img)
        try:
            font = ImageFont.truetype("/usr/share/fonts/liberation-mono/LiberationMono-Bold.ttf", 11)
        except (OSError, IOError):
            font = ImageFont.load_default()

        for bbox in bboxes:
            color = _BBOX_COLORS[bbox["id"] % len(_BBOX_COLORS)]
            x = int(bbox["x"] * scale)
            y = int(bbox["y"] * scale)
            w = int(bbox["w"] * scale)
            h = int(bbox["h"] * scale)
            draw.rectangle([x, y, x + w, y + h], outline=color, width=2)
            label = str(bbox["id"])
            draw.rectangle([x, y - 12, x + 8 + len(label) * 7, y], fill=color)
            draw.text((x + 2, y - 12), label, fill="white", font=font)

    # Encode
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    b64 = base64.b64encode(buf.getvalue()).decode()

    return b64, bboxes


def bbox_summary(bboxes: list[dict]) -> str:
    """Compact text summary of bboxes for LLM context."""
    lines = []
    for b in bboxes:
        label = b["text"] or b["desc"]
        lines.append(f"[{b['id']}] {b['cls']}: \"{label}\"")
    return "\n".join(lines)


def save_annotated(d, path: str, max_height: int = 480) -> list[dict]:
    """Capture annotated screenshot and save to file. Returns bboxes."""
    b64, bboxes = capture_annotated(d, max_height)
    img_data = base64.b64decode(b64)
    with open(path, "wb") as f:
        f.write(img_data)
    return bboxes
