"""Playwright browser launch with stealth args + extension loading support."""

from pathlib import Path

from playwright.sync_api import BrowserContext

from .config import BROWSER_ARGS, PROFILE_DIR, STEALTH_INIT_SCRIPT, STEALTH_UA


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
