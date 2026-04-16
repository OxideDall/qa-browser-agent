"""Phone connection helper for Redmi Note 8 Pro via Tailscale ADB."""

import uiautomator2 as u2
import time
import subprocess

DEVICE_ADDR = "100.85.141.101:5555"


def ensure_adb():
    """Make sure ADB is connected."""
    r = subprocess.run(["adb", "connect", DEVICE_ADDR],
                       capture_output=True, text=True, timeout=10)
    if "connected" not in r.stdout and "already" not in r.stdout:
        raise ConnectionError(f"ADB connect failed: {r.stdout} {r.stderr}")


def connect():
    """Connect to the phone, return uiautomator2 device."""
    ensure_adb()
    d = u2.connect(DEVICE_ADDR)
    d.settings["wait_timeout"] = 10
    d.settings["operation_delay"] = (0.2, 0.2)
    return d


def wait_and_click(d, timeout=10, **kwargs):
    """Wait for element and click it. Returns True if found."""
    el = d(**kwargs)
    if el.wait(timeout=timeout):
        el.click()
        return True
    return False


def scroll_and_collect(d, collect_fn, max_scrolls=5):
    """Scroll down, collect items each time. Returns deduplicated list."""
    all_items = []
    seen = set()
    for i in range(max_scrolls):
        items = collect_fn(d)
        for item in items:
            key = item.get("name", "") + item.get("price", "")
            if key and key not in seen:
                seen.add(key)
                all_items.append(item)
        d.swipe_ext("up", scale=0.7)
        time.sleep(1.5)
    return all_items
