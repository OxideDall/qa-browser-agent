"""Declarative assert evaluator. Runs against a live Playwright page.

Schema (inside fixture's assert.json):

    {
      "checks": [
        {"type": "url_contains", "value": "/success"},
        {"type": "url_equals", "value": "http://..."},
        {"type": "dom_text",   "selector": "#toast", "expected": "Confirmed!"},
        {"type": "dom_text_contains", "selector": "h1", "value": "Welcome"},
        {"type": "dom_count",  "selector": ".item", "min": 3},
        {"type": "dom_attr",   "selector": "input#email", "attr": "value", "expected": "..."},
        {"type": "localstorage_key", "key": "todos", "regex": ".*completed.*"},
        {"type": "localstorage_key", "key": "todos", "json_match": [{"completed": true}]},
        {"type": "tab_count",  "min": 2},
        {"type": "agent_status", "expected": "PASS"}
      ]
    }

Each check returns (ok: bool, msg: str). The overall assert is OK iff every
check is OK. Failures preserve the first error message.
"""

from __future__ import annotations

import json
import re
from typing import Any

from playwright.sync_api import Page


def _localstorage(page: Page, key: str) -> str | None:
    try:
        return page.evaluate(f"localStorage.getItem({json.dumps(key)})")
    except Exception:
        return None


def _eval_check(check: dict, page: Page, context: object,
                agent_status: str) -> tuple[bool, str]:
    t = check.get("type")
    try:
        if t == "url_contains":
            v = check["value"]
            ok = v in page.url
            return ok, f"url_contains '{v}' (got {page.url!r})"
        if t == "url_equals":
            v = check["value"]
            ok = page.url == v
            return ok, f"url_equals '{v}' (got {page.url!r})"
        if t == "dom_text":
            sel = check["selector"]
            expected = check["expected"]
            loc = page.locator(sel).first
            if loc.count() == 0:
                return False, f"dom_text '{sel}' not found"
            got = (loc.inner_text(timeout=2000) or "").strip()
            return (got == expected, f"dom_text '{sel}' got={got!r} expected={expected!r}")
        if t == "dom_text_contains":
            sel = check["selector"]
            v = check["value"]
            loc = page.locator(sel).first
            if loc.count() == 0:
                return False, f"dom_text_contains '{sel}' not found"
            got = (loc.inner_text(timeout=2000) or "")
            return (v in got, f"dom_text_contains '{sel}' looking for {v!r} in {got!r}")
        if t == "dom_count":
            sel = check["selector"]
            mn = int(check.get("min", 0))
            mx = check.get("max")
            cnt = page.locator(sel).count()
            ok = cnt >= mn and (mx is None or cnt <= int(mx))
            return ok, f"dom_count '{sel}' got={cnt} min={mn} max={mx}"
        if t == "dom_attr":
            sel = check["selector"]
            attr = check["attr"]
            expected = check["expected"]
            loc = page.locator(sel).first
            if loc.count() == 0:
                return False, f"dom_attr '{sel}' not found"
            got = loc.get_attribute(attr)
            return (got == expected,
                    f"dom_attr '{sel}'.{attr} got={got!r} expected={expected!r}")
        if t == "localstorage_key":
            key = check["key"]
            raw = _localstorage(page, key)
            if raw is None:
                return False, f"localstorage_key '{key}' missing"
            if "regex" in check:
                ok = bool(re.search(check["regex"], raw))
                return ok, f"localstorage_key '{key}' regex {check['regex']!r} on {raw[:120]!r}"
            if "json_match" in check:
                try:
                    parsed = json.loads(raw)
                except Exception as e:
                    return False, f"localstorage_key '{key}' not JSON: {e}"
                want = check["json_match"]
                ok = _json_subset_match(want, parsed)
                return ok, f"localstorage_key '{key}' json_match {want!r} on {parsed!r}"
            if "equals" in check:
                ok = raw == check["equals"]
                return ok, f"localstorage_key '{key}' equals check"
            return True, f"localstorage_key '{key}' present"
        if t == "tab_count":
            pages = getattr(context, "pages", [])
            cnt = len(pages)
            mn = int(check.get("min", 0))
            mx = check.get("max")
            ok = cnt >= mn and (mx is None or cnt <= int(mx))
            return ok, f"tab_count got={cnt} min={mn} max={mx}"
        if t == "agent_status":
            expected = check["expected"]
            ok = agent_status == expected
            return ok, f"agent_status got={agent_status!r} expected={expected!r}"
        return False, f"unknown check type: {t!r}"
    except Exception as e:
        return False, f"check {t!r} crashed: {type(e).__name__}: {e}"


def _json_subset_match(want: Any, got: Any) -> bool:
    """Recursive 'subset' match — every key/index in `want` must equal `got`."""
    if isinstance(want, dict):
        if not isinstance(got, dict):
            return False
        return all(k in got and _json_subset_match(v, got[k]) for k, v in want.items())
    if isinstance(want, list):
        if not isinstance(got, list):
            return False
        # for lists we require every element of `want` to find a match in `got`
        return all(any(_json_subset_match(w, g) for g in got) for w in want)
    return want == got


def evaluate(spec: dict, page: Page, context: object,
             agent_status: str) -> tuple[bool, str, list[dict]]:
    """Run all checks. Returns (overall_ok, first_failure_msg, per_check_details)."""
    checks = spec.get("checks", [])
    if not checks:
        return False, "no checks defined", []
    details: list[dict] = []
    overall_ok = True
    first_fail = ""
    for check in checks:
        ok, msg = _eval_check(check, page, context, agent_status)
        details.append({"check": check, "ok": ok, "msg": msg})
        if not ok and overall_ok:
            overall_ok = False
            first_fail = msg
    return overall_ok, first_fail or "all checks passed", details
