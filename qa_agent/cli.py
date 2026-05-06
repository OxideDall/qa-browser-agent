"""Command-line interface: argparse + dispatch to metamask/run_task.

Auth: pick a provider via `LLM_PROVIDER` env + that provider's API-key
env (`ANTHROPIC_API_KEY` / `OPENROUTER_API_KEY`). See README.
"""

import argparse
import json
import sys
import time

from . import config
from .agent import run_macro_task, run_tagged_task, run_task
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
                             "context.add_init_script. Runs once in every "
                             "new page in this BrowserContext, BEFORE any "
                             "page-side script — including the SPA bundle "
                             "and inline <script> tags — i.e. as the very "
                             "first thing the page sees. Useful for "
                             "pre-seeding localStorage / sessionStorage / "
                             "cookies with an auth session, monkey-patching "
                             "fetch, etc.")
    parser.add_argument("--json-result", action="store_true",
                        help="Emit a JSON result line to stdout; route logs to stderr "
                             "(used by the MCP wrapper)")
    parser.add_argument("--http-creds",
                        help="Basic-auth credentials for the entire "
                             "BrowserContext, format `user:pass`. Forwarded "
                             "to Playwright's http_credentials kwarg — "
                             "resolves Basic-auth challenges on every "
                             "navigation/fetch/EventSource transparently.")
    parser.add_argument("--trace", action="store_true",
                        help="Record a Playwright trace (DOM snapshots, "
                             "screenshots, network) to <screenshots_dir>/"
                             "trace.zip. Open with `playwright show-trace "
                             "<path>` for time-travel debugging. ~5–15MB "
                             "per run.")
    parser.add_argument("--show-browser", action="store_true",
                        help="Headed mode + pause before close so you can "
                             "inspect the live browser. Implies --headless "
                             "off. Blocks on stdin until Enter; safe for "
                             "interactive sessions, NOT for CI.")
    parser.add_argument("--tagged",
                        help="Path to a tagged-DSL steps file. Runs the "
                             "deterministic, LLM-less assertion loop "
                             "(qa_agent.tagged). Mutually exclusive with "
                             "the natural-language `task` positional.")
    parser.add_argument("--macro",
                        help="Name of an installed macro to invoke. "
                             "Resolved against ~/.config/qa_agent/macros/ "
                             "(or QA_MACROS_DIR). Compiled to tagged DSL "
                             "with --param substitution and dispatched "
                             "via run_macro_task. Mutually exclusive with "
                             "the natural-language task and --tagged.")
    parser.add_argument("--param", action="append", default=[],
                        help="Macro parameter, format `key=value`. "
                             "Repeatable. Required for any macro param "
                             "marked `required`. See `--list-macros`.")
    parser.add_argument("--list-macros", action="store_true",
                        help="Print installed macros (name, version, "
                             "support, success_rate, description) and exit.")
    parser.add_argument("--validate-macro",
                        help="Live-validate the named macro: load, "
                             "compile with sample params from "
                             "meta.examples (or --param overrides), "
                             "replay against a real browser, report "
                             "verdict. Mutually exclusive with task / "
                             "--tagged / --macro.")
    parser.add_argument("--continue-on-fail", action="store_true",
                        help="Tagged / macro mode only: keep running after "
                             "a step fails (default: stop on first FAIL).")

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

    if args.list_macros:
        from .macros import list_macros
        rows = list_macros()
        if not rows:
            print("(no macros installed at ~/.config/qa_agent/macros/)")
        else:
            for r in rows:
                if "error" in r:
                    print(f"  ! {r['name']}: {r['error']}")
                    continue
                print(
                    f"  {r['name']:<32}  v{r['version']}  "
                    f"params={r['n_params']}  support={r['support_count']}  "
                    f"sr={r['success_rate']:.2f}  {r['description'][:50]}"
                )
        sys.exit(0)

    if not args.task and not args.tagged and not args.macro and not args.validate_macro:
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

    http_creds: dict | None = None
    if args.http_creds:
        if ":" not in args.http_creds:
            msg = (
                "--http-creds must be `user:pass` (got: no colon). "
                "Use --help for details."
            )
            print(msg, file=sys.stderr)
            if args.json_result:
                _emit_json(original_stdout, {
                    "status": "ERROR", "description": msg,
                    "steps": 0, "elapsed": 0.0,
                })
            sys.exit(1)
        u, _, p = args.http_creds.partition(":")
        http_creds = {"username": u, "password": p}

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

    # Shared --show-browser hook used by both LLM and tagged paths.
    def _show_browser_pause(_page, _ctx) -> None:
        print(
            "[--show-browser] press Enter in this terminal to "
            "close the browser and exit...", file=sys.stderr,
        )
        try:
            input()
        except (KeyboardInterrupt, EOFError):
            pass

    headless_eff = False if args.show_browser else args.headless

    # Validate-macro mode: load + compile + live-replay + report. No
    # task / --tagged / --macro coexists; this is its own short-circuit.
    if args.validate_macro:
        if args.tagged or args.task or args.macro:
            print(
                "--validate-macro is mutually exclusive with --tagged / "
                "--macro / a natural-language task",
                file=sys.stderr,
            )
            sys.exit(2)

        from .macros import live_validate, load_macro

        param_overrides: dict[str, str] = {}
        for raw in args.param:
            if "=" in raw:
                k, _, v = raw.partition("=")
                param_overrides[k] = v

        try:
            macro = load_macro(args.validate_macro)
        except Exception as e:
            msg = (
                f"--validate-macro {args.validate_macro!r}: "
                f"{type(e).__name__}: {e}"
            )
            print(msg, file=sys.stderr)
            if args.json_result:
                _emit_json(original_stdout, {
                    "status": "ERROR", "description": msg,
                    "steps": 0, "elapsed": 0.0,
                })
            sys.exit(1)
        try:
            result = live_validate(
                macro,
                params=param_overrides or None,
                headless=headless_eff,
                http_credentials=http_creds,
                trace=args.trace,
            )
        except Exception as e:
            msg = f"live_validate failed: {type(e).__name__}: {e}"
            print(msg, file=sys.stderr)
            if args.json_result:
                _emit_json(original_stdout, {
                    "status": "ERROR", "description": msg,
                    "steps": 0, "elapsed": 0.0,
                })
            sys.exit(1)

        verdict = "PASS" if result.passed else result.status
        if not args.json_result:
            print(f"[validate-macro] {result.macro_name}: {verdict}")
            print(f"  params used: {result.params_used}")
            print(f"  score: {result.n_passed}/{result.n_steps} "
                  f"({result.score:.2f})")
            if result.failed_step is not None:
                print(f"  failed at step {result.failed_step}: "
                      f"{result.failed_message}")
        else:
            _emit_json(original_stdout, {
                "status": result.status,
                "description": result.description,
                "steps": result.n_steps,
                "elapsed": round(result.elapsed, 1),
                "validate_macro": True,
                "macro": result.macro_name,
                "params_used": result.params_used,
                "passed": result.passed,
                "score": result.score,
                "failed_step": result.failed_step,
                "failed_message": result.failed_message,
                "confidence": result.confidence,
                "screenshots_dir": result.screenshots_dir,
                "step_results": result.step_results,
            })
        sys.exit(0 if result.passed else 1)

    # Macro mode: load + compile + dispatch via run_macro_task. The
    # macro name and its params come from --macro / --param; URL is
    # picked from meta.preconditions.url_templates if --url isn't set.
    if args.macro:
        if args.tagged or args.task:
            print(
                "--macro is mutually exclusive with --tagged / a "
                "natural-language task", file=sys.stderr,
            )
            sys.exit(2)

        params: dict[str, str] = {}
        for raw in args.param:
            if "=" not in raw:
                msg = f"--param must be `key=value`, got {raw!r}"
                print(msg, file=sys.stderr)
                if args.json_result:
                    _emit_json(original_stdout, {
                        "status": "ERROR", "description": msg,
                        "steps": 0, "elapsed": 0.0,
                    })
                sys.exit(1)
            k, _, v = raw.partition("=")
            params[k] = v

        macro_summary: dict = {}
        t_macro_start = time.time()
        print(f"QA Agent: macro {args.macro} {params}")
        try:
            status, description, steps_used = run_macro_task(
                args.macro, params,
                url=args.url,
                headless=headless_eff,
                verbose=args.verbose,
                init_script=init_script_src,
                http_credentials=http_creds,
                trace=args.trace,
                continue_on_fail=args.continue_on_fail,
                on_finish=lambda rec: macro_summary.update(rec),
                before_close=(_show_browser_pause if args.show_browser else None),
            )
        except Exception as e:
            if args.json_result:
                _emit_json(original_stdout, {
                    "status": "ERROR",
                    "description": f"{type(e).__name__}: {e}",
                    "steps": 0,
                    "elapsed": round(time.time() - t_macro_start, 1),
                })
            raise

        if args.json_result:
            _emit_json(original_stdout, {
                "status": status,
                "description": description,
                "steps": steps_used,
                "elapsed": round(time.time() - t_macro_start, 1),
                "macro": args.macro,
                "params": params,
                "tagged": True,
                "confidence": macro_summary.get("confidence"),
                "screenshots": macro_summary.get("screenshots", []),
                "screenshots_dir": macro_summary.get("screenshots_dir"),
                "console_errors": macro_summary.get("console_errors", 0),
                "network_errors": macro_summary.get("network_errors", 0),
                "flicker_events": macro_summary.get("flicker_events", 0),
                "console_log_path": macro_summary.get("console_log_path"),
                "network_log_path": macro_summary.get("network_log_path"),
                "flicker_log_path": macro_summary.get("flicker_log_path"),
                "trace_path": macro_summary.get("trace_path"),
                "step_results": macro_summary.get("step_results", []),
            })
        sys.exit(0 if status == "PASS" else 1)

    # Tagged mode: read steps file, dispatch to run_tagged_task. We
    # branch here so the rest of the CLI (LLM provider banner, model
    # override, etc.) is bypassed — tagged mode doesn't use any of it.
    if args.tagged:
        try:
            with open(args.tagged, "r", encoding="utf-8") as f:
                steps_text = f.read()
        except OSError as e:
            msg = f"Cannot read --tagged {args.tagged}: {e}"
            print(msg, file=sys.stderr)
            if args.json_result:
                _emit_json(original_stdout, {
                    "status": "ERROR", "description": msg,
                    "steps": 0, "elapsed": 0.0,
                })
            sys.exit(1)
        tagged_summary: dict = {}
        t_tagged_start = time.time()
        print(f"QA Agent: tagged mode ({args.tagged})")
        try:
            status, description, steps_used = run_tagged_task(
                steps_text, url=args.url,
                headless=headless_eff,
                verbose=args.verbose,
                init_script=init_script_src,
                http_credentials=http_creds,
                trace=args.trace,
                continue_on_fail=args.continue_on_fail,
                on_finish=lambda rec: tagged_summary.update(rec),
                before_close=(_show_browser_pause if args.show_browser else None),
            )
        except Exception as e:
            if args.json_result:
                _emit_json(original_stdout, {
                    "status": "ERROR",
                    "description": f"{type(e).__name__}: {e}",
                    "steps": 0,
                    "elapsed": round(time.time() - t_tagged_start, 1),
                })
            raise
        if args.json_result:
            _emit_json(original_stdout, {
                "status": status,
                "description": description,
                "steps": steps_used,
                "elapsed": round(time.time() - t_tagged_start, 1),
                "tagged": True,
                "confidence": tagged_summary.get("confidence"),
                "screenshots": tagged_summary.get("screenshots", []),
                "screenshots_dir": tagged_summary.get("screenshots_dir"),
                "console_errors": tagged_summary.get("console_errors", 0),
                "network_errors": tagged_summary.get("network_errors", 0),
                "flicker_events": tagged_summary.get("flicker_events", 0),
                "console_log_path": tagged_summary.get("console_log_path"),
                "network_log_path": tagged_summary.get("network_log_path"),
                "flicker_log_path": tagged_summary.get("flicker_log_path"),
                "trace_path": tagged_summary.get("trace_path"),
                "step_results": tagged_summary.get("step_results", []),
            })
        sys.exit(0 if status == "PASS" else 1)

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
            args.task, args.url, headless_eff, args.verbose,
            args.max_steps, extensions or None,
            init_script=init_script_src,
            on_finish=_capture_finish,
            before_close=(_show_browser_pause if args.show_browser else None),
            http_credentials=http_creds,
            trace=args.trace,
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
            "confidence": finish_summary.get("confidence"),
            "uncertainty_reasons": finish_summary.get("uncertainty_reasons", []),
            "signals": finish_summary.get("signals", {}),
            "screenshots": finish_summary.get("screenshots", []),
            "screenshots_dir": finish_summary.get("screenshots_dir"),
            "console_errors": finish_summary.get("console_errors", 0),
            "network_errors": finish_summary.get("network_errors", 0),
            "flicker_events": finish_summary.get("flicker_events", 0),
            "console_log_path": finish_summary.get("console_log_path"),
            "network_log_path": finish_summary.get("network_log_path"),
            "flicker_log_path": finish_summary.get("flicker_log_path"),
            "done_reasks_log_path": finish_summary.get("done_reasks_log_path"),
            "done_reasks_log": finish_summary.get("done_reasks_log", []),
            "trace_path": finish_summary.get("trace_path"),
            "macro_detection": finish_summary.get("macro_detection"),
        })
    sys.exit(0 if status == "PASS" else 1)
