"""LLM curation pass — name candidates, label parameter slots, gate
weak ones.

The miner's symbolic side finds frequent contiguous N-grams and
infers parameter positions. The LLM's job here is purely **semantic**:

  1. Give the candidate a short snake_case name (`marketplace_search`).
  2. Write a one-sentence description.
  3. Name each parameter slot the inference pass found
     (`param_0_1` → `query`).
  4. Sanity gate: is this a coherent skill or coincidental
     co-occurrence?

The LLM does NOT decide:
  * which steps are in the macro (mining did)
  * which args are parameters (inference did)
  * whether the macro will replay correctly (validation does)

Output is a `CuratedMacro` dataclass; if the LLM rejects (or the call
fails), returns None and the caller drops the candidate.

Provider auth is whatever is in the env — same as the agent loop.
Token cost: one small request per candidate; ~200 tokens in,
~100 out. Negligible against the run-time savings.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from ..library import _NAME_RE
from .inference import InferredSlots
from .loader import Trace
from .mining import NGram


_SYS_PROMPT = (
    "You are labelling a candidate macro discovered by an offline "
    "trace miner. Reply with JSON only — no prose, no markdown fences. "
    "Schema: {\"name\":<snake_case identifier>, "
    "\"description\":<one short sentence>, "
    "\"params\":[{\"step_idx\":N,\"arg_idx\":N,\"name\":<snake_case>}], "
    "\"keep\":<true|false>}. "
    "Set keep=false if the steps look like a coincidence rather than a "
    "coherent skill (e.g. unrelated clicks, debugging spam). "
    "params MUST cover every (step_idx, arg_idx) the user lists; do "
    "not invent additional ones."
)


def _format_user_msg(
    ngram: NGram,
    slots: InferredSlots,
    traces: list[Trace],
) -> str:
    """Build the user-side prompt: the candidate steps, the inferred
    param positions, and a sample of the page contexts they ran in."""
    lines: list[str] = []
    lines.append("CANDIDATE STEPS:")
    for i, item in enumerate(ngram.pattern):
        lines.append(f"  step {i}: verb={item.verb} on {item.classifier}")
    lines.append("")
    lines.append(f"OBSERVED IN {ngram.support} distinct runs.")
    lines.append("")

    if slots.params:
        lines.append("PARAMETER SLOTS (variable args across runs):")
        for p in slots.params:
            sample = ", ".join(repr(v) for v in p.distinct_values[:3])
            more = (
                f" ... +{len(p.distinct_values) - 3} more"
                if len(p.distinct_values) > 3 else ""
            )
            lines.append(
                f"  step {p.step_idx} arg {p.arg_idx}: type={p.proposed_type} "
                f"observed values: [{sample}{more}]"
            )
        lines.append("")
    else:
        lines.append("PARAMETER SLOTS: none (all args fixed across runs)")
        lines.append("")

    if slots.concrete:
        lines.append("FIXED ARGS (same across all runs — for context):")
        for c in slots.concrete[:8]:
            v = c.value if len(c.value) < 60 else c.value[:60] + "..."
            lines.append(f"  step {c.step_idx} arg {c.arg_idx}: {v!r}")
        if len(slots.concrete) > 8:
            lines.append(f"  ... +{len(slots.concrete) - 8} more")
        lines.append("")

    # Sample 1-2 example URLs for context — helps the LLM tell whether
    # the candidate is, say, a marketplace flow vs. a settings dialog.
    sample_urls: list[str] = []
    seen: set[str] = set()
    for occ in ngram.occurrences[:5]:
        trace = traces[occ.seq_id]
        for s in trace.steps:
            if s.page_url and s.page_url not in seen:
                seen.add(s.page_url)
                sample_urls.append(s.page_url)
                break
        if len(sample_urls) >= 3:
            break
    if sample_urls:
        lines.append("SAMPLE PAGE URLS where this ran:")
        for u in sample_urls:
            lines.append(f"  {u}")
        lines.append("")

    lines.append("Reply with JSON matching the schema above. JSON only.")
    return "\n".join(lines)


@dataclass
class CuratedMacro:
    """LLM-blessed candidate ready for the emit step."""
    name: str
    description: str
    pattern: tuple = ()                            # the underlying NGram pattern
    slots: InferredSlots | None = None             # fixed args + parameters
    param_names: dict[tuple[int, int], str] = field(default_factory=dict)
    keep: bool = True
    raw_llm_response: str = ""


def _auto_name(ngram: NGram) -> str:
    """Fallback name when --no-curate is set: synthesises something
    readable like `click_button_then_press_enter`."""
    parts: list[str] = []
    for item in ngram.pattern[:4]:
        parts.append(f"{item.verb}_{item.classifier}")
    name = "_".join(parts)
    name = re.sub(r"[^a-zA-Z0-9_]", "_", name).lower()
    name = re.sub(r"_+", "_", name).strip("_") or "macro"
    if not _NAME_RE.match(name):
        name = "macro_" + name
    return name[:60]


def _curate_offline(
    ngram: NGram, slots: InferredSlots,
) -> CuratedMacro:
    """Synthesise a CuratedMacro without an LLM — used by --no-curate."""
    base = _auto_name(ngram)
    param_names: dict[tuple[int, int], str] = {}
    for p in slots.params:
        # Generic name based on verb context: type-into-textbox -> "text",
        # goto -> "url", evaluate -> "expr", otherwise "param_S_A".
        if p.verb == "type":
            name = "text"
        elif p.verb == "goto":
            name = "url"
        elif p.verb == "evaluate":
            name = "expr"
        else:
            name = f"param_{p.step_idx}_{p.arg_idx}"
        # Disambiguate collisions.
        if name in param_names.values():
            name = f"{name}_{p.step_idx}"
        param_names[(p.step_idx, p.arg_idx)] = name
    return CuratedMacro(
        name=base,
        description=f"auto-mined from {ngram.support} runs",
        pattern=ngram.pattern,
        slots=slots,
        param_names=param_names,
        keep=True,
        raw_llm_response="<offline>",
    )


def _parse_llm_json(text: str) -> dict | None:
    """Parse the LLM reply. Tolerates fences / leading prose by
    finding the first {...} block."""
    text = text.strip()
    if not text:
        return None
    # Strip trivial markdown fences if present.
    fence = re.match(r"^```(?:json)?\s*\n(.*?)\n```\s*$", text, re.DOTALL)
    if fence:
        text = fence.group(1).strip()
    # Find first balanced JSON object.
    start = text.find("{")
    if start < 0:
        return None
    try:
        return json.loads(text[start:])
    except json.JSONDecodeError:
        # Try greedy back-trim — sometimes there's trailing junk.
        end = text.rfind("}")
        if end > start:
            try:
                return json.loads(text[start:end + 1])
            except json.JSONDecodeError:
                return None
        return None


def _validate_curator_response(
    parsed: dict, slots: InferredSlots,
) -> tuple[str, str, dict[tuple[int, int], str], bool] | None:
    """Vet the LLM response. Returns (name, description, param_names, keep)
    or None on validation failure (caller drops the candidate)."""
    name = parsed.get("name")
    if not isinstance(name, str) or not _NAME_RE.match(name):
        return None
    description = str(parsed.get("description", ""))[:200]
    keep = bool(parsed.get("keep", True))

    raw_params = parsed.get("params") or []
    if not isinstance(raw_params, list):
        return None
    param_names: dict[tuple[int, int], str] = {}
    for entry in raw_params:
        if not isinstance(entry, dict):
            return None
        si = entry.get("step_idx")
        ai = entry.get("arg_idx")
        nm = entry.get("name")
        if not isinstance(si, int) or not isinstance(ai, int):
            return None
        if not isinstance(nm, str) or not _NAME_RE.match(nm):
            return None
        param_names[(si, ai)] = nm

    # Cross-check the LLM hit every slot the inference pass found.
    expected = {(p.step_idx, p.arg_idx) for p in slots.params}
    if set(param_names) != expected:
        return None

    return name, description, param_names, keep


def curate(
    ngram: NGram,
    slots: InferredSlots,
    traces: list[Trace],
    *,
    use_llm: bool = True,
) -> CuratedMacro | None:
    """Run the curation step.

    use_llm=False → synthesise everything offline (auto-name, generic
    param names, always keep). Useful for first-pass debugging without
    paying for tokens.

    Returns None if the LLM rejected the candidate or its response
    failed validation; caller drops the candidate.
    """
    if not use_llm:
        return _curate_offline(ngram, slots)

    # Lazy import — keeps `python -m qa_agent.macros.miner --help` fast
    # and avoids importing the LLM provider when --no-curate.
    from ...llm import ask_llm

    user_msg = _format_user_msg(ngram, slots, traces)
    try:
        text, _, _ = ask_llm(
            access_token="",
            messages=[{"role": "user", "content": user_msg}],
            system=_SYS_PROMPT,
        )
    except Exception as e:
        # LLM unavailable / rate-limited — fall back to offline curation
        # rather than dropping the candidate entirely.
        offline = _curate_offline(ngram, slots)
        offline.raw_llm_response = f"<llm error: {type(e).__name__}: {e}>"
        return offline

    parsed = _parse_llm_json(text)
    if parsed is None:
        return None
    validated = _validate_curator_response(parsed, slots)
    if validated is None:
        return None
    name, description, param_names, keep = validated
    if not keep:
        return CuratedMacro(
            name=name, description=description,
            pattern=ngram.pattern, slots=slots,
            param_names=param_names, keep=False,
            raw_llm_response=text,
        )
    return CuratedMacro(
        name=name, description=description,
        pattern=ngram.pattern, slots=slots,
        param_names=param_names, keep=True,
        raw_llm_response=text,
    )
