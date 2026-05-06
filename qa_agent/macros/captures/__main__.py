"""CLI: `python -m qa_agent.macros.captures <stats|list|gc>`.

  stats           — inventory size + counts by mode/status
  list [--mode] [--status] [--limit] — per-capture metadata
  gc --days N [--apply] [--keep-failed] — delete old captures

Defaults to the user's home dirs (`~/.config/qa_agent/captures/` and
`./qa_screenshots/`); both overridable via flags so bench / CI can
point at sandboxed locations.
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

from .api import compute_stats, gc_old_captures, list_captures_meta
from ...agent import CAPTURES_ROOT
from ...config import SCREENSHOT_DIR


def _humanize_bytes(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.1f}{unit}" if unit != "B" else f"{n}B"
        n /= 1024
    return f"{n:.1f}GB"


def _fmt_ts(t: float | None) -> str:
    if t is None:
        return "(none)"
    return datetime.fromtimestamp(t, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")


def _add_dir_args(ap: argparse.ArgumentParser) -> None:
    ap.add_argument(
        "--captures-dir",
        default=str(CAPTURES_ROOT),
        help=f"Captures root (default: {CAPTURES_ROOT})",
    )
    ap.add_argument(
        "--screenshots-dir",
        default=str(SCREENSHOT_DIR.resolve()),
        help=f"Screenshots root (default: {SCREENSHOT_DIR.resolve()})",
    )


def _cmd_stats(args: argparse.Namespace) -> int:
    cap = Path(args.captures_dir).expanduser()
    shots = Path(args.screenshots_dir).expanduser()
    s = compute_stats(cap, shots)
    print(f"captures dir : {cap}")
    print(f"screenshots  : {shots}")
    print(f"count        : {s.count}")
    print(f"by mode      : {dict(sorted(s.by_mode.items()))}")
    print(f"by status    : {dict(sorted(s.by_status.items()))}")
    print(f"capture size : {_humanize_bytes(s.capture_bytes)}")
    print(f"screenshots  : {_humanize_bytes(s.screenshots_bytes)}")
    print(f"total        : {_humanize_bytes(s.total_bytes)}")
    print(f"oldest mtime : {_fmt_ts(s.oldest_mtime)}")
    print(f"newest mtime : {_fmt_ts(s.newest_mtime)}")
    return 0


def _cmd_list(args: argparse.Namespace) -> int:
    cap = Path(args.captures_dir).expanduser()
    shots = Path(args.screenshots_dir).expanduser()
    metas = list_captures_meta(cap, shots)
    if args.mode:
        metas = [m for m in metas if m.mode == args.mode]
    if args.status:
        metas = [m for m in metas if m.final_status == args.status]
    if args.limit:
        metas = metas[-args.limit:]
    if not metas:
        print("(no captures match)")
        return 0
    print(
        f"{'run_id':<48}  {'mode':<7}  {'status':<7}  steps  "
        f"{'size':>9}  age"
    )
    now = datetime.now(timezone.utc).timestamp()
    for m in metas:
        age_d = (now - m.mtime) / 86400.0
        print(
            f"{m.run_id:<48}  {m.mode:<7}  "
            f"{(m.final_status or '?'):<7}  {m.n_steps:>5}  "
            f"{_humanize_bytes(m.total_bytes):>9}  {age_d:5.1f}d"
        )
    return 0


def _cmd_gc(args: argparse.Namespace) -> int:
    cap = Path(args.captures_dir).expanduser()
    shots = Path(args.screenshots_dir).expanduser()
    eligible, bytes_total = gc_old_captures(
        cap, shots,
        older_than_days=args.days,
        keep_failed=args.keep_failed,
        apply=args.apply,
    )
    verb = "deleted" if args.apply else "would delete"
    print(
        f"{verb} {len(eligible)} capture(s) older than {args.days} days, "
        f"freeing {_humanize_bytes(bytes_total)}"
    )
    if args.verbose:
        for m in eligible:
            print(f"  {m.run_id}  ({m.mode}, {m.final_status or '?'}, "
                  f"{_humanize_bytes(m.total_bytes)})")
    if not args.apply and eligible:
        print("(dry-run — re-run with --apply to actually delete)")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="qa_agent.macros.captures",
        description=(
            "Inspect and prune the per-run capture archive at "
            "~/.config/qa_agent/captures/. Captures grow without bound "
            "by default — run `gc` periodically (or wire it into a "
            "cron job) once you've mined what you need from them."
        ),
    )
    sub = ap.add_subparsers(dest="cmd", required=True)

    sp_stats = sub.add_parser("stats", help="Inventory size + counts")
    _add_dir_args(sp_stats)
    sp_stats.set_defaults(func=_cmd_stats)

    sp_list = sub.add_parser("list", help="Per-capture metadata")
    _add_dir_args(sp_list)
    sp_list.add_argument("--mode", choices=["llm", "tagged"])
    sp_list.add_argument("--status", choices=["PASS", "FAIL", "ERROR"])
    sp_list.add_argument("--limit", type=int, default=0,
                         help="Show only the most recent N (default: all)")
    sp_list.set_defaults(func=_cmd_list)

    sp_gc = sub.add_parser("gc", help="Delete old captures")
    _add_dir_args(sp_gc)
    sp_gc.add_argument(
        "--days", type=float, default=30.0,
        help="Cutoff age in days (default: 30). Captures older than "
             "(now - days) are eligible.",
    )
    sp_gc.add_argument(
        "--apply", action="store_true",
        help="Actually delete (default: dry-run, just report).",
    )
    sp_gc.add_argument(
        "--keep-failed", action="store_true",
        help="Don't delete FAIL/ERROR captures — useful for keeping "
             "debugging context around after pruning successful runs.",
    )
    sp_gc.add_argument(
        "-v", "--verbose", action="store_true",
        help="Print every eligible capture.",
    )
    sp_gc.set_defaults(func=_cmd_gc)

    args = ap.parse_args(argv)
    try:
        return args.func(args)
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
