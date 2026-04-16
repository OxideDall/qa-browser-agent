"""Post-hoc check that bench_profile's MM matches BENCH_ADDRESS_0.

Opens chromium with the bench profile + MM, unlocks, navigates to MM's
account page, grabs the displayed address, compares against .env's
BENCH_ADDRESS_0. Does NOT go through onboarding — assumes it's done.

Usage:
    python -m bench.verify_mm
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from playwright.sync_api import sync_playwright  # noqa: E402

from qa_agent.browser import _find_metamask_id, _launch_browser  # noqa: E402
from qa_agent.config import METAMASK_EXT  # noqa: E402
from bench.runner.web3_assert import _read_env  # noqa: E402
from bench.setup_mm import BENCH_PROFILE  # noqa: E402


def main() -> int:
    env = _read_env()
    expected = env.get("BENCH_ADDRESS_0", "").lower()
    password = env.get("BENCH_PASSWORD", "")
    if not expected or not password:
        print("missing BENCH_ADDRESS_0 or BENCH_PASSWORD in .env",
              file=sys.stderr)
        return 2

    if not BENCH_PROFILE.exists():
        print(f"{BENCH_PROFILE} does not exist — run `python -m bench.setup_mm` first",
              file=sys.stderr)
        return 2

    with sync_playwright() as p:
        context, page, _ = _launch_browser(
            p,
            headless=True,
            extensions=[str(METAMASK_EXT)],
            profile_dir=BENCH_PROFILE,
        )
        time.sleep(3)

        mm_id = _find_metamask_id(context)
        if not mm_id:
            print("could not find MM extension id", file=sys.stderr)
            return 3

        mm_page = context.new_page()
        mm_page.goto(f"chrome-extension://{mm_id}/home.html",
                     wait_until="domcontentloaded", timeout=15000)
        mm_page.wait_for_timeout(2000)

        body = mm_page.inner_text("body", timeout=5000)
        if "Разблокировать" in body or "Unlock" in body:
            # Locked — enter password.
            pwd = mm_page.locator("input[type='password']").first
            pwd.click(timeout=3000)
            pwd.type(password, delay=20)
            mm_page.wait_for_timeout(300)
            for sel in (
                "button[data-testid='unlock-submit']",
                "button:has-text('Разблокировать')",
                "button:has-text('Unlock')",
            ):
                try:
                    btn = mm_page.locator(sel).first
                    if btn.is_visible(timeout=500):
                        btn.click(timeout=3000)
                        break
                except Exception:
                    continue
            mm_page.wait_for_timeout(3000)

        # Try the "copy address" button — data-testid is stable across locales.
        addr_text = ""
        try:
            el = mm_page.locator("[data-testid='app-header-copy-button']").first
            if el.is_visible(timeout=3000):
                label = el.inner_text(timeout=2000) or ""
                # Usually shows e.g. "0xcec...Cd10"
                addr_text = label.strip()
        except Exception:
            pass

        # Fallback: scan body text for a 0x... string.
        if not addr_text:
            import re
            m = re.search(r"0x[a-fA-F0-9]{4,}\.?\.?\.?[a-fA-F0-9]{2,}",
                          mm_page.inner_text("body", timeout=3000))
            if m:
                addr_text = m.group()

        context.close()

    if not addr_text:
        print("could not extract address from MM dashboard", file=sys.stderr)
        return 4

    # MM typically shows truncated form "0xcecF...Cd10" — compare on prefix/suffix.
    lower = addr_text.lower().replace("…", "...")
    prefix_ok = lower.startswith(expected[:6])
    suffix_ok = lower.endswith(expected[-4:])
    if prefix_ok and suffix_ok:
        print(f"OK: MM shows {addr_text!r} — matches BENCH_ADDRESS_0={expected}")
        return 0
    print(f"FAIL: MM shows {addr_text!r}, expected BENCH_ADDRESS_0={expected}",
          file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
