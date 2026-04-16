"""Page snapshot extraction: JS extractor (main) + HTML-parser fallback for LavaMoat pages."""

from html.parser import HTMLParser

from playwright.sync_api import Page, TimeoutError as PwTimeout

# Main extractor — injected via page.evaluate(). Collects interactive elements
# + Shadow DOM recursion + cursor:pointer second pass + text content. ~300 tokens output.
JS_EXTRACTOR = """() => {
    document.querySelectorAll('[data-qa-id]').forEach(el => el.removeAttribute('data-qa-id'));

    const INTERACTIVE = 'a, button, input, select, textarea, [role="button"], [role="link"], [role="tab"], [role="menuitem"], [role="checkbox"], [role="radio"], [role="switch"], [tabindex]:not([tabindex="-1"])';
    const vw = window.innerWidth;
    const vh = window.innerHeight;
    const results = [];
    let id = 1;

    // Collect elements from main DOM + Shadow DOMs (2 levels deep)
    function collectAll(root) {
        const els = [];
        for (const el of root.querySelectorAll(INTERACTIVE)) els.push(el);
        for (const el of root.querySelectorAll('*')) {
            if (el.shadowRoot) {
                for (const sel of el.shadowRoot.querySelectorAll(INTERACTIVE)) els.push(sel);
                for (const el2 of el.shadowRoot.querySelectorAll('*')) {
                    if (el2.shadowRoot) {
                        for (const sel2 of el2.shadowRoot.querySelectorAll(INTERACTIVE)) els.push(sel2);
                    }
                }
            }
        }
        return els;
    }

    for (const el of collectAll(document)) {
        const style = window.getComputedStyle(el);
        if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') continue;

        const rect = el.getBoundingClientRect();
        if (rect.width < 2 || rect.height < 2) continue;
        if (rect.bottom < 0 || rect.top > vh || rect.right < 0 || rect.left > vw) continue;

        // Occlusion check — but allow Web Component (rabby-kit style) overlays
        const cx = rect.left + rect.width / 2;
        const cy = rect.top + rect.height / 2;
        let visible = false;
        for (const [px, py] of [[cx,cy],[rect.left+3,rect.top+3],[rect.right-3,rect.bottom-3]]) {
            if (px < 0 || py < 0 || px >= vw || py >= vh) continue;
            const topEl = document.elementFromPoint(px, py);
            if (!topEl || el.contains(topEl) || topEl === el || topEl.contains(el)) {
                visible = true; break;
            }
            if (topEl.tagName.includes('-')) { visible = true; break; }
        }
        if (!visible) continue;

        el.setAttribute('data-qa-id', String(id));

        const tag = el.tagName.toLowerCase();
        let text = (el.textContent || '').trim().substring(0, 120);
        if (tag === 'input' || tag === 'textarea') {
            text = el.value ? el.value.substring(0, 120) : '';
        }

        const info = { id, tag };
        if (el.type && tag === 'input') info.type = el.type;
        if (text) info.text = text;
        if (el.placeholder) info.ph = el.placeholder.substring(0, 80);

        const role = el.getAttribute('role');
        if (role) info.role = role;

        if (tag === 'a' && el.href) {
            try {
                const u = new URL(el.href);
                info.href = u.pathname + u.search;
            } catch(e) {
                info.href = el.getAttribute('href');
            }
        }

        if (el.disabled) info.disabled = true;
        if (el.checked) info.checked = true;
        if (tag === 'select') {
            const opt = el.options[el.selectedIndex];
            if (opt) info.selected = opt.text.substring(0, 60);
        }

        let section = '';
        let parent = el.parentElement;
        for (let i = 0; i < 5 && parent; i++) {
            const lbl = parent.getAttribute('aria-label');
            if (lbl) { section = lbl.substring(0, 60); break; }
            const h = parent.querySelector('h1,h2,h3,h4');
            if (h && h.compareDocumentPosition(el) & Node.DOCUMENT_POSITION_FOLLOWING) {
                section = h.textContent.trim().substring(0, 60);
                break;
            }
            parent = parent.parentElement;
        }
        if (section) info.section = section;

        results.push(info);
        id++;
    }

    // Second pass: cursor:pointer div/span/li (catches React SPAs with unsemantic buttons)
    const cursorSeen = new Set(results.map(r => r.text || ''));
    for (const el of document.querySelectorAll('div, span, li')) {
        if (el.hasAttribute('data-qa-id')) continue;
        const s = window.getComputedStyle(el);
        if (s.cursor !== 'pointer') continue;
        if (s.display === 'none' || s.visibility === 'hidden' || s.opacity === '0') continue;
        const rect = el.getBoundingClientRect();
        if (rect.width < 10 || rect.height < 10) continue;
        if (rect.bottom < 0 || rect.top > vh || rect.right < 0 || rect.left > vw) continue;
        const text = (el.textContent || '').trim().substring(0, 120);
        if (!text || text.length < 2 || text.length > 100) continue;
        if (cursorSeen.has(text)) continue;
        if (el.querySelector('[data-qa-id]')) continue;
        if (el.closest('[data-qa-id]')) continue;

        cursorSeen.add(text);
        el.setAttribute('data-qa-id', String(id));
        const tag = el.tagName.toLowerCase();
        const info = { id, tag, text };
        info._cx = Math.round(rect.left + rect.width / 2);
        info._cy = Math.round(rect.top + rect.height / 2);
        const role = el.getAttribute('role');
        if (role) info.role = role;
        results.push(info);
        id++;
        if (results.length >= 60) break;
    }

    // Visible text content — headings, prices, descriptions, key text in viewport
    const textSnippets = [];
    const TEXT_NODES = 'h1, h2, h3, h4, p, span.a-price, [data-a-color="price"] span, .a-price .a-offscreen, .product-title, .price, .rating, [class*="price"], [class*="rating"], [class*="stars"], [class*="review"], td, th, dt, dd, li, figcaption, label, legend, .a-size-large, .a-size-medium, .a-size-base';
    const seen = new Set();
    for (const el of document.querySelectorAll(TEXT_NODES)) {
        const style = window.getComputedStyle(el);
        if (style.display === 'none' || style.visibility === 'hidden') continue;
        const rect = el.getBoundingClientRect();
        if (rect.bottom < 0 || rect.top > vh) continue;
        if (rect.width < 2) continue;
        let t = (el.textContent || '').trim().replace(/\\s+/g, ' ').substring(0, 240);
        if (!t || t.length < 2 || seen.has(t)) continue;
        if (seen.has(t.substring(0, 120))) continue;
        seen.add(t);
        seen.add(t.substring(0, 120));
        const tag = el.tagName.toLowerCase();
        textSnippets.push({ tag, text: t });
        if (textSnippets.length >= 40) break;
    }

    return {
        url: location.href,
        title: document.title.substring(0, 80),
        count: results.length,
        elements: results,
        text: textSnippets
    };
}"""


