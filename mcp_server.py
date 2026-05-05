#!/usr/bin/env python3
"""MCP server exposing qa_agent as tools over stdio transport.

qa_run and qa_setup_metamask shell out to `python -m qa_agent --json-result`
via subprocess for full isolation from FastMCP's asyncio/sniffio context — the
playwright.sync_api can't run inside an event loop, and anyio.to_thread.run_sync
copies the caller's contextvars into worker threads, which poisons sniffio.

Running in a fresh subprocess sidesteps all of that.

Usage in .mcp.json or claude_desktop_config.json:
    {
      "mcpServers": {
        "qa-browser": {
          "command": "/usr/bin/python3",
          "args": ["mcp_server.py"],
          "env": {
            "ANTHROPIC_API_KEY": "sk-ant-..."
          }
        }
      }
    }

MCP hosts spawn the server with an empty env, so provider API keys must
either be set via the host's `"env"` block (shown above) or listed in a
`.env` file in the repo root — this module auto-loads that file.
"""

import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

_ROOT = Path(__file__).resolve().parent

# Allow importing qa_agent from this directory for status checks
sys.path.insert(0, str(_ROOT))


def _load_dotenv(path: Path) -> None:
    """Minimal .env loader — no python-dotenv dependency. Lines like
    `KEY=value` or `KEY="value with spaces"` are honoured; existing env
    wins (so the MCP host can still override with its own "env" block)."""
    if not path.is_file():
        return
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        k = k.strip()
        v = v.strip().strip('"').strip("'")
        if k and k not in os.environ:
            os.environ[k] = v


# MCP hosts start mcp_server.py in a clean environment — pull in the
# project-local .env so ANTHROPIC_API_KEY / OPENROUTER_API_KEY / etc.
# reach the subprocess that actually runs the agent.
_load_dotenv(_ROOT / ".env")

from mcp.server.fastmcp import FastMCP

import qa_agent

REPO_DIR = Path(__file__).resolve().parent

mcp = FastMCP("qa-browser-agent")


def _run_cli(cli_args: list[str], timeout: float) -> dict:
    """Run `python -m qa_agent --json-result <cli_args>` and return a result dict.

    The CLI emits exactly one JSON line on stdout as its final output; everything
    else (progress logs, errors) goes to stderr. On failure we still produce a
    structured dict with status=ERROR so the MCP client always gets JSON.
    """
    cmd = [sys.executable, "-m", "qa_agent", "--json-result", *cli_args]
    t_start = time.time()
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(REPO_DIR),
        )
    except subprocess.TimeoutExpired as e:
        return {
            "status": "ERROR",
            "description": f"subprocess timeout after {timeout}s",
            "steps": 0,
            "elapsed": round(time.time() - t_start, 1),
            "log": (e.stderr or "")[-4000:] if isinstance(e.stderr, str) else "",
        }
    except FileNotFoundError as e:
        return {
            "status": "ERROR",
            "description": f"cannot launch qa_agent: {e}",
            "steps": 0,
            "elapsed": round(time.time() - t_start, 1),
            "log": "",
        }

    # Parse the final JSON line from stdout. Anything earlier on stdout would be
    # a bug — --json-result reroutes all prints to stderr — but we handle it just
    # in case by scanning lines from the end.
    parsed: dict | None = None
    for line in reversed(proc.stdout.strip().splitlines()):
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
            if isinstance(obj, dict) and "status" in obj:
                parsed = obj
                break
        except json.JSONDecodeError:
            continue

    if parsed is None:
        return {
            "status": "ERROR",
            "description": (
                f"qa_agent exited {proc.returncode} without JSON result"
            ),
            "steps": 0,
            "elapsed": round(time.time() - t_start, 1),
            "log": (proc.stderr or "")[-4000:],
        }

    parsed["log"] = (proc.stderr or "")[-4000:]
    return parsed


