"""Bootstrap MetaMask inside the bench's isolated browser profile.

Direct-Playwright version (no LLM) — more reliable than agent-driven because
MM onboarding has too many tiny variations (locale, pin-extension modals,
post-onboard tutorials) for the agent to reliably shepherd in 40 steps.

The bench profile lives at ~/.config/qa_agent/bench_profile/ so the main
qa_agent profile is untouched.

Usage:
    python -m bench.setup_mm                # headless
    python -m bench.setup_mm --headed       # show the browser for debug
    python -m bench.setup_mm --force        # wipe bench_profile/ first
"""

from __future__ import annotations

import argparse
import re
import shutil
import sys
import time
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from playwright.sync_api import Page, TimeoutError as PwTimeout, sync_playwright  # noqa: E402

from qa_agent.browser import _find_metamask_id, _launch_browser  # noqa: E402
from qa_agent.config import METAMASK_EXT  # noqa: E402
from bench.runner.web3_assert import _read_env, NAMES, bench_address, native_balance_eth  # noqa: E402

BENCH_PROFILE = Path.home() / ".config" / "qa_agent" / "bench_profile"


def _click_first_visible(page: Page, selectors: list[str], *,
                         timeout: int = 5000) -> bool:
    """Try each selector in order; click the first that becomes visible."""
    for sel in selectors:
        try:
            loc = page.locator(sel).first
            if loc.is_visible(timeout=timeout):
                loc.click(timeout=timeout)
                return True
        except Exception:
            continue
    return False


def _wait_visible(page: Page, selectors: list[str], *, timeout: int = 10000):
    """Return the first visible locator or raise."""
    deadline = time.time() + timeout / 1000
    while time.time() < deadline:
        for sel in selectors:
            try:
                loc = page.locator(sel).first
                if loc.is_visible(timeout=300):
                    return loc
            except Exception:
                continue
        time.sleep(0.3)
    raise RuntimeError(f"none of {selectors} became visible in {timeout}ms")


