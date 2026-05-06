"""Parameter inference — figure out which arg positions in a candidate
N-gram vary across runs (parameters) vs. stay constant (concrete).

For each step in the N-gram and each arg index in that step:

  * collect the raw arg values from every occurrence
  * if all collected values are identical → arg is concrete, embed
    it verbatim in the compiled tagged DSL
  * if they differ → it's a parameter candidate, name it later via
    the LLM curator (or auto-generate `param_<step>_<arg>` if
    --no-curate is set)

Output is a list of `ParamCandidate` rows, one per (step_idx, arg_idx)
that varied. The emitter uses this list to produce
`${param_name}` placeholders in the macro body and to populate
`meta.params`.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .loader import Trace, TraceStep
from .mining import NGram


@dataclass
class ParamCandidate:
    """One arg position in the N-gram that varies across runs."""
    step_idx: int           # 0-based position in the N-gram
    arg_idx: int            # 0-based arg slot
    verb: str
    role: str | None        # target role of the step (None for non-targeted verbs)
    distinct_values: list[str] = field(default_factory=list)
    proposed_type: str = "string"      # "string" / "int" / "url"

    @property
    def n_distinct(self) -> int:
        return len(self.distinct_values)


@dataclass
class ConcreteArgs:
    """Args at this step that *didn't* vary — fixed across all
    occurrences. Emitter inlines these into the tagged DSL."""
    step_idx: int
    arg_idx: int
    value: str


@dataclass
class InferredSlots:
    """Result of running inference over an NGram + its source traces."""
    params: list[ParamCandidate] = field(default_factory=list)
    concrete: list[ConcreteArgs] = field(default_factory=list)


def _looks_int(values: list[str]) -> bool:
    if not values:
        return False
    for v in values:
        try:
            int(v)
        except (TypeError, ValueError):
            return False
    return True


def _looks_url(values: list[str]) -> bool:
    if not values:
        return False
    for v in values:
        if not v or "://" not in v[:32]:
            return False
    return True


def _propose_type(values: list[str]) -> str:
    if _looks_int(values):
        return "int"
    if _looks_url(values):
        return "url"
    return "string"


def _step_at(trace: Trace, vocab_step_no: int) -> TraceStep | None:
    """The vocabulary item carries the ORIGINAL trace step_no it was
    derived from (vocab.py preserves it). Look the underlying
    TraceStep up by that number."""
    for s in trace.steps:
        if s.step_no == vocab_step_no:
            return s
    return None


def infer_params(
    ngram: NGram,
    sequences: list[list],          # list[VocabItem] per trace
    traces: list[Trace],
) -> InferredSlots:
    """Walk the N-gram's occurrences across all sequences. For each
    step + arg slot, collect the raw args (from the underlying
    TraceStep). Classify as parameter or concrete.

    `sequences[i]` corresponds to `traces[i]` — identical ordering.
    """
    if len(sequences) != len(traces):
        raise ValueError(
            f"sequences and traces must align: {len(sequences)} vs {len(traces)}"
        )

    n = ngram.length

    # Per-step, gather all arg-vectors observed across occurrences.
    # `args_at_step[step_idx]` is a list[list[str]], one row per occurrence.
    args_at_step: list[list[list[str]]] = [[] for _ in range(n)]

    for occ in ngram.occurrences:
        seq = sequences[occ.seq_id]
        trace = traces[occ.seq_id]
        for step_idx in range(n):
            vocab_item = seq[occ.start_idx + step_idx]
            tracestep = _step_at(trace, vocab_item.step_no)
            if tracestep is None:
                # Should not happen — vocab items come from this trace.
                args_at_step[step_idx].append([])
                continue
            args_at_step[step_idx].append(list(tracestep.args))

    # Maximum arg-arity per step across all observations.
    max_arity = [
        max((len(row) for row in args_at_step[s]), default=0)
        for s in range(n)
    ]

    # For these verbs, the first arg in captures is the snapshot id
    # ("click 5"). The id varies wildly between runs (the catalog row
    # at position 5 is a different element each time) but it's not a
    # real parameter — replay uses role-based selectors. Skip arg_idx=0
    # for these so the inference doesn't misclassify the id as a slot.
    _ID_AT_ZERO = frozenset({"click", "hover", "select", "type"})

    out = InferredSlots()
    for step_idx in range(n):
        rows = args_at_step[step_idx]
        verb = ngram.pattern[step_idx].verb
        for arg_idx in range(max_arity[step_idx]):
            if verb in _ID_AT_ZERO and arg_idx == 0:
                # Skip the snapshot-id arg.
                continue
            values = [
                row[arg_idx] for row in rows
                if arg_idx < len(row)
            ]
            if not values:
                continue
            # Distinct-value count ignoring duplicates.
            distinct = sorted(set(values))
            role = (
                ngram.pattern[step_idx].classifier
                if verb in ("click", "type", "select", "hover",
                            "expect_visible", "expect_hidden", "wait_for")
                else None
            )

            if len(distinct) == 1:
                out.concrete.append(ConcreteArgs(
                    step_idx=step_idx, arg_idx=arg_idx, value=distinct[0],
                ))
            else:
                out.params.append(ParamCandidate(
                    step_idx=step_idx, arg_idx=arg_idx,
                    verb=verb, role=role,
                    distinct_values=distinct,
                    proposed_type=_propose_type(distinct),
                ))
    return out