@mcp.tool()
def qa_run(
    task: str,
    url: str | None = None,
    headless: bool = True,
    max_steps: int = 60,
    metamask: bool = False,
    extensions: list[str] | None = None,
    init_script: str | None = None,
    http_credentials: dict | None = None,
) -> dict:
    """Run a browser QA task. Claude Haiku drives Playwright to test web apps.

    Args:
        task: Natural language description of what to test.
        url: Starting URL (auto-detected from task if omitted).
        headless: Run browser headless. Default True.
        max_steps: Maximum agent steps before timeout. Default 60.
        metamask: Load bundled MetaMask extension (requires prior setup).
        extensions: Paths to additional unpacked extensions.
        init_script: Optional JavaScript source injected via Playwright
            context.add_init_script. Runs in every new page of the
            BrowserContext BEFORE any page-side script — including the
            SPA bundle and inline <script> tags. Use to pre-seed
            localStorage/sessionStorage/cookies with an auth session,
            monkey-patch fetch, install console hooks, etc.
        http_credentials: Optional `{"username": "...", "password": "..."}`
            forwarded to Playwright's context kwarg of the same name.
            Resolves Basic-auth challenges across every
            navigation/fetch/EventSource in the context. Use this rather
            than monkey-patching fetch — EventSource doesn't accept
            custom headers, so an init_script wrapper breaks SSE.

    Returns:
        dict with keys: status (PASS/FAIL/ERROR), description, steps, elapsed, log.
    """
    if metamask and not qa_agent.METAMASK_EXT.exists():
        return {
            "status": "ERROR",
            "description": (
                f"MetaMask not found at {qa_agent.METAMASK_EXT}. "
                "Run qa_setup_metamask first."
            ),
            "steps": 0,
            "elapsed": 0.0,
            "log": "",
        }

    cli_args: list[str] = ["--max-steps", str(max_steps), "-v"]
    if headless:
        cli_args.append("--headless")
    if metamask:
        cli_args.append("--metamask")
    if url:
        cli_args += ["--url", url]
    for ext in extensions or []:
        cli_args += ["--extension", ext]
    if http_credentials:
        u = http_credentials.get("username", "")
        p = http_credentials.get("password", "")
        if not u:
            return {
                "status": "ERROR",
                "description": "http_credentials needs `username` and `password` keys",
                "steps": 0, "elapsed": 0.0, "log": "",
            }
        cli_args += ["--http-creds", f"{u}:{p}"]

    # init_script is passed as JS source over MCP; write to a temp file and
    # hand the path to the CLI. Guaranteed cleanup after _run_cli returns.
    tmp_path: str | None = None
    if init_script is not None:
        fd, tmp_path = tempfile.mkstemp(
            suffix=".js", prefix="qa_init_", dir=str(REPO_DIR)
        )
        try:
            with open(fd, "w") as f:
                f.write(init_script)
        except Exception:
            try:
                Path(tmp_path).unlink()
            except OSError:
                pass
            raise
        cli_args += ["--init-script", tmp_path]

    cli_args.append(task)

    # Generous timeout: each step can take ~10s, plus cold start + browser launch.
    timeout = max(60.0, max_steps * 15.0 + 30.0)
    try:
        return _run_cli(cli_args, timeout=timeout)
    finally:
        if tmp_path:
            try:
                Path(tmp_path).unlink()
            except OSError:
                pass


