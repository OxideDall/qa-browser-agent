"""LLM judge for open-ended (L6) fixtures.

Calls Sonnet with the fixture's task + the agent's run transcript +
(optionally) the final page screenshot. Returns a structured verdict.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

# Project root must be on sys.path before this module's own imports succeed.
import sys
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from qa_agent.llm import ask_llm  # noqa: E402
from qa_agent.oauth import _get_access_token  # noqa: E402

JUDGE_MODEL = "claude-sonnet-4-6"
JUDGE_MAX_TOKENS = 1024

JUDGE_SYSTEM = """You are an impartial QA judge. You are shown:

1. A task description that was given to a browser-automation agent.
2. The agent's full step-by-step transcript (one JSON record per step,
   plus a final result record).
3. Optionally a final-state screenshot of the page the agent ended on.

Your job: decide whether the agent semantically completed the task.

Rubric:
- Did the agent reach the requested end-state? (most important)
- Was the final `done PASS` description supported by concrete evidence
  (quoted UI text, tx hash, etc.) — not vague claims like "completed"?
- Did the agent use a reasonable number of steps without burning the
  whole budget on loops or vision retries?
- Were there blocked actions (MetaMask popup escapes), forced FAILs,
  or hard-loop terminations? Those generally indicate failure.

Return STRICT JSON only, no markdown, with this exact shape:

{"verdict": "PASS" | "FAIL",
 "score": 1 | 2 | 3 | 4 | 5,
 "reasoning": "<one short paragraph>",
 "evidence_cited": "<the agent's final done-PASS description verbatim, or null>"}

Score scale:
  5 = clean PASS, minimal steps, strong evidence
  4 = PASS but inefficient (3-5x over optimal)
  3 = borderline; agent claimed done but evidence weak or partial completion
  2 = clear miss but no crash
  1 = crashed, looped, or invented success without evidence
"""


def _summarize_transcript(steps: list[dict], result: dict | None) -> str:
    """Produce a compact text version of the agent's run for the judge."""
    lines = []
    for s in steps:
        action = s.get("action") or "?"
        args = s.get("args") or []
        flags = []
        if s.get("loop_hit"):
            flags.append(f"loop={s['loop_hit']}")
        if s.get("blocked"):
            flags.append(f"blocked={s['blocked']}")
        if s.get("done_reasked"):
            flags.append("done_reasked")
        if s.get("vision"):
            flags.append("vision")
        flag_s = (" [" + ",".join(flags) + "]") if flags else ""
        result_s = (s.get("result") or "")[:120]
        args_s = " ".join(str(a)[:40] for a in args)
        lines.append(
            f"step {s['step']:>2}: {action} {args_s}{flag_s} → {result_s}"
        )
    if result:
        lines.append("")
        lines.append(
            f"FINAL: status={result.get('status')!r} "
            f"description={result.get('description')!r}  "
            f"steps={result.get('steps_used')} "
            f"tokens={result.get('total_in')}+{result.get('total_out')} "
            f"wall={result.get('wall_seconds'):.1f}s"
        )
    return "\n".join(lines)


def judge_run(task: str, run_log_path: Path,
              screenshot_b64: str | None = None) -> dict[str, Any]:
    """Read run JSONL, ask the judge, return verdict dict."""
    steps: list[dict] = []
    result: dict | None = None
    for line in run_log_path.read_text().splitlines():
        try:
            rec = json.loads(line)
        except Exception:
            continue
        if rec.get("t") == "step":
            steps.append(rec)
        elif rec.get("t") == "result":
            result = rec

    transcript = _summarize_transcript(steps, result)
    user_msg = (
        f"## Task given to the agent\n\n{task}\n\n"
        f"## Transcript\n\n{transcript}\n\n"
        "## Decision\n\n"
        "Return the JSON verdict now."
    )

    token = _get_access_token()
    text, in_tok, out_tok = ask_llm(
        token,
        messages=[{"role": "user", "content": user_msg}],
        system=JUDGE_SYSTEM,
        image_b64=screenshot_b64,
        model=JUDGE_MODEL,
        max_tokens=JUDGE_MAX_TOKENS,
    )

    verdict = _parse_verdict(text)
    verdict["_judge_in_tokens"] = in_tok
    verdict["_judge_out_tokens"] = out_tok
    verdict["_judge_raw"] = text
    return verdict


def _parse_verdict(text: str) -> dict[str, Any]:
    """Tolerantly extract the JSON object from the judge response."""
    s = text.strip()
    # Strip code fences if Sonnet wrapped despite instructions.
    s = re.sub(r"^```(?:json)?\s*", "", s)
    s = re.sub(r"\s*```$", "", s)
    try:
        return json.loads(s)
    except Exception:
        # Find the first {...} block
        m = re.search(r"\{[^{}]*\}", s, flags=re.DOTALL)
        if m:
            try:
                return json.loads(m.group(0))
            except Exception:
                pass
    return {
        "verdict": "FAIL",
        "score": 1,
        "reasoning": f"judge response unparseable: {text[:200]!r}",
        "evidence_cited": None,
    }


def main(argv: list[str] | None = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(prog="bench.runner.judge")
    ap.add_argument("--task", required=True, help="path to fixture's task.txt")
    ap.add_argument("--log", required=True, help="path to run JSONL")
    args = ap.parse_args(argv)

    task = Path(args.task).read_text().strip()
    verdict = judge_run(task, Path(args.log))
    print(json.dumps(verdict, ensure_ascii=False, indent=2))
    return 0 if verdict.get("verdict") == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
