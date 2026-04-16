# Android bench — real-device fixtures

This directory is the Android counterpart of `bench/`. Fixtures run
against a physical phone over ADB + uiautomator2 instead of a headless
browser.

## Requirements

- A rooted-or-developer Android device with ADB over TCP enabled.
  Tested on Redmi Note 8 Pro (begonia), Android 10.
- `adb` on the host (`dnf install android-tools` / `apt install adb`).
- `pip install uiautomator2 Pillow`
- The first `u2.connect(...)` call auto-installs the UIAutomator2 APK and
  the `com.github.uiautomator/.ToastService` / FastInputIME helpers on
  the phone. No further action needed.

Optional but recommended:
- Tailscale (or any VPN overlay) if the phone is remote — the bench
  only uses ADB; do **not** set a Tailscale exit node on the phone,
  otherwise marketplace traffic will egress through the VPN and you
  may get rate-limited or shown different content.

One-time device connect:

```bash
# On the phone (from Termux or via USB + adb first-time pairing):
adb tcpip 5555

# On the host:
adb connect <device-ip>:5555
adb devices                          # should list the device as "device"
```

## Running

```bash
# Single fixture
ANDROID_SERIAL=192.168.1.42:5555 \
  python -m bench.android.runner android_aliexpress_l1_search

# Whole suite
ANDROID_SERIAL=192.168.1.42:5555 \
  python -m bench.android.runner --all
```

The first run will wake + unlock the phone, `app_start` the target
package, then drive the same FSM the browser bench uses, just with
uiautomator2 as the driver. Logs land in `bench/android/runs/<id>_<ts>.jsonl`
(gitignored).

## Fixture layout

```
bench/android/fixtures/<id>/
├── config.toml          [fixture] id/category/level/title
│                        [android] package / serial (optional)
│                        [budget]  max_steps / max_tokens / retries
├── task.txt             natural-language task for the agent
├── assert.json          declarative checks (subset below), OR
└── assert.py            def check(run_log) -> (ok, msg)
```

Declarative check types (just the ones that make sense on-device):

| type                    | fields                         | meaning                              |
|-------------------------|--------------------------------|--------------------------------------|
| `agent_status`          | `expected: "PASS"`             | FSM reached DONE_PASS                |
| `current_package`       | `expected: "ru.aliexpress.buyer"` | phone still in the target app     |
| `regex_in_description`  | `pattern: "…"` (+ `ignore_case`) | regex on the agent's done PASS text |
| `hierarchy_contains`    | `value: "some text"`           | UI hierarchy XML contains the text   |

## Current fixtures

| id                              | level | goal                                                        |
|---------------------------------|------:|-------------------------------------------------------------|
| `android_aliexpress_l1_search`  |     1 | open AliExpress → dismiss the promo bottom-sheet (`press back`) → tap the `Найти на AliExpress` search bar → verify search screen loads |

Set `ANDROID_SERIAL=<ip>:5555` so the runner finds your device.

## Known limits

- **Lock screen mid-run.** The runner unlocks up-front but nothing keeps
  the display awake if the device times out mid-task. For long runs,
  either bump the screen-off timeout on the phone or add a wakelock
  (`adb shell settings put system screen_off_timeout 600000` etc.).
- **IME input.** `type` uses uiautomator2's FastInputIME. If another
  keyboard is default, typing might drop characters. Set FastInput as
  default keyboard via uiautomator2 once: `d.set_fastinput_ime(True)`.
- **Keyguard without PIN assumed.** `run_android_task` does
  `device.screen_on() + device.unlock()` + a fallback swipe. A phone
  with a password/pattern lock will not be unlocked automatically.
