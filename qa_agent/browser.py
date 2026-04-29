"""Playwright browser launch with stealth args + extension loading support."""

from pathlib import Path

from playwright.sync_api import BrowserContext

from .config import BROWSER_ARGS, PROFILE_DIR, STEALTH_INIT_SCRIPT, STEALTH_UA


# Injected before any page script runs. Wires a MutationObserver to a
# bounded ring buffer on `window.__qa_mutations`, plus a per-step reset
# helper. The Python side polls + clears this buffer between agent steps
# (runtime.actions.detect_flicker) — the browser-side cost is one
# observer per page; the buffer caps at 5_000 records so heavy SPAs
# can't OOM the page. Each entry has the bare minimum needed to call
# the same DOM "node" out across attach/detach pairs (parent tag, child
# tag, text fingerprint, and a high-resolution timestamp).
MUTATION_INIT_SCRIPT = r"""
(() => {
  if (window.__qa_mutations) return;
  const MAX = 5000;
  const buf = [];
  const fp = (n) => {
    try {
      if (!n) return '';
      if (n.nodeType === 3) return 't:' + (n.nodeValue || '').slice(0, 32);
      const tag = (n.nodeName || '?').toLowerCase();
      const id = n.id ? '#' + n.id : '';
      const cls = (n.className && typeof n.className === 'string')
        ? '.' + n.className.split(/\s+/).filter(Boolean).slice(0, 3).join('.')
        : '';
      const txt = (n.textContent || '').trim().slice(0, 32);
      return tag + id + cls + (txt ? '|' + txt : '');
    } catch (e) { return '?'; }
  };
  const obs = new MutationObserver((records) => {
    const now = performance.now();
    for (const r of records) {
      if (r.type !== 'childList') continue;
      const parent = fp(r.target);
      for (const n of r.addedNodes) {
        buf.push({ t: now, kind: 'add', parent, node: fp(n) });
      }
      for (const n of r.removedNodes) {
        buf.push({ t: now, kind: 'remove', parent, node: fp(n) });
      }
    }
    if (buf.length > MAX) buf.splice(0, buf.length - MAX);
  });
  try {
    obs.observe(document.documentElement || document, {
      childList: true, subtree: true,
    });
  } catch (e) { /* document not yet ready — observer will attach on next frame */ }
  window.__qa_mutations = {
    drain: () => { const out = buf.slice(); buf.length = 0; return out; },
    peek:  () => buf.slice(),
    size:  () => buf.length,
  };
})();
"""


def _launch_browser(
    p,
    headless: bool,
    extensions: list[str] | None = None,
    init_script: str | None = None,
    profile_dir: Path | None = None,
):
    """Launch browser. Returns (context, page, needs_close_browser).

    With extensions: persistent context (required for extensions).
    Without: regular launch for cleaner isolation.
    Both paths use stealth args + --headless=new for WebGL/WASM support in DeFi SPAs.

    If `init_script` is provided, it's injected via `context.add_init_script`
    BEFORE any page navigation so it can seed `localStorage` / `sessionStorage`
    for the target origin on first load (used by QA runs that need a pre-baked
    auth session without going through the login UI).

    `profile_dir` overrides the default persistent-context directory — used by
    bench to isolate the benchmark wallet from any pre-existing qa_agent
    profile. Only meaningful for the extensions path.
    """
    if extensions:
        prof = profile_dir if profile_dir is not None else PROFILE_DIR
        prof.mkdir(parents=True, exist_ok=True)
        ext_paths = [str(Path(e).resolve()) for e in extensions]
        args = list(BROWSER_ARGS)
        args.append(f"--disable-extensions-except={','.join(ext_paths)}")
        for ep in ext_paths:
            args.append(f"--load-extension={ep}")
        if headless:
            args.append("--headless=new")

        context = p.chromium.launch_persistent_context(
            str(prof),
            headless=False,  # managed by --headless=new arg
            args=args,
            user_agent=STEALTH_UA,
            viewport={"width": 1280, "height": 720},
        )
        context.add_init_script(STEALTH_INIT_SCRIPT)
        context.add_init_script(MUTATION_INIT_SCRIPT)
        if init_script:
            context.add_init_script(init_script)

        # Wait for extensions to initialize and open onboarding tabs
        page = context.pages[0] if context.pages else context.new_page()
        page.wait_for_timeout(3000)
        for pg in context.pages:
            if "extension" in pg.url or "onboarding" in pg.url or "welcome" in pg.url:
                page = pg
                break
        else:
            page.wait_for_timeout(2000)
            for pg in context.pages:
                if "extension" in pg.url or "onboarding" in pg.url or "welcome" in pg.url:
                    page = pg
                    break
        page.bring_to_front()
        return context, page, False

    # No extensions — cleaner isolation
    args = list(BROWSER_ARGS)
    if headless:
        args.append("--headless=new")
    browser = p.chromium.launch(headless=False, args=args)
    context = browser.new_context(
        viewport={"width": 1280, "height": 720},
        user_agent=STEALTH_UA,
    )
    context.add_init_script(STEALTH_INIT_SCRIPT)
    context.add_init_script(MUTATION_INIT_SCRIPT)
    if init_script:
        context.add_init_script(init_script)
    page = context.new_page()
    return context, page, True


def _find_metamask_id(context: BrowserContext) -> str | None:
    """Find MetaMask extension ID from loaded service workers or pages."""
    for sw in context.service_workers:
        if "chrome-extension://" in sw.url:
            return sw.url.split("chrome-extension://")[1].split("/")[0]
    for pg in context.pages:
        if "chrome-extension://" in pg.url:
            return pg.url.split("chrome-extension://")[1].split("/")[0]
    return None
