"""Annotated screenshot capture: draws bounding boxes + element IDs on page screenshots."""

import base64
from io import BytesIO

from PIL import Image, ImageDraw, ImageFont
from playwright.sync_api import Page

# JS to get bounding boxes for all data-qa-id elements
JS_GET_BBOXES = """() => {
    const bboxes = [];
    for (const el of document.querySelectorAll('[data-qa-id]')) {
        const r = el.getBoundingClientRect();
        bboxes.push({
            id: parseInt(el.getAttribute('data-qa-id')),
            x: Math.round(r.x), y: Math.round(r.y),
            w: Math.round(r.width), h: Math.round(r.height)
        });
    }
    return bboxes;
}"""

# Color palette for bbox overlays (high contrast)
_BBOX_COLORS = [
    (255, 0, 0), (0, 180, 0), (0, 100, 255), (255, 165, 0),
    (180, 0, 255), (0, 200, 200), (255, 0, 150), (100, 200, 0),
]


def capture_annotated_screenshot(page: Page, max_height: int = 480,
                                  skip_bboxes: bool = False) -> str:
    """Take screenshot, resize to 480p, draw bbox overlays with IDs.

    skip_bboxes=True when JS eval is blocked (extension pages) — plain screenshot only.
    Returns base64-encoded JPEG.

    Scrolls to top before capture so fixed-positioned overlays land at
    consistent coordinates run-to-run; viewport-only shots taken at an
    arbitrary scroll position were the root cause of "vision sometimes
    sees the badge, sometimes doesn't" inconsistency.
    """
    try:
        page.evaluate("() => window.scrollTo(0, 0)")
    except Exception:
        pass
    png_bytes = page.screenshot(type="png")
    img = Image.open(BytesIO(png_bytes))

    bboxes = []
    if not skip_bboxes:
        try:
            bboxes = page.evaluate(JS_GET_BBOXES)
        except Exception:
            pass

    if bboxes:
        draw = ImageDraw.Draw(img)
        try:
            for fp in ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
                       "/usr/share/fonts/dejavu-sans-fonts/DejaVuSans-Bold.ttf",
                       "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf"):
                try:
                    font = ImageFont.truetype(fp, 14)
                    break
                except (OSError, IOError):
                    continue
            else:
                raise OSError("no DejaVu font found")
        except (OSError, IOError):
            font = ImageFont.load_default()

        for bbox in bboxes:
            color = _BBOX_COLORS[bbox["id"] % len(_BBOX_COLORS)]
            x, y, w, h = bbox["x"], bbox["y"], bbox["w"], bbox["h"]
            draw.rectangle([x, y, x + w, y + h], outline=color, width=2)
            label = str(bbox["id"])
            lw, lh = draw.textbbox((0, 0), label, font=font)[2:]
            label_x = max(x, 0)
            label_y = max(y - lh - 2, 0)
            draw.rectangle(
                [label_x, label_y, label_x + lw + 4, label_y + lh + 2], fill=color)
            draw.text((label_x + 2, label_y), label, fill=(255, 255, 255), font=font)

    # Resize to 480p maintaining aspect ratio
    orig_w, orig_h = img.size
    scale = max_height / orig_h
    new_w = int(orig_w * scale)
    img = img.resize((new_w, max_height), Image.LANCZOS)

    buf = BytesIO()
    img.save(buf, format="JPEG", quality=50)
    return base64.b64encode(buf.getvalue()).decode("ascii")