def _find_onboarding_page(context, timeout: float = 15.0) -> Page | None:
    """Wait for MM's onboarding tab to open."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        for pg in context.pages:
            url = pg.url
            if ("chrome-extension://" in url and
                    ("onboarding" in url or "home.html" in url
                     or url.endswith("/"))):
                return pg
        time.sleep(0.5)
    return None


def _fill_seed(page: Page, seed: str) -> None:
    """Fill the Secret Recovery Phrase into whichever MM UI is showing."""
    words = seed.strip().split()
    n = len(words)
    page.wait_for_timeout(1000)

    # Strategy 1: pick word-count selector dropdown (MM needs to know 12 vs 24)
    #    — only present in newer MM onboarding.
    try:
        count_selector = page.locator(
            "select.import-srp__number-of-words-dropdown, "
            "select[data-testid='import-srp-number-of-words-dropdown'], "
            "select.dropdown"
        ).first
        if count_selector.is_visible(timeout=1500):
            try:
                count_selector.select_option(str(n))
            except Exception:
                # Some variants label options like "I have a 24-word SRP"
                count_selector.select_option(label=f"I have a {n}-word")
            page.wait_for_timeout(500)
    except Exception:
        pass

    # Also try the "I have a 24-word phrase" button text
    _click_first_visible(page,
        [f"button:has-text('{n}-word')",
         f"button:has-text('{n} слов')"],
        timeout=500)

    # Strategy 2: individual word inputs (data-testid="import-srp__srp-word-0").
    # Same keystroke-validation caveat as Strategy 3.
    page.wait_for_timeout(500)
    word_inputs = page.locator("[data-testid^='import-srp__srp-word-']")
    wc = word_inputs.count()
    if wc >= n:
        for i, w in enumerate(words):
            loc = page.locator(f"[data-testid='import-srp__srp-word-{i}']").first
            loc.click(timeout=3000)
            loc.press_sequentially(w, delay=5, timeout=5000)
        return
    if wc > 0:
        print(f"[setup_mm] only {wc} word inputs visible, need {n}; "
              f"trying paste-into-first strategy", file=sys.stderr)
        first = page.locator("[data-testid='import-srp__srp-word-0']").first
        first.click(timeout=3000)
        # Most MM versions support multi-word paste into first field.
        first.press_sequentially(seed, delay=5, timeout=15000)
        page.wait_for_timeout(500)
        return

    # Strategy 3: single textarea (older MM UI + current modern `import-srp` form).
    # IMPORTANT: MM's React form validates on keystroke events — using .fill()
    # sets the value directly but does NOT trigger the input handler that gates
    # the Continue button. So we must clear, then press-sequentially.
    for sel in [
        "textarea[data-testid='secret-recovery-phrase']",
        "textarea#import-srp__srp",
        "[data-testid='srp-input-import__srp-note']",
        ".srp-input-import__container textarea",
        "[data-testid='import-srp'] textarea",
        "textarea.mm-textarea",
        "textarea",
    ]:
        try:
            loc = page.locator(sel).first
            if loc.is_visible(timeout=500):
                loc.click(timeout=2000)
                # Clear any existing content first.
                loc.fill("", timeout=2000)
                # Press-sequentially fires keydown/keypress/input events,
                # which MM's React form relies on to validate.
                loc.press_sequentially(seed, delay=10, timeout=15000)
                return
        except Exception:
            continue

    # Debug dump — save HTML + screenshot so we can see what MM is showing.
    dump = Path("/tmp/mm_setup_seed_fail.html")
    dump.write_text(page.content())
    try:
        page.screenshot(path="/tmp/mm_setup_seed_fail.png")
    except Exception:
        pass
    print(f"[setup_mm] seed-input dump written to {dump} and "
          f"/tmp/mm_setup_seed_fail.png", file=sys.stderr)

    raise RuntimeError("could not find any seed-phrase input widget")


def _dismiss_modals(page: Page, max_iters: int = 6) -> None:
    """Click through post-onboarding 'pin the extension' / 'next' / 'done' tutorials."""
    DISMISS = [
        "[data-testid='pin-extension-next']",
        "[data-testid='pin-extension-done']",
        "[data-testid='onboarding-complete-done']",
        "[data-testid='default-settings-got-it']",
        "button:has-text('Next')",
        "button:has-text('Got it')",
        "button:has-text('Done')",
        "button:has-text('Продолжить')",
        "button:has-text('Далее')",
        "button:has-text('Готово')",
        "button:has-text('Понятно')",
    ]
    for _ in range(max_iters):
        if not _click_first_visible(page, DISMISS, timeout=1500):
            break
        page.wait_for_timeout(600)


DASHBOARD_MARKERS = (
    "[data-testid='account-menu-icon']",
    "[data-testid='account-overview__asset-tab']",
    "[data-testid='eth-overview-send']",
    "[data-testid='app-header-copy-button']",
)


def _verify_dashboard(page: Page, expected: str, password: str,
                      timeout: float = 30.0) -> tuple[bool, str]:
    """Wait for dashboard; if locked, enter password. Address match is best-effort
    because newer MM versions hide the full/truncated address behind a menu.
    Success criterion: any DASHBOARD_MARKER becomes visible.
    """
    deadline = time.time() + timeout

    while time.time() < deadline:
        body = ""
        try:
            body = page.inner_text("body", timeout=2000)
        except Exception:
            pass

        if "Разблокировать" in body or "Unlock" in body:
            pwd = page.locator("input[type='password']").first
            try:
                pwd.click(timeout=3000)
                pwd.press_sequentially(password, delay=10, timeout=5000)
                _click_first_visible(page,
                    ["[data-testid='unlock-submit']",
                     "button:has-text('Разблокировать')",
                     "button:has-text('Unlock')"], timeout=3000)
                page.wait_for_timeout(2000)
            except Exception:
                pass
            continue

        # Any dashboard marker visible ⇒ onboarding is done.
        for sel in DASHBOARD_MARKERS:
            try:
                if page.locator(sel).first.is_visible(timeout=500):
                    # Best-effort address extraction — if we find an address
                    # anywhere on the page, return it for cross-check logging.
                    try:
                        btn = page.locator(
                            "[data-testid='app-header-copy-button']"
                        ).first
                        if btn.is_visible(timeout=500):
                            label = btn.inner_text(timeout=1000) or ""
                            if "0x" in label or "…" in label:
                                return True, label.strip()
                    except Exception:
                        pass
                    m = re.search(
                        r"0x[a-fA-F0-9]{4,}\.?\.?\.?[a-fA-F0-9]{2,}", body
                    )
                    return True, (m.group() if m else "<dashboard reached>")
            except Exception:
                continue

        time.sleep(1)

    return False, "timeout waiting for dashboard"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="bench.setup_mm")
    ap.add_argument("--headed", action="store_true",
                    help="run with visible browser (requires DISPLAY)")
    ap.add_argument("--force", action="store_true",
                    help="wipe bench_profile/ before onboarding")
    args = ap.parse_args(argv)

    env = _read_env()
    seed = env.get("BENCH_SEED")
    password = env.get("BENCH_PASSWORD")
    expected = env.get("BENCH_ADDRESS_0", "").lower()
    if not seed or not password or not expected:
        print("missing BENCH_SEED / BENCH_PASSWORD / BENCH_ADDRESS_0 in .env",
              file=sys.stderr)
        return 2

    if args.force and BENCH_PROFILE.exists():
        shutil.rmtree(BENCH_PROFILE)
        print(f"wiped {BENCH_PROFILE}")

    addr = bench_address()
    print(f"bench address: {addr}")
    print("on-chain balances:")
    for chain_id, name in NAMES.items():
        try:
            b = native_balance_eth(chain_id, addr)
            print(f"  {name:<20}: {b:.4f}")
        except Exception as e:
            print(f"  {name:<20}: RPC err {e}")
    print()
    print(f"MM onboarding into: {BENCH_PROFILE}")

    with sync_playwright() as p:
        context, page, _ = _launch_browser(
            p,
            headless=not args.headed,
            extensions=[str(METAMASK_EXT)],
            profile_dir=BENCH_PROFILE,
        )
        try:
            # Step 0 — find the onboarding tab MM auto-opened.
            onb = _find_onboarding_page(context, timeout=15)
            if onb is None:
                print("could not find MM onboarding tab", file=sys.stderr)
                return 3
            onb.bring_to_front()
            onb.wait_for_load_state("domcontentloaded", timeout=10000)
            onb.wait_for_timeout(1500)

            # Navigate through the pre-seed screens. MM's onboarding varies by
            # version: some show Welcome → Create/Import → SRP-choice → Seed,
            # others go Welcome → SRP directly. We loop and fire whichever
            # "advance" button is present until the seed input appears.
            advance_buttons = [
                # Terms checkbox (must click BEFORE the continue button).
                "[data-testid='onboarding-terms-checkbox']",
                "#onboarding__terms-checkbox",
                # Continue-type buttons (order matters: more specific first).
                "[data-testid='onboarding-import-wallet']",
                "[data-testid='onboarding-import-with-srp-button']",
                "[data-testid='import-srp-button']",
                "[data-testid='metametrics-no-thanks']",
                "[data-testid='metametrics-i-agree']",
                "[data-testid='get-started']",
                # Text-based fallback
                "button:has-text('Import an existing wallet')",
                "button:has-text('Импорт существующего кошелька')",
                "button:has-text('Import using Secret Recovery Phrase')",
                "button:has-text('Импорт с помощью секретной фра')",
                "button:has-text('Secret Recovery Phrase')",
                "button:has-text('No thanks')",
                "button:has-text('Нет, спасибо')",
                "button:has-text('I agree')",
                "button:has-text('Get started')",
                "button:has-text('Начать')",
            ]
            SEED_SELS = (
                "[data-testid^='import-srp__srp-word-']",
                "textarea[data-testid='secret-recovery-phrase']",
                "textarea#import-srp__srp",
                ".srp-input-import__container textarea",
                "[data-testid='import-srp'] textarea",
                "textarea.mm-textarea",
            )

            seed_ready = False
            last_click_sig = None
            for it in range(25):
                # Did the seed input appear?
                for sel in SEED_SELS:
                    try:
                        if onb.locator(sel).first.is_visible(timeout=300):
                            seed_ready = True
                            break
                    except Exception:
                        pass
                if seed_ready:
                    break

                # Otherwise try to advance: click the highest-priority visible button.
                clicked = None
                for sel in advance_buttons:
                    try:
                        loc = onb.locator(sel).first
                        if loc.is_visible(timeout=300):
                            loc.click(timeout=3000)
                            clicked = sel
                            break
                    except Exception:
                        continue
                if clicked is None:
                    onb.wait_for_timeout(800)
                    continue
                # Detect click that doesn't navigate (same button twice in a row)
                # — usually a checkbox that doesn't advance. That's fine; next
                # iteration will see the real continue button visible.
                last_click_sig = clicked
                onb.wait_for_timeout(1200)

            if not seed_ready:
                dump = Path("/tmp/mm_setup_pre_seed_fail.html")
                dump.write_text(onb.content())
                try:
                    onb.screenshot(path="/tmp/mm_setup_pre_seed_fail.png")
                except Exception:
                    pass
                print(f"could not advance to seed input (dump: {dump})",
                      file=sys.stderr)
                return 4

            # Fill the seed.
            _fill_seed(onb, seed)
            # Blur the seed field so MM validates and enables the confirm button.
            try:
                onb.keyboard.press("Tab")
            except Exception:
                pass
            onb.wait_for_timeout(1500)

            # Step 6 — confirm seed. Poll for the button to become enabled
            # (MM keeps it disabled until the seed passes validation).
            confirm_clicked = False
            for _ in range(10):
                for sel in [
                    "[data-testid='import-srp-confirm']",
                    "button.import-srp__continue-button",
                    "button:has-text('Confirm Secret Recovery Phrase')",
                    "button:has-text('Подтвердить секретную фразу')",
                    "button:has-text('Продолжить')",
                    "button:has-text('Continue')",
                ]:
                    try:
                        loc = onb.locator(sel).first
                        if loc.is_visible(timeout=500) and loc.is_enabled(timeout=500):
                            loc.click(timeout=3000)
                            confirm_clicked = True
                            break
                    except Exception:
                        continue
                if confirm_clicked:
                    break
                onb.wait_for_timeout(800)
            if not confirm_clicked:
                dump = Path("/tmp/mm_setup_confirm_fail.html")
                dump.write_text(onb.content())
                try:
                    onb.screenshot(path="/tmp/mm_setup_confirm_fail.png")
                except Exception:
                    pass
                print(f"could not click confirm-SRP button (dump: {dump})",
                      file=sys.stderr)
                return 5

            # Step 7 — password. Again: use press_sequentially to fire the
            # keystroke events MM's validator watches for.
            onb.wait_for_timeout(2000)
            pw_inputs = onb.locator("input[type='password']")
            pw_count = pw_inputs.count()
            if pw_count < 2:
                dump = Path("/tmp/mm_setup_pw_fail.html")
                dump.write_text(onb.content())
                try:
                    onb.screenshot(path="/tmp/mm_setup_pw_fail.png")
                except Exception:
                    pass
                print(f"expected 2 password inputs, found {pw_count} "
                      f"(dump: {dump})", file=sys.stderr)
                return 6
            for i in range(2):
                loc = pw_inputs.nth(i)
                loc.click(timeout=3000)
                loc.press_sequentially(password, delay=10, timeout=8000)

            # Password-terms checkbox (label may be long — `has-text` risky)
            onb.wait_for_timeout(500)
            _click_first_visible(onb, [
                "[data-testid='create-password-terms']",
                "input#password-terms",
                "label[for='password-terms']",
                "input[type='checkbox']",
            ], timeout=3000)
            onb.wait_for_timeout(500)

            # Submit password form — poll for enabled state.
            submit_clicked = False
            for _ in range(10):
                for sel in [
                    "[data-testid='create-password-import']",
                    "[data-testid='create-password-wallet']",
                    "[data-testid='create-password-submit']",
                    "button:has-text('Import my wallet')",
                    "button:has-text('Create password')",
                    "button:has-text('Импортировать')",
                    "button:has-text('Создать пароль')",
                ]:
                    try:
                        loc = onb.locator(sel).first
                        if loc.is_visible(timeout=500) and loc.is_enabled(timeout=500):
                            loc.click(timeout=3000)
                            submit_clicked = True
                            break
                    except Exception:
                        continue
                if submit_clicked:
                    break
                onb.wait_for_timeout(800)
            if not submit_clicked:
                dump = Path("/tmp/mm_setup_pw_submit_fail.html")
                dump.write_text(onb.content())
                try:
                    onb.screenshot(path="/tmp/mm_setup_pw_submit_fail.png")
                except Exception:
                    pass
                print(f"could not click create-password button (dump: {dump})",
                      file=sys.stderr)
                return 6

            # Step 8 — the post-onboarding tutorial + pin-extension screens.
            # MM takes a few seconds to finish importing before showing them.
            onb.wait_for_timeout(6000)
            _dismiss_modals(onb, max_iters=10)

            # Step 9 — "Open wallet" final CTA
            for _ in range(5):
                if _click_first_visible(onb, [
                    "[data-testid='onboarding-complete-done']",
                    "button:has-text('Open wallet')",
                    "button:has-text('Открыть кошелек')",
                ], timeout=2000):
                    break
                onb.wait_for_timeout(1000)
            onb.wait_for_timeout(2000)
            _dismiss_modals(onb, max_iters=10)

            # Step 10 — verify via freshly-opened home.html
            mm_id = _find_metamask_id(context)
            if not mm_id:
                print("could not find MM extension id after onboarding",
                      file=sys.stderr)
                return 7
            home = context.new_page()
            home.goto(f"chrome-extension://{mm_id}/home.html",
                      wait_until="domcontentloaded", timeout=15000)
            home.wait_for_timeout(3000)
            _dismiss_modals(home, max_iters=10)
            ok, addr_text = _verify_dashboard(home, expected, password,
                                              timeout=30)
            if not ok:
                dump = Path("/tmp/mm_setup_dashboard_fail.html")
                dump.write_text(home.content())
                try:
                    home.screenshot(path="/tmp/mm_setup_dashboard_fail.png")
                except Exception:
                    pass
                print(f"dashboard verify FAILED: {addr_text}  (dump: {dump})",
                      file=sys.stderr)
                return 7

            # Truncated MM address like "0xcecF…Cd10" — check prefix+suffix when
            # we could extract one. On recent MM versions the address is
            # hidden behind an account menu, so we treat "dashboard reached"
            # alone as success (BIP39 checksum + standard derivation means
            # the imported address MUST be expected).
            if "0x" in addr_text.lower():
                lower = addr_text.lower().replace("…", "...")
                prefix_ok = lower.startswith(expected[:6])
                suffix_ok = lower.endswith(expected[-4:])
                if not (prefix_ok and suffix_ok):
                    print(f"WRONG ADDRESS: MM shows {addr_text!r} "
                          f"but expected {expected}", file=sys.stderr)
                    return 8
                print(f"\nOK — MM dashboard shows {addr_text!r} "
                      f"(matches {expected})")
            else:
                print(f"\nOK — MM dashboard reached "
                      f"(address not shown directly; BIP39 seed → expected "
                      f"{expected})")
            print(f"bench_profile ready at {BENCH_PROFILE}")
            return 0

        finally:
            context.close()


if __name__ == "__main__":
    raise SystemExit(main())