class _InteractiveHTMLParser(HTMLParser):
    """Legacy HTML parser — kept for reference but not used; _extract_from_html uses Playwright APIs."""

    INTERACTIVE_TAGS = {"a", "button", "input", "select", "textarea"}
    INTERACTIVE_ROLES = {"button", "link", "tab", "menuitem", "checkbox", "radio", "switch"}

    def __init__(self):
        super().__init__()
        self.elements: list[dict] = []
        self.text_nodes: list[dict] = []
        self._id = 1
        self._tag_stack: list[str] = []
        self._current_text: list[str] = []
        self._current_tag: str | None = None
        self._skip_tags = {"script", "style", "noscript", "svg", "path"}
        self._skipping = 0
        self._heading_context = ""

    def handle_starttag(self, tag, attrs):
        attrs_d = dict(attrs)
        if tag in self._skip_tags:
            self._skipping += 1
            return
        if tag in ("h1", "h2", "h3", "h4"):
            self._current_tag = tag
            self._current_text = []
        role = attrs_d.get("role", "")
        is_interactive = (
            tag in self.INTERACTIVE_TAGS
            or role in self.INTERACTIVE_ROLES
            or (attrs_d.get("tabindex", "-1") not in ("-1", ""))
        )
        style = attrs_d.get("style", "")
        if "display:none" in style.replace(" ", "") or "display: none" in style:
            return
        if attrs_d.get("hidden") is not None or attrs_d.get("aria-hidden") == "true":
            return
        if is_interactive:
            el = {"id": self._id, "tag": tag}
            self._id += 1
            if tag == "input":
                el["type"] = attrs_d.get("type", "text")
                if attrs_d.get("value"):
                    el["text"] = attrs_d["value"][:60]
            if attrs_d.get("placeholder"):
                el["ph"] = attrs_d["placeholder"][:40]
            if role:
                el["role"] = role
            if tag == "a" and attrs_d.get("href"):
                el["href"] = attrs_d["href"][:80]
            if attrs_d.get("disabled") is not None:
                el["disabled"] = True
            if attrs_d.get("checked") is not None:
                el["checked"] = True
            if attrs_d.get("aria-label"):
                el["text"] = attrs_d["aria-label"][:60]
            if self._heading_context:
                el["section"] = self._heading_context
            if attrs_d.get("data-testid"):
                el["_sel"] = f'[data-testid="{attrs_d["data-testid"]}"]'
            elif attrs_d.get("id"):
                el["_sel"] = f'#{attrs_d["id"]}'
            elif attrs_d.get("name"):
                el["_sel"] = f'{tag}[name="{attrs_d["name"]}"]'
            elif attrs_d.get("class"):
                cls = attrs_d["class"].split()[0] if attrs_d["class"].strip() else ""
                if cls and len(cls) > 2:
                    el["_sel"] = f'{tag}.{cls}'
            self.elements.append(el)
            self._tag_stack.append(f"_el_{el['id']}")
            return
        if tag in ("h1", "h2", "h3", "h4", "p", "label", "legend", "li", "span", "div"):
            self._current_tag = tag
            self._current_text = []
        self._tag_stack.append(tag)

    def handle_endtag(self, tag):
        if tag in self._skip_tags and self._skipping > 0:
            self._skipping -= 1
            return
        if self._tag_stack:
            self._tag_stack.pop()
        if self._current_text:
            text = " ".join(self._current_text).strip()[:120]
            if text:
                if self.elements and not self.elements[-1].get("text"):
                    last = self.elements[-1]
                    if last["tag"] == tag or (tag in ("span", "div") and not last.get("text")):
                        last["text"] = text
                if tag in ("h1", "h2", "h3", "h4"):
                    self._heading_context = text[:30]
                    self.text_nodes.append({"tag": tag, "text": text})
                elif tag in ("p", "label", "legend", "li") and len(text) > 3:
                    self.text_nodes.append({"tag": tag, "text": text})
        self._current_tag = None
        self._current_text = []

    def handle_data(self, data):
        if self._skipping:
            return
        text = data.strip()
        if text:
            self._current_text.append(text)
            if self.elements:
                last = self.elements[-1]
                if not last.get("text") and last["tag"] in ("button", "a"):
                    last["text"] = text[:60]


