"""Command-line interface: argparse + dispatch to metamask/run_task.

Auth: pick a provider via `LLM_PROVIDER` env + that provider's API-key
env (`ANTHROPIC_API_KEY` / `OPENROUTER_API_KEY`). See README.
"""

import argparse
import json
import sys
import time

from . import config
from .agent import run_task
from .config import DEFAULT_MAX_STEPS, METAMASK_EXT, MODEL
from .metamask import setup_metamask


def _emit_json(stream, payload: dict) -> None:
    """Write a single JSON line + newline to the given stream and flush."""
    stream.write(json.dumps(payload) + "\n")
    stream.flush()


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="qa_agent",
        description="QA browser agent — LLM-driven testing via Playwright",
        epilog=(
            "Examples:\n"
            '  python -m qa_agent "test login at http://localhost:3000"\n'
            '  python -m qa_agent --extension ~/ext/metamask "swap ETH on Uniswap"\n'
            "  python -m qa_agent --setup-metamask               # auto-setup test wallet\n"
            '  python -m qa_agent --metamask "connect wallet on https://app.uniswap.org"\n'
            "\n"
            "LLM auth: export ANTHROPIC_API_KEY (default) or LLM_PROVIDER=openrouter\n"
            "          + OPENROUTER_API_KEY. Optional LLM_MODEL to override the default."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("task", nargs="?", help="QA task in natural language")
    parser.add_argument("--url", help="Starting URL (auto-detected from task if omitted)")
    parser.add_argument("--setup-metamask", action="store_true",
                        help="Setup MetaMask with test seed")
    parser.add_argument("--metamask", action="store_true",
                        help="Run with MetaMask extension loaded")
    parser.add_argument("--extension", action="append", default=[],
                        help="Path to unpacked extension (repeatable)")
    parser.add_argument("--headless", action="store_true",
                        help="Headless browser (default: headed)")
    parser.add_argument("-v", "--verbose", action="store_true", help="Detailed step output")
    parser.add_argument("--max-steps", type=int, default=DEFAULT_MAX_STEPS,
                        help=f"Max steps (default: {DEFAULT_MAX_STEPS})")
    parser.add_argument("--model", default=MODEL, help=f"Model (default: {MODEL})")
    parser.add_argument("--init-script",
                        help="Path to a JS file injected via Playwright "
                             "add_init_script before any navigation. Useful "
                             "for pre-seeding localStorage with an auth "
                             "session to skip the login UI.")
    parser.add_argument("--json-result", action="store_true",
                        help="Emit a JSON result line to stdout; route logs to stderr "
                             "(used by the MCP wrapper)")

    args = parser.parse_args()

    # MCP mode: reroute all prints to stderr so they can't pollute the JSON-RPC
    # stdout that the MCP host reads. The final JSON line is written to the
    # preserved original stdout at the end.
    original_stdout = sys.stdout
    if args.json_result:
        sys.stdout = sys.stderr

    if args.setup_metamask:
        t_start = time.time()
        try:
            status = setup_metamask(headless=args.headless, verbose=args.verbose)
        except Exception as e:
            if args.json_result:
                _emit_json(original_stdout, {
                    "status": "ERROR",
                    "description": f"{type(e).__name__}: {e}",
                    "steps": 0,
                    "elapsed": round(time.time() - t_start, 1),
                })
            raise
        if args.json_result:
            _emit_json(original_stdout, {
                "status": status or "UNKNOWN",
                "description": (
                    "MetaMask wallet ready" if status == "PASS" else "setup failed"
                ),
                "steps": 0,
                "elapsed": round(time.time() - t_start, 1),
            })
        sys.exit(0 if status == "PASS" else 1)

    if not args.task:
        parser.print_help()
        sys.exit(1)

    # Override model at config level so llm.py picks it up
    config.MODEL = args.model

    extensions = list(args.extension)
    if args.metamask:
        if not METAMASK_EXT.exists():
            msg = f"MetaMask not found at {METAMASK_EXT}. Run --setup-metamask first."
            print(msg, file=sys.stderr)
            if args.json_result:
                _emit_json(original_stdout, {
                    "status": "ERROR",
                    "description": msg,
                    "steps": 0,
                    "elapsed": 0.0,
                })
            sys.exit(1)
        extensions.append(str(METAMASK_EXT))

    init_script_src: str | None = None
    if args.init_script:
        try:
            with open(args.init_script, "r") as f:
                init_script_src = f.read()
        except OSError as e:
            msg = f"Cannot read --init-script {args.init_script}: {e}"
            print(msg, file=sys.stderr)
            if args.json_result:
                _emit_json(original_stdout, {
                    "status": "ERROR",
                    "description": msg,
                    "steps": 0,
                    "elapsed": 0.0,
                })
            sys.exit(1)

    print(f"QA Agent: {args.task}")
    ext_info = f" | Extensions: {len(extensions)}" if extensions else ""
    init_info = " | init-script: yes" if init_script_src else ""
    import os
    provider = os.environ.get("LLM_PROVIDER", "anthropic")
    print(f"  Model: {args.model} | Provider: {provider}{ext_info}{init_info}")

    t_start = time.time()
    # Stash the diagnostics summary captured by on_finish so we can fold
    # screenshots / console-error / network-error / flicker counts into
    # the JSON line emitted to MCP hosts.
    finish_summary: dict = {}

    def _capture_finish(rec: dict) -> None:
        finish_summary.update(rec)

    try:
        status, description, steps_used = run_task(
            args.task, args.url, args.headless, args.verbose,
            args.max_steps, extensions or None,
            init_script=init_script_src,
            on_finish=_capture_finish,
        )
    except Exception as e:
        if args.json_result:
            _emit_json(original_stdout, {
                "status": "ERROR",
                "description": f"{type(e).__name__}: {e}",
                "steps": 0,
                "elapsed": round(time.time() - t_start, 1),
            })
        raise

    if args.json_result:
        _emit_json(original_stdout, {
            "status": status,
            "description": description,
            "steps": steps_used,
            "elapsed": round(time.time() - t_start, 1),
            "screenshots": finish_summary.get("screenshots", []),
            "console_errors": finish_summary.get("console_errors", 0),
            "network_errors": finish_summary.get("network_errors", 0),
            "flicker_events": finish_summary.get("flicker_events", 0),
        })
    sys.exit(0 if status == "PASS" else 1)
