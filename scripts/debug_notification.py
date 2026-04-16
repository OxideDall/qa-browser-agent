#!/usr/bin/env python3
"""Debug: inspect MetaMask notification.html after Uniswap connect request.

Steps:
1. Open MM notification.html, unlock if needed (keystroke simulation)
2. Open Uniswap, trigger Connect → MetaMask
3. Open notification.html again, dump what extractors see
"""

import json
import sys
import time
sys.path.insert(0, "/home/oxide")

from pathlib import Path
from playwright.sync_api import sync_playwright, TimeoutError as PwTimeout

PROFILE_DIR = Path.home() / ".config" / "qa_agent" / "browser_profile"
METAMASK_EXT = Path.home() / "extensions" / "metamask"
PASSWORD = "Testpassword1!"

BROWSER_ARGS = [
    "--disable-blink-features=AutomationControlled",
    "--use-angle=gl",
    "--disable-dev-shm-usage",
    "--no-sandbox",
    "--headless=new",
]
STEALTH_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)


def find_mm_id(context):
    for sw in context.service_workers:
        if "chrome-extension://" in sw.url:
            return sw.url.split("chrome-extension://")[1].split("/")[0]
    for pg in context.pages:
        if "chrome-extension://" in pg.url:
            return pg.url.split("chrome-extension://")[1].split("/")[0]
    return None


def dump_page_info(page, label):
    """Print page body text and test both extractors."""
    print(f"\n{'='*60}")
    print(f"  {label}")
    print(f"  URL: {page.url}")
    print(f"{'='*60}")

    # Body text
    try:
        body = page.inner_text("body", timeout=3000)
        print(f"\n--- Body text (first 500 chars) ---")
        print(body[:500])
        print(f"--- (total {len(body)} chars) ---")
    except Exception as e:
        print(f"  body error: {e}")

    # Screenshot
    try:
        page.screenshot(path=f"/home/oxide/qa_screenshots/debug_{label.replace(' ', '_')}.png")
        print(f"  Screenshot saved: debug_{label.replace(' ', '_')}.png")
    except Exception as e:
        print(f"  Screenshot error: {e}")

    # Test JS extractor
    print(f"\n--- JS Extractor ---")
    try:
        from qa_agent import JS_EXTRACTOR
        result = page.evaluate(JS_EXTRACTOR)
        print(f"  Elements: {result['count']}")
        for el in result['elements']:
            print(f"    {el}")
        print(f"  Text nodes: {len(result.get('text', []))}")
        for t in result.get('text', [])[:10]:
            print(f"    {t}")
    except Exception as e:
        print(f"  JS Extractor BLOCKED: {type(e).__name__}: {str(e)[:100]}")

    # Test fallback extractor
    print(f"\n--- Fallback (CDP-safe) Extractor ---")
    try:
        from qa_agent import _extract_from_html
        result = _extract_from_html(page)
        print(f"  Elements: {result['count']}")
        for el in result['elements']:
            # Remove _bbox for readability
            el2 = {k: v for k, v in el.items() if k != '_bbox'}
            print(f"    {el2}")
        print(f"  Text nodes: {len(result.get('text', []))}")
        for t in result.get('text', [])[:10]:
            print(f"    {t}")
    except Exception as e:
        print(f"  Fallback Extractor FAILED: {type(e).__name__}: {str(e)[:100]}")


def unlock_mm(page, verbose=True):
    """Unlock MetaMask using keystroke simulation (not fill())."""
    body = page.inner_text("body", timeout=3000)[:200]
    if verbose:
        print(f"  MM body: {body[:100]}")

    if "Разблокировать" not in body and "Unlock" not in body:
        print("  MM already unlocked (or not on lock screen)")
        return True

    # Find and focus password input
    try:
        pwd_input = page.locator("input[type='password']").first
        if not pwd_input.is_visible(timeout=2000):
            print("  Password input not visible")
            return False
        pwd_input.click(timeout=3000)
        time.sleep(0.2)
        # Use keystroke simulation instead of fill()
        pwd_input.type(PASSWORD, delay=20)
        time.sleep(0.3)

        # Click unlock button
        for sel in [
            "button:has-text('Разблокировать')",
            "button:has-text('Unlock')",
            "button[data-testid='unlock-submit']",
        ]:
            try:
                btn = page.locator(sel).first
                if btn.is_visible(timeout=500):
                    btn.click(timeout=3000)
                    print(f"  Clicked unlock via: {sel}")
                    time.sleep(2)
                    break
            except Exception:
                continue

        # Verify unlock
        body2 = page.inner_text("body", timeout=3000)[:200]
        if "Разблокировать" in body2 or "Unlock" in body2:
            print(f"  STILL LOCKED after unlock attempt!")
            print(f"  Body: {body2[:100]}")
            return False
        print("  MetaMask unlocked!")
        return True
    except Exception as e:
        print(f"  Unlock error: {e}")
        return False