def _extract_from_html(page: Page) -> dict:
    """Fallback extraction using ONLY LavaMoat-safe Playwright APIs.

    Avoids page.evaluate() and locator.evaluate() entirely. Uses: locator.all(),
    .is_visible(), .bounding_box(), .get_attribute(), .inner_text(), .input_value()
    — all of which go through CDP protocol.
    """
    elements = []
    text_nodes = []
    eid = 1
    seen_bboxes: set[tuple[int, int, int, int]] = set()

    TAG_QUERIES = [
        ("a", "a"),
        ("button", "button"),
        ("input", "input"),
        ("select", "select"),
        ("textarea", "textarea"),
        ("div", "[role='button']"),
        ("div", "[role='link']"),
        ("div", "[role='tab']"),
        ("div", "[role='checkbox']"),
        ("div", "[role='radio']"),
        ("div", "[role='switch']"),
    ]

    for tag_name, selector in TAG_QUERIES:
        try:
            for loc in page.locator(selector).all():
                try:
                    if not loc.is_visible(timeout=300):
                        continue
                    bbox = loc.bounding_box()
                    if not bbox or bbox["width"] < 2 or bbox["height"] < 2:
                        continue
                    bkey = (round(bbox["x"]), round(bbox["y"]),
                            round(bbox["width"]), round(bbox["height"]))
                    if bkey in seen_bboxes:
                        continue
                    seen_bboxes.add(bkey)
                except Exception:
                    continue

                el = {"id": eid, "tag": tag_name, "_bbox": bbox}

                try:
                    role = loc.get_attribute("role") or ""
                    if role:
                        el["role"] = role
                        if tag_name == "div":
                            el["tag"] = role
                except Exception:
                    pass

                try:
                    testid = loc.get_attribute("data-testid") or ""
                    el_id = loc.get_attribute("id") or ""
                    name = loc.get_attribute("name") or ""
                    placeholder = loc.get_attribute("placeholder") or ""
                    href = loc.get_attribute("href") or "" if tag_name == "a" else ""
                    aria_label = loc.get_attribute("aria-label") or ""
                    disabled = loc.get_attribute("disabled")
                    checked = loc.get_attribute("checked")
                    inp_type = loc.get_attribute("type") or ""
                except Exception:
                    testid = el_id = name = placeholder = href = aria_label = ""
                    disabled = checked = None
                    inp_type = ""

                if tag_name == "input" and inp_type:
                    el["type"] = inp_type
                if placeholder:
                    el["ph"] = placeholder[:80]
                if href:
                    el["href"] = href[:80]
                if disabled is not None:
                    el["disabled"] = True
                if checked is not None:
                    el["checked"] = True

                text = ""
                if tag_name in ("input", "textarea"):
                    try:
                        text = loc.input_value(timeout=300)
                    except Exception:
                        pass
                if not text:
                    try:
                        text = loc.inner_text(timeout=300)
                    except Exception:
                        pass
                if not text and aria_label:
                    text = aria_label
                if text:
                    el["text"] = text.strip()[:120]

                if testid:
                    el["_sel"] = f'[data-testid="{testid}"]'
                elif el_id:
                    el["_sel"] = f'#{el_id}'
                elif name:
                    el["_sel"] = f'{tag_name}[name="{name}"]'
                elif placeholder:
                    el["_sel"] = f'{tag_name}[placeholder="{placeholder[:80]}"]'

                elements.append(el)
                eid += 1

                if eid > 60:
                    break
        except Exception:
            continue

    # Sort by reading order, reassign IDs
    elements.sort(key=lambda e: (e.get("_bbox", {}).get("y", 0),
                                  e.get("_bbox", {}).get("x", 0)))
    for i, el in enumerate(elements, 1):
        el["id"] = i

    try:
        for h_tag in ("h1", "h2", "h3", "h4"):
            for loc in page.locator(h_tag).all():
                try:
                    if loc.is_visible(timeout=200):
                        t = loc.inner_text(timeout=200).strip()[:240]
                        if t:
                            text_nodes.append({"tag": h_tag, "text": t})
                except Exception:
                    continue
        for p_tag in ("p", "label", "legend"):
            for loc in page.locator(p_tag).all():
                try:
                    if loc.is_visible(timeout=200):
                        t = loc.inner_text(timeout=200).strip()[:240]
                        if t and len(t) > 3:
                            text_nodes.append({"tag": p_tag, "text": t})
                except Exception:
                    continue
                if len(text_nodes) >= 30:
                    break
    except Exception:
        pass

    return {
        "url": page.url,
        "title": page.title()[:80] if page.title() else "",
        "count": len(elements),
        "elements": elements,
        "text": text_nodes[:30],
    }