@mcp.tool()
def qa_tagged(
    steps: str,
    url: str | None = None,
    headless: bool = True,
    init_script: str | None = None,
    http_credentials: dict | None = None,
    trace: bool = False,
    continue_on_fail: bool = False,
) -> dict:
    """Run a deterministic tagged-DSL assertion suite. NO LLM is used.

    Use this for smoke checks where the assertions are known up front:
    log-in flows you've scripted, regression checks for a fixed page,
    CI gates where you want zero LLM cost and deterministic timing.
    Each step's verdict is independent — assertions either pass or the
    run FAILs at the first step that doesn't (override with
    continue_on_fail=True).

    Args:
        steps: The tagged-DSL program. One step per line. See
            qa_agent.tagged docstring for the full grammar:
                click <selector>
                type <selector> "text"
                goto <url> / wait <ms> / wait_for <sel> [timeout_ms]
                press <key> / scroll up|down / screenshot / evaluate <jsExpr>
                expect_visible / expect_hidden <sel> [timeout_ms]
                expect_text "<substring>"
                expect_url <regex>
                expect_count <sel> <op> <n>
                expect_eval <jsExpr> <op> "<expected>"
            Selectors: `button "OK"`, `dialog`, `"Click me"` (text),
            CSS (`.x`, `#y`, `[data-testid=foo]`).
        url: Optional starting URL — if set, ran via `goto` before the
            first step. Convenience for the common case.
        headless: Run browser headless. Default True.
        init_script: Same as in qa_run — runs in every new page BEFORE
            any page-side script. Use for pre-seeding auth.
        http_credentials: `{"username": "...", "password": "..."}` for
            Basic-auth challenges across navigation/fetch/EventSource.
        trace: Record a Playwright trace.zip to <screenshots_dir>/.
        continue_on_fail: If True, keep running every step regardless
            of failures (useful for collecting all assertion failures
            in one run instead of stopping at the first).

    Returns:
        dict with keys: status, description, steps, elapsed, tagged=True,
        confidence (1.0 on clean PASS, 0.0 on any FAIL), screenshots,
        screenshots_dir, console_errors, network_errors, flicker_events,
        trace_path, console_log_path/network_log_path/flicker_log_path,
        step_results (list of per-step verdicts).
    """
    cli_args: list[str] = ["--tagged", "/dev/stdin", "-v"]  # placeholder
    # We need the steps as a tempfile because --tagged takes a path.
    fd, sp = tempfile.mkstemp(suffix=".tagged", prefix="qa_steps_",
                              dir=str(REPO_DIR))
    try:
        with open(fd, "w", encoding="utf-8") as f:
            f.write(steps)
        cli_args = ["--tagged", sp, "-v"]
        if headless:
            cli_args.append("--headless")
        if url:
            cli_args += ["--url", url]
        if trace:
            cli_args.append("--trace")
        if continue_on_fail:
            cli_args.append("--continue-on-fail")
        if http_credentials:
            u = http_credentials.get("username", "")
            p = http_credentials.get("password", "")
            if not u:
                return {
                    "status": "ERROR",
                    "description": "http_credentials needs `username` and `password`",
                    "steps": 0, "elapsed": 0.0, "log": "",
                }
            cli_args += ["--http-creds", f"{u}:{p}"]
        # init_script via tempfile (same pattern as qa_run).
        init_path: str | None = None
        if init_script is not None:
            ifd, init_path = tempfile.mkstemp(
                suffix=".js", prefix="qa_init_", dir=str(REPO_DIR),
            )
            with open(ifd, "w", encoding="utf-8") as f:
                f.write(init_script)
            cli_args += ["--init-script", init_path]
        try:
            # Step count drives the timeout; tagged steps are fast
            # (~50–500ms each except wait/goto). 60s base + 5s per step.
            step_count = max(1, sum(1 for line in steps.splitlines()
                                    if line.strip()
                                    and not line.strip().startswith("#")))
            timeout = 60.0 + step_count * 5.0
            return _run_cli(cli_args, timeout=timeout)
        finally:
            if init_path:
                try:
                    Path(init_path).unlink()
                except OSError:
                    pass
    finally:
        try:
            Path(sp).unlink()
        except OSError:
            pass


@mcp.tool()
def qa_setup_metamask(headless: bool = True) -> dict:
    """One-time MetaMask wallet setup with a test seed phrase.

    Creates a persistent browser profile with MetaMask unlocked and ready.
    Safe to re-run; will recreate the wallet if the profile is missing.

    Args:
        headless: Run browser headless. Default True.

    Returns:
        dict with keys: status, description, steps, elapsed, log.
    """
    if not qa_agent.METAMASK_EXT.exists():
        return {
            "status": "ERROR",
            "description": (
                f"MetaMask extension not found at {qa_agent.METAMASK_EXT}. "
                "Download v13.24.0 from github.com/MetaMask/metamask-extension/releases"
            ),
            "steps": 0,
            "elapsed": 0.0,
            "log": "",
        }

    cli_args = ["--setup-metamask", "-v"]
    if headless:
        cli_args.append("--headless")

    # Seed-phrase onboarding is slow — budget ~4 minutes.
    return _run_cli(cli_args, timeout=300.0)


@mcp.tool()
def qa_status() -> dict:
    """Check qa-browser-agent environment: OAuth credentials, MetaMask extension, browser profile."""
    # _load_credentials lives in the gitignored qa_agent.oauth subpackage
    # — only meaningful when LLM_PROVIDER=subscription. For env-key
    # providers (anthropic / openrouter) the function is absent, so we
    # treat its absence as "n/a" rather than crashing the tool.
    has_creds: bool | None = None
    try:
        from qa_agent.oauth import _load_credentials  # type: ignore
        creds = _load_credentials()
        has_creds = creds is not None and bool(creds.get("accessToken"))
    except ImportError:
        has_creds = None

    if has_creds is None:
        oauth_status = "n/a (env-key provider)"
    elif has_creds:
        oauth_status = "present"
    else:
        oauth_status = "missing (run: python -m qa_agent --login)"

    mm_installed = qa_agent.METAMASK_EXT.exists()
    profile_exists = qa_agent.PROFILE_DIR.exists()
    return {
        "oauth_credentials": oauth_status,
        "metamask_extension": (
            str(qa_agent.METAMASK_EXT) if mm_installed else "missing"
        ),
        "browser_profile": (
            str(qa_agent.PROFILE_DIR) if profile_exists else "missing"
        ),
        "model": qa_agent.MODEL,
        "provider": os.environ.get("LLM_PROVIDER", "anthropic"),
    }


if __name__ == "__main__":
    mcp.run()