def main():
    Path("/home/oxide/qa_screenshots").mkdir(exist_ok=True)

    with sync_playwright() as p:
        ext_path = str(METAMASK_EXT.resolve())
        args = list(BROWSER_ARGS)
        args.append(f"--disable-extensions-except={ext_path}")
        args.append(f"--load-extension={ext_path}")

        context = p.chromium.launch_persistent_context(
            str(PROFILE_DIR),
            headless=False,
            args=args,
            user_agent=STEALTH_UA,
            viewport={"width": 1280, "height": 720},
        )
        context.add_init_script(
            'Object.defineProperty(navigator,"webdriver",{get:()=>undefined})'
        )

        page = context.pages[0] if context.pages else context.new_page()
        page.wait_for_timeout(3000)

        mm_id = find_mm_id(context)
        print(f"MM ext id: {mm_id}")
        if not mm_id:
            print("MetaMask not found!")
            context.close()
            return

        # === Step 1: Unlock MetaMask ===
        print("\n=== Step 1: Unlock MetaMask ===")
        notif_url = f"chrome-extension://{mm_id}/notification.html"
        page.goto(notif_url, timeout=10000, wait_until="domcontentloaded")
        page.wait_for_timeout(2000)

        dump_page_info(page, "notification_before_unlock")
        unlocked = unlock_mm(page)

        if unlocked:
            page.wait_for_timeout(1000)
            dump_page_info(page, "notification_after_unlock")

        # === Step 2: Navigate to Uniswap ===
        print("\n=== Step 2: Open Uniswap ===")
        uni_page = context.new_page()
        uni_page.goto("https://app.uniswap.org", timeout=30000, wait_until="domcontentloaded")
        uni_page.wait_for_timeout(5000)

        # Find Connect Wallet button
        print("  Looking for Connect button...")
        connect_clicked = False
        for sel in [
            "button:has-text('Connect')",
            "button:has-text('Подключить')",
            "[data-testid='navbar-connect-wallet']",
        ]:
            try:
                btn = uni_page.locator(sel).first
                if btn.is_visible(timeout=2000):
                    btn.click(timeout=5000)
                    print(f"  Clicked connect: {sel}")
                    connect_clicked = True
                    break
            except Exception:
                continue

        if not connect_clicked:
            print("  Connect button not found, trying JS extractor...")
            try:
                from qa_agent import JS_EXTRACTOR
                result = uni_page.evaluate(JS_EXTRACTOR)
                for el in result['elements']:
                    if 'connect' in (el.get('text', '') or '').lower():
                        print(f"  Found: {el}")
                        eid = el['id']
                        try:
                            uni_page.click(f'[data-qa-id="{eid}"]', timeout=5000)
                            connect_clicked = True
                            print(f"  Clicked via data-qa-id={eid}")
                        except Exception:
                            if el.get('_cx'):
                                uni_page.mouse.click(el['_cx'], el['_cy'])
                                connect_clicked = True
                                print(f"  Clicked via coords ({el['_cx']}, {el['_cy']})")
                        break
            except Exception as e:
                print(f"  JS extractor error: {e}")

        if not connect_clicked:
            print("  FAILED to click Connect button!")
            dump_page_info(uni_page, "uniswap_no_connect")
            context.close()
            return

        uni_page.wait_for_timeout(2000)

        # === Step 3: Click MetaMask in wallet modal ===
        print("\n=== Step 3: Click MetaMask in wallet modal ===")
        mm_clicked = False

        # Try JS extractor to find MetaMask option
        try:
            from qa_agent import JS_EXTRACTOR
            result = uni_page.evaluate(JS_EXTRACTOR)
            for el in result['elements']:
                text = (el.get('text', '') or '').lower()
                if 'metamask' in text:
                    print(f"  Found MetaMask: {el}")
                    # Use coordinate click (data-qa-id click fails due to pointer-events)
                    if el.get('_cx'):
                        uni_page.mouse.click(el['_cx'], el['_cy'])
                        mm_clicked = True
                        print(f"  Clicked MetaMask via coords ({el['_cx']}, {el['_cy']})")
                    else:
                        # Try data-qa-id first, fallback to coords from bbox
                        try:
                            uni_page.click(f'[data-qa-id="{el["id"]}"]', timeout=3000)
                            mm_clicked = True
                        except Exception:
                            # Calculate center from what we can get
                            loc = uni_page.locator(f'[data-qa-id="{el["id"]}"]')
                            bbox = loc.bounding_box()
                            if bbox:
                                uni_page.mouse.click(
                                    bbox['x'] + bbox['width']/2,
                                    bbox['y'] + bbox['height']/2)
                                mm_clicked = True
                                print(f"  Clicked MetaMask via bbox coords")
                    break
        except Exception as e:
            print(f"  JS extractor error: {e}")

        if not mm_clicked:
            # Try text-based approach
            for sel in [
                "div:has-text('MetaMask')",
                "span:has-text('MetaMask')",
                "button:has-text('MetaMask')",
            ]:
                try:
                    loc = uni_page.locator(sel).first
                    bbox = loc.bounding_box()
                    if bbox:
                        uni_page.mouse.click(
                            bbox['x'] + bbox['width']/2,
                            bbox['y'] + bbox['height']/2)
                        mm_clicked = True
                        print(f"  Clicked MetaMask via text selector bbox: {sel}")
                        break
                except Exception:
                    continue

        if not mm_clicked:
            print("  FAILED to click MetaMask!")
            dump_page_info(uni_page, "uniswap_wallet_modal")
            context.close()
            return

        # === Step 4: Wait for MetaMask notification and inspect ===
        print("\n=== Step 4: Check for MetaMask notification ===")
        uni_page.wait_for_timeout(3000)

        # Check if MetaMask opened a popup
        ext_page = None
        for pg in context.pages:
            if not pg.is_closed() and "chrome-extension://" in pg.url:
                if pg.url != notif_url or pg != page:
                    ext_page = pg
                    break

        if not ext_page:
            # Try opening notification.html directly
            print("  No popup found, opening notification.html...")
            ext_page = context.new_page()
            ext_page.goto(notif_url, timeout=10000, wait_until="domcontentloaded")
            ext_page.wait_for_timeout(2000)

            body = ext_page.inner_text("body", timeout=3000)
            if len(body.strip()) < 5:
                print("  Empty notification — no pending request")
                ext_page.close()
                ext_page = None

        if ext_page:
            ext_page.bring_to_front()
            ext_page.wait_for_timeout(1000)

            # Check if locked again
            body = ext_page.inner_text("body", timeout=3000)[:200]
            if "Разблокировать" in body or "Unlock" in body:
                print("  MM locked again, unlocking...")
                unlock_mm(ext_page)
                ext_page.wait_for_timeout(2000)

            dump_page_info(ext_page, "notification_connect_request")

            # Try clicking Connect/Next/Approve buttons
            print("\n=== Step 5: Try clicking approval buttons ===")
            for btn_text in ["Далее", "Next", "Подключить", "Connect", "Подтвердить", "Confirm", "Approve"]:
                for tag in ["button", "div[role='button']"]:
                    sel = f"{tag}:has-text('{btn_text}')"
                    try:
                        loc = ext_page.locator(sel).first
                        if loc.is_visible(timeout=500):
                            print(f"  Found button: '{btn_text}' via {sel}")
                            loc.click(timeout=3000)
                            print(f"  Clicked '{btn_text}'!")
                            ext_page.wait_for_timeout(1500)
                            # Dump again to see next state
                            body2 = ext_page.inner_text("body", timeout=2000)[:200]
                            print(f"  After click body: {body2[:100]}")
                            break
                    except Exception:
                        continue

            # Final state
            ext_page.wait_for_timeout(1000)
            if not ext_page.is_closed():
                dump_page_info(ext_page, "notification_final_state")
        else:
            print("  No MetaMask notification found!")
            # Check all pages
            print(f"  All pages ({len(context.pages)}):")
            for i, pg in enumerate(context.pages):
                if not pg.is_closed():
                    print(f"    {i}: {pg.url[:80]}")

        # Check Uniswap state
        print("\n=== Uniswap final state ===")
        if not uni_page.is_closed():
            uni_page.bring_to_front()
            uni_page.wait_for_timeout(1000)
            dump_page_info(uni_page, "uniswap_final")

        context.close()
        print("\nDone!")


if __name__ == "__main__":
    main()