def _is_extension_page(page: Page) -> bool:
    url = page.url
    return url.startswith("chrome-extension://") or url.startswith("moz-extension://")


def extract_elements(page: Page) -> tuple[list[dict], str, bool]:
    """Extract interactive elements. Returns (elements, dsl_text, is_fallback).

    is_fallback=True means JS eval was blocked (LavaMoat etc.) and we're using CDP-safe path.
    """
    try:
        page.wait_for_load_state("domcontentloaded", timeout=5000)
    except PwTimeout:
        pass
    try:
        page.wait_for_load_state("networkidle", timeout=3000)
    except PwTimeout:
        pass

    page.wait_for_timeout(500)

    is_fallback = False
    try:
        result = page.evaluate(JS_EXTRACTOR)
    except Exception:
        result = _extract_from_html(page)
        is_fallback = True

    elements = result["elements"]

    TAG_SHORT = {"button": "btn", "input": "in", "select": "sel", "textarea": "txt"}
    lines = [f"@ {result['title']} | {result['url']}"]
    for el in elements:
        tag = TAG_SHORT.get(el["tag"], el["tag"])
        if tag == "in" and el.get("type"):
            tag += f".{el['type']}"

        parts = [str(el["id"]), tag]

        if el.get("text"):
            parts.append(f'"{el["text"]}"')
        if el.get("ph"):
            parts.append(f'[{el["ph"]}]')
        if el.get("href"):
            parts.append(f'->{el["href"]}')
        if tag == "sel" and el.get("selected"):
            parts.append(f'="{el["selected"]}"')
        if el.get("checked"):
            parts.append("+")
        if el.get("disabled"):
            parts.append("!disabled")
        if el.get("role"):
            parts.append(f'r:{el["role"]}')
        if el.get("section"):
            parts.append(f'@{el["section"]}')

        lines.append(" ".join(parts))

    for t in result.get("text", []):
        tag = t["tag"]
        txt = t["text"]
        if tag == "h1":
            lines.append(f"# {txt}")
        elif tag == "h2":
            lines.append(f"## {txt}")
        elif tag in ("h3", "h4"):
            lines.append(f"### {txt}")
        else:
            lines.append(f"| {txt}")

    return elements, "\n".join(lines), is_fallback
