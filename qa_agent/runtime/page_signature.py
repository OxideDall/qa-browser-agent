"""Page signature: structural + content fingerprints + URL template.

Used by the macro pipeline (Phase 0 of the macro design doc) to
classify a page state with three orthogonal fingerprints:

  struct_hash    — invariant under content changes. Same shape +
                   roles + tags → same hash. Two runs of the same
                   marketplace category page hash equal even if the
                   product list rotated.
  content_hash   — invariant under structural changes. Same visible
                   text → same hash. Catches "same data rendered
                   slightly differently".
  url_template   — URL with numeric / UUID / slug-like / long-hex
                   path segments normalised; query params: keys
                   kept (sorted), values dropped.

Two pages are *same template* if (url_template, struct_hash) match —
the macro pipeline uses this as the precondition signature.
*Same instance* if all three match. Edit-distance comparison between
struct_hashes (Phase 4 — APTED) is a TODO; the current scheme is
"identical or different", no fuzzy matching.

Hashes are SHA-1 truncated to 16 hex chars: enough collision resistance
for bench-scale dedup, cheap to compare in Python sets / dict keys.
"""

from __future__ import annotations

import hashlib
import re
from urllib.parse import parse_qsl, urlsplit, urlunsplit


# ---------------------------------------------------------------------------
# URL templating
# ---------------------------------------------------------------------------

_SEG_NUMERIC = re.compile(r"^\d+$")
_SEG_UUID = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)
_SEG_HEX_LONG = re.compile(r"^[0-9a-f]{16,}$", re.IGNORECASE)
# Slug-ish: lowercase / digits / dashes, ≥10 chars. Avoids collapsing
# short, semantically-meaningful segments like /api or /docs.
_SEG_SLUG = re.compile(r"^[a-z0-9][a-z0-9\-]{9,}$", re.IGNORECASE)


def url_template(url: str) -> str:
    """Normalise a URL to its template form.

    /catalog/12345/widget-foo-bar  →  /catalog/<num>/<slug>
    /api/users/abc-…-uuid          →  /api/users/<uuid>
    ?q=hello&page=2                →  ?page=<v>&q=<v>     (keys sorted)
    """
    try:
        sp = urlsplit(url)
    except Exception:
        return url

    parts: list[str] = []
    for seg in sp.path.split("/"):
        if not seg:
            parts.append(seg)
            continue
        if _SEG_NUMERIC.match(seg):
            parts.append("<num>")
        elif _SEG_UUID.match(seg):
            parts.append("<uuid>")
        elif _SEG_HEX_LONG.match(seg):
            parts.append("<hex>")
        elif _SEG_SLUG.match(seg):
            parts.append("<slug>")
        else:
            parts.append(seg)
    new_path = "/".join(parts)

    qs = sorted(k for k, _ in parse_qsl(sp.query, keep_blank_values=True))
    new_query = "&".join(f"{k}=<v>" for k in qs)

    # Drop fragment — almost always client-side state, not template.
    return urlunsplit((sp.scheme, sp.netloc, new_path, new_query, ""))


# ---------------------------------------------------------------------------
# Hashes
# ---------------------------------------------------------------------------

def _short_hash(s: str) -> str:
    return hashlib.sha1(s.encode("utf-8", errors="replace")).hexdigest()[:16]


def struct_hash(elements: list[dict]) -> str:
    """Hash the structural shape of the interactive-element list.

    Same template + different data → same hash. Per-element features
    chosen to be content-invariant: tag, role, presence (not value)
    of href, disabled / checked state. Element ORDER matters — the
    extractor walks DOM order; same template renders the same order.
    """
    if not elements:
        return _short_hash("__empty__")
    rows: list[str] = []
    for el in elements:
        feat = (
            str(el.get("tag", "")),
            str(el.get("role", "")),
            str(el.get("type", "")),       # for input[type=email] vs [type=text]
            "1" if el.get("disabled") else "0",
            "1" if el.get("checked") else "0",
            "1" if el.get("href") else "0",
            "1" if el.get("ph") else "0",   # has placeholder?
        )
        rows.append("|".join(feat))
    return _short_hash("\n".join(rows))


def content_hash(
    elements: list[dict],
    text_snippets: list[dict] | list[str] | None = None,
) -> str:
    """Hash the bag of visible text on the page.

    Bag-of-strings, not order-sensitive — `[text="A","B"]` hashes the
    same as `["B","A"]`. Differentiates "same template, different
    actual data on screen" from "same instance".

    `text_snippets` may be either:
      - `[{"tag": "...", "text": "..."}, ...]` — raw extractor output
      - `["text1", "text2", ...]`              — pre-extracted strings
    """
    bag: set[str] = set()
    for el in elements:
        for k in ("text", "ph", "selected"):
            v = el.get(k)
            if v:
                bag.add(str(v).strip().lower()[:80])
    if text_snippets:
        for t in text_snippets:
            if isinstance(t, dict):
                v = t.get("text", "")
            else:
                v = str(t)
            v = v.strip().lower()
            if v:
                bag.add(v[:80])
    if not bag:
        return _short_hash("__empty__")
    return _short_hash("\n".join(sorted(bag)))


# ---------------------------------------------------------------------------
# Composite signature
# ---------------------------------------------------------------------------

def compute_signature(
    url: str,
    elements: list[dict],
    text_snippets: list[dict] | list[str] | None = None,
) -> dict:
    """Build the full signature dict for a page state.

    Returns a flat dict — convenient to embed in step records and
    JSONL captures without nested-key collisions:

        {
          "url_template": "https://example.com/catalog/<num>",
          "raw_url":      "https://example.com/catalog/12345",
          "struct_hash":  "abc123...",
          "content_hash": "def456...",
          "n_elements":   42,
        }
    """
    return {
        "url_template": url_template(url or ""),
        "raw_url": url or "",
        "struct_hash": struct_hash(elements or []),
        "content_hash": content_hash(elements or [], text_snippets),
        "n_elements": len(elements or []),
    }


def template_key(sig: dict) -> tuple[str, str]:
    """Tuple key for "same template" dedup. Used by the miner to
    bucket steps by which template they ran on."""
    return (sig.get("url_template", ""), sig.get("struct_hash", ""))


def instance_key(sig: dict) -> tuple[str, str, str]:
    """Tuple key for "same exact page instance" dedup."""
    return (
        sig.get("url_template", ""),
        sig.get("struct_hash", ""),
        sig.get("content_hash", ""),
    )
