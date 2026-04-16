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
          "args": ["mcp_server.py"]
        }
      }
    }
"""

import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path

# Allow importing qa_agent from this directory for status checks
sys.path.insert(0, str(Path(__file__).parent))

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
    max_steps: int = 30,
    metamask: bool = False,
    extensions: list[str] | None = None,
    init_script: str | None = None,
) -> dict:
    """Run a browser QA task. Claude Haiku drives Playwright to test web apps.

    Args:
        task: Natural language description of what to test.
        url: Starting URL (auto-detected from task if omitted).
        headless: Run browser headless. Default True.
        max_steps: Maximum agent steps before timeout. Default 30.
        metamask: Load bundled MetaMask extension (requires prior setup).
        extensions: Paths to additional unpacked extensions.
        init_script: Optional JavaScript source injected via Playwright
            add_init_script before any navigation. Useful for pre-seeding
            localStorage/sessionStorage with an auth session so the agent
            can skip the login UI.

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
    creds = qa_agent._load_credentials()
    has_creds = creds is not None and bool(creds.get("accessToken"))
    mm_installed = qa_agent.METAMASK_EXT.exists()
    profile_exists = qa_agent.PROFILE_DIR.exists()
    return {
        "oauth_credentials": (
            "present" if has_creds else "missing (run: python -m qa_agent --login)"
        ),
        "metamask_extension": (
            str(qa_agent.METAMASK_EXT) if mm_installed else "missing"
        ),
        "browser_profile": (
            str(qa_agent.PROFILE_DIR) if profile_exists else "missing"
        ),
        "model": qa_agent.MODEL,
    }


if __name__ == "__main__":
    mcp.run()
