# Macros — design notes

## Goal

Compile **frequently-recurring sub-traces of the agent loop** into reusable, deterministic skills that the runner can invoke without spinning the LLM. The trigger pattern is regression testing on the same site: search-and-buy on a marketplace, login → navigate → assert on an SPA, multi-step settings flows. After running these N times the LLM is asking the same questions and getting the same answers; that's pure waste.

Tagged DSL (`qa_agent/tagged.py`) is the **compile target**: a learned skill is a tagged-DSL block, optionally parameterised. Replay is `run_tagged_task` — already exists, already deterministic, already has full diagnostics.

The pipeline is **hybrid**: a symbolic frequent-subsequence miner finds candidates by frequency, an LLM curator labels them and infers parameter slots, dry-run validation gates promotion to the skill library. This avoids both extremes (pure-symbolic = PhD-level R&D for years; pure-LLM-curator = unbounded cost and unprovable behaviour).

## Use-case priority

The tool is primarily a regression-test harness for **the same site under repeated runs**. That makes the macro economics good:

- High duplication factor — one site × hundreds of runs/day → most action sequences are seen many times.
- Drift is gradual — site changes happen at deploy boundaries, not per run, so cached macros are useful for hours-to-days.
- Operator already accepts deterministic execution (tagged DSL) for known checks — macros are an automatic version of that for unknown-up-front but recurring sequences.

Cross-site generalisation (same skill on Amazon and on Wildberries) is **lower-priority**, lives in Phase 4. It's the hardest piece and least immediately valuable for the current bench.

## Pipeline overview

```
                  ┌─────────────────────────┐
   forward path → │  capture (Phase 0)       │ → ~/.config/qa_agent/captures/<run>.jsonl
                  │  per-step records with   │
                  │  page signatures         │
                  └────────────┬─────────────┘
                               │
                    ┌──────────┴──────────┐
                    │                     │
                    ▼                     ▼
        ┌───────────────────┐   ┌──────────────────────┐
        │ frequent-subseq   │   │ LLM curator           │
        │ miner (PrefixSpan │   │ (Phase 1, hybrid)     │
        │ on action+role    │   │ — labels, infers      │
        │ tuples)           │   │   parameter slots     │
        └────────┬──────────┘   └──────┬───────────────┘
                 │                     │
                 └──────────┬──────────┘
                            │
                            ▼
                ┌────────────────────────────┐
                │ candidate macros            │
                │ (tagged-DSL + meta.json)    │
                └────────┬───────────────────┘
                         │
              dry-run validation (Phase 1.5)
                         │
                         ▼
                ┌────────────────────────────┐
                │ ~/.config/qa_agent/macros/  │
                │   <name>/macro.tagged.txt   │
                │   <name>/meta.json          │
                └────────┬───────────────────┘
                         │
        ┌────────────────┴────────────────┐
        │                                 │
        ▼                                 ▼
explicit replay                online detection (Phase 3)
(Phase 2: `macro <name>`         child FSM watches the
in DSL / CLI flag)               action stream, suggests
                                 / auto-invokes when prefix matches
```

## Phase 0 — capture (DONE)

Implemented in this commit. Every `run_task` and `run_tagged_task` writes a JSONL trace to `~/.config/qa_agent/captures/{browser,tagged}/<run_id>.jsonl`:

```
{"t": "start", "mode": "llm"|"tagged", "run_id": ..., "task": ..., "url": ..., ...}
{"t": "step", "step": N, "action": ..., "args": [...], "result": ..., "page_url": ...,
 "pre_signature": {url_template, raw_url, struct_hash, content_hash, n_elements}, ...}
{"t": "result", "status": ..., "confidence": ..., ...}
```

`pre_signature` is computed by `qa_agent/runtime/page_signature.py`:

| field | invariant under | use |
|---|---|---|
| `url_template` | dynamic path / query values | precondition match: same template? |
| `struct_hash` | content changes | precondition match: same shape? |
| `content_hash` | structural changes | "same instance" detection |
| `n_elements` | — | quick filter |

Two pages are *same template* if `(url_template, struct_hash)` match. *Same instance* if all three match. Edit-distance fuzzy matching is a Phase 4 TODO (APTED on the structural feature lists).

Default-on; opt-out via `QA_DISABLE_CAPTURE=1`. Writes are best-effort — instrumentation never breaks a run.

`screenshots_dir` and capture file share the same `run_id` stamp so post-mortem can correlate them by stem.

## Phase 1 — offline miner (DONE)

Implemented in `qa_agent/macros/miner/`. CLI: `python -m qa_agent.macros.miner [--captures-dir ...] [--macros-out ...] [--min-support N] [--min-len N] [--max-len N] [--no-curate] [--no-validate] [--dry-run] [--include-failed] [--include-tagged]`.

What changed from the original design:

1. **Contiguous N-grams instead of PrefixSpan**. The action traces in this codebase are short and structured — gaps between meaningful actions are typically `look` / `screenshot` / `wait` (which the vocabulary pass drops). A skill is a contiguous chunk of the post-vocabulary sequence; gap-allowing PrefixSpan would over-cluster. Closed-pattern filter (BIDE-style) drops shorter N-grams that share full support with a longer extension. ~80 lines, no deps. If/when we need cross-page workflows with variable middles, swap in PrefixSpan — the pipeline is decoupled.

2. **Vocabulary**. Step → `(verb, classifier)` token. `classifier` is `target_role` for click/type/select/hover/wait_for, `key:enter` etc. for press, `wait_short`/`wait_medium`/`wait_long` bucketing for wait, `url:host` for goto, `js:<head_token>` for evaluate, fixed labels (`text_assert`, `count_assert`, ...) for expect_*. Concrete arg values do NOT enter the vocabulary — that's inference territory.

3. **Inference**. For each (step_idx, arg_idx) in a candidate, collects raw arg values across occurrences. All-equal → concrete arg, embedded verbatim in the tagged-DSL body. Differing → parameter candidate, types proposed via numeric / URL-shape detection. **Snapshot ids** at arg position 0 of click / hover / select / type are dropped here — they vary trivially run-to-run but aren't real parameters; replay uses role-based selectors.

4. **Curation pass — symbolic OR LLM**. `curate(ngram, slots, traces, use_llm=...)`. `use_llm=False` mode synthesises a name from the vocabulary tokens, picks generic slot names (`text`/`url`/`expr`/`param_S_A`), keeps every candidate. `use_llm=True` calls `qa_agent.llm.ask_llm` with a structured-output prompt (JSON-only reply), validates the response (every inference slot must appear in the LLM's `params`, name must match `[A-Za-z_][A-Za-z0-9_]*`), drops on parse failure or `keep=false`. LLM errors fall back to offline curation rather than dropping the candidate.

5. **Validation = structural alignment**. `validate()` re-walks each occurrence in the source captures and scores `(matched_steps / total_steps)` against the candidate pattern. ≥0.95 passes. Live-page replay validation (Phase 1.5 in the original plan) is **not** implemented — it's expensive (one browser per candidate) and operationally captured by the next real run that uses the macro. The structural pass catches the most common failure mode (inference hallucinated a slot or the miner over-clustered).

6. **Emit**. `emit(curated, occurrences, traces, output_root)` writes:
   - `<root>/<name>/macro.tagged.txt` — body with `${param}` placeholders
   - `<root>/<name>/meta.json` — schema (name, version=1, description, params, preconditions.url_templates, support_count, success_rate, learned_from_runs)
   Per-verb rendering dispatches in `_render_step`: `click <role>` (no name — captures don't carry accessible names), `type <role> ${text}`, `goto ${url}`, `press Enter`, `expect_visible <role>`, etc. `select` has no tagged-DSL counterpart, emitted as a comment so the operator can replace.

End-to-end verified on synthetic 4-run "search the catalog" workload:

```
4 traces, vocab=5 tokens each
mined 10 ngrams → 1 closed (len=5, support=4)
inference: 1 param (`text`, observed: hammer/wrench/гвозди/отвёртка), 3 concrete
validation: score=1.0 → pass
emit:
  goto "https://shop.example.com/"
  click button
  type textbox ${text}
  press Enter
  expect_visible heading
```

On real-world captures from this repo's own test runs (7 traces accumulated), the miner finds 3 candidate macros at min-support=2, including `goto + wait_for + expect_visible + ...` from the campo-staging tagged smoke runs.

### Phase 1 — what's NOT done

- **Live-page dry-run validation**. Structural alignment only. Live validation can be added as `validate_live(macro, captures_dir)` that loads the macro, picks a sample params set from `learned_from_runs`, and runs `run_macro_task` against the captured URL. Cost = one browser launch per candidate, gated behind `--live-validate`.
- **Step boundary inference**. Original plan had `boundaries.py` for finding "where a skill starts/ends" via signature deltas + anchor verbs. With contiguous N-gram mining boundaries are the N-gram itself — the structural-alignment validation catches over-clustering. If that turns out insufficient on real-world captures, add boundary detection as an inference step before emit.
- **Auto-merge / versioning**. Re-emitting an existing macro overwrites in place (same name, same version). No diff-based version bump. Manual `meta.version` bumps still work.

## Phase 1 — original plan, kept for context

Runs as a separate CLI: `python -m qa_agent.macros.mine [--min-runs 5] [--min-len 3]`.

Inputs:
- `~/.config/qa_agent/captures/**/*.jsonl` — accumulated traces.

Steps:

1. **Bucket by template**. Group steps by `template_key(signature)`. Macro is a per-template artefact: a "search the marketplace catalog" skill is bound to the catalog page template, not to any product page.

2. **Action vocabulary**. Reduce each step to a tuple `(verb, target_role, arg_type)`. Examples:
   - `(click, button, "name=Search")` — fully concrete
   - `(type, textbox, "<param:query>")` — parameter slot
   - `(press, "Enter", -)` — fully concrete
   The arg-type abstraction is what makes "search anything" a single sequence rather than one per query.

3. **Frequent sequence mining**. PrefixSpan (Pei 2001) or BIDE (Wang 2004 — closed patterns, smaller output) on the per-template action vocabulary. Configurable `min_support` (default: ≥3 distinct runs ending in success). Output: candidate sub-traces with their support count.

4. **Boundary inference**. A candidate from frequent mining is a contiguous subsequence; the boundaries (where a skill starts and ends) are inferred via:
   - **Page-signature delta** — large struct_hash change before/after the candidate (skill produced a navigation).
   - **Anchor verbs** — sequences starting at a `goto` / `click` of a major nav element and ending at an `expect_*` or a `done`.

5. **LLM curation pass** (hybrid). Send the candidate sub-trace + a sample of 2-3 page-signatures it crossed to a small model (Haiku-class, that's it). Ask:
   - Name this skill in 2-4 words.
   - Which steps' arg-strings are *parameters* (vs. fixed)?
   - Write a 1-sentence description.
   - Does this look like a coherent skill or a random co-occurrence? (yes/no gate.)
   The miner uses the LLM verdict as a soft filter — it doesn't trust it for behaviour, only for labeling and slot inference.

6. **Compile to tagged DSL with slots**. Output:
   ```
   # ~/.config/qa_agent/macros/marketplace_search_v1/macro.tagged.txt
   # name: marketplace_search
   # description: Open search bar, type query, submit.
   # params: query (string, required)
   click textbox "Search"
   type textbox "Search" "${query}"
   press Enter
   wait_for [data-testid=results-list] 8000
   expect_visible [data-testid=results-list]
   ```
   And alongside `meta.json`:
   ```json
   {
     "name": "marketplace_search",
     "version": 1,
     "preconditions": {
       "url_templates": ["https://wb.ru/", "https://example.com/catalog"],
       "struct_hashes": ["abc123...", "def456..."]
     },
     "params": [{"name": "query", "type": "string", "required": true}],
     "support": 12,
     "success_rate": 1.0,
     "learned_from_runs": ["run_...", "run_..."]
   }
   ```

7. **Dry-run validation** (Phase 1.5). Replay the candidate macro against captured traces (`page_url` + simulated action results from the trace). If success rate < 0.8 — drop. Real-page validation is Phase 2.

### Algorithms — references

| pick | for what | why |
|---|---|---|
| **PrefixSpan** (Pei 2001) | sequential pattern mining | linear in pattern count, Python implementations available (e.g. `prefixspan` package), reasonable defaults |
| **BIDE** (Wang 2004) | closed sequential patterns | smaller candidate set than PrefixSpan, fewer LLM-curation calls |
| **CM-SPADE** (Fournier-Viger 2014) | parallel + co-occurrence map | fastest in benchmarks, overkill for our scale |

For the current capture rate (low thousands of traces/day, ~30 steps each) PrefixSpan is sufficient. Move to BIDE when the candidate explosion becomes a curation-cost problem.

## Phase 2 — explicit replay

DSL extension (in both modes):

```
macro <name> [param=value] [param=value] ...
```

Tagged grammar gets a new verb in `qa_agent/tagged.py`. LLM grammar gets the verb in `SYSTEM_PROMPT` and a parser branch in `parse_action`.

Resolution: `~/.config/qa_agent/macros/<name>/macro.tagged.txt` is read, parameters substituted, executed via `run_tagged_task` recursively. The agent gets a single result row (`macro <name> -> success: 8 sub-steps PASS`) and continues.

Replay logs nest under the parent run: a `macro` step in the parent capture has a `nested_capture` path pointing at the sub-run's JSONL.

This phase is small (~200 LoC) and fully unblocks human-curated macros even before mining works.

## Phase 3 — online detection

`MacroFSM` — child FSM next to the existing `AgentFSM`. Listens on `act_classify` via a transition listener; tracks the current path of `(verb, target_role)` tuples; matches against a precompiled Aho-Corasick automaton built from all installed macros' action prefixes.

When a prefix match is found and the current page-signature satisfies the macro's preconditions:

- **Suggest mode** (default): inject a user-msg into the LLM conversation: `"This sub-trace looks like macro `<name>`. Use `macro <name> [params]` to invoke."`. LLM decides.
- **Auto-invoke mode** (operator opt-in): swap the next agent action for the macro and skip ahead.

Both modes log `step_record["macro_match"]` so the recorder captures it.

Auto-invoke is the dangerous one — needs a kill-switch (`QA_DISABLE_AUTO_MACRO=1`) and a runtime invariant: if any sub-step's `expect_*` post-condition fails, abort the macro and fall back to LLM mid-flight. This is why every macro **must** include post-condition checks.

## Phase 4 — site-mapping / generalisation

The hard part. Cross-site skill transfer.

Goals:
- "Search anything" skill works on Wildberries, Amazon, eBay — same parameter (query), different DOM trees, different selectors.
- Site mapping: incrementally learn the skeleton of a site (header / nav / footer / content area) by clustering structural fingerprints across pages.

Components needed:

1. **Tree-edit distance** — APTED (Pawlik+Augsten 2015). O(n·m) pessimistic, much faster in practice on real DOM. Used for: "is this page on site A *similar to* this page on site B?" Threshold tuning is empirical.

2. **Subtree fingerprinting** — Merkle-style: `hash(tag, role, sorted(child_fingerprints))`. Enables O(n) "did this subtree change since last visit?" check, used for incremental signature recomputation.

3. **Macro generalisation by selector abstraction**. A macro learned on site A has selectors like `button "Найти"` (role + name). Cross-site reuse requires:
   - Replace specific roles + names with role-only selectors when consistent across sites in a cluster.
   - Validate via dry-run on captures from both sites.

4. **Site clusters**. DBSCAN or BIRCH on (url-template-host, struct_hash) tuples → "marketplace cluster", "settings-page cluster". Macros tagged with cluster ids.

This is the part that justifies the "tree-sitter analogue" framing — but tree-sitter itself is for *text* grammars and incremental parsing; the analogue here is **structural-hash incremental tree comparison**, which is an open research area on real DOM but well-understood on synthetic benchmarks.

Phase 4 is **research-grade**. Concrete algorithms exist; the engineering effort to make them robust on real-world sites is large. Postpone until Phases 0-3 prove out.

## Hybrid LLM-curator details

Two roles for the LLM in this pipeline, both small-model (Haiku-class):

1. **Phase 1 curation** — names, slots, gate. One call per candidate. Bounded by candidate count (tens to low hundreds per offline run); cheap.

2. **Phase 3 disambiguation** — if multiple installed macros match the current prefix, ask the LLM "which one fits this state?". Bounded by number of online matches; very rare.

Both can run on `claude-haiku-4-5` or any small model; no need for Sonnet/Opus. Token cost is dwarfed by the per-step LLM calls macros replace.

## Risks (recap, expanded)

- **Compounding silent errors.** Mitigation: every macro step ends with an `expect_*` post-condition; runner aborts the macro on first miss. This is a hard invariant — the miner refuses to emit a macro without per-step assertions.
- **Site drift.** Macros are versioned; a top-level miner re-run promotes new versions when struct_hash distribution shifts. `meta.json` carries a `learned_from_runs` array; if those runs are >7 days old, the macro is flagged for revalidation.
- **False-positive prefix matches.** Online detection requires `(struct_hash matches)` AND `(prefix matches)` AND `(URL template matches)`. All three.
- **Privacy.** Operator-policy-acknowledged off (this build). Captures may contain seed phrases / OAuth tokens — operator's responsibility to scrub the captures dir before sharing.
- **Cost vs. benefit.** Phases 0-2 are cheap (~3-4 weeks engineering, real benefit). Phases 3-4 are weeks-to-months and only justified when daily run volume is high. Don't gold-plate ahead of demand.

## Open questions

1. **Macro storage location.** `~/.config/qa_agent/macros/` — per-user. Should the bench harness use a fixture-local override (`bench/fixtures/<id>/macros/`) so CI runs are reproducible without contaminating user state? Probably yes.
2. **Capture retention.** No GC currently. Add `--gc-captures` CLI? Or rotate by age (>30 days → delete)?
3. **Capture format stability.** JSONL schema is going to evolve as we add fields. Embed `"capture_version": "1"` in the start record so the miner can refuse incompatible old traces gracefully.
4. **Macro DSL beyond tagged.** Tagged covers most flows, but recursive macros (a macro invoking another) need the parser extension in Phase 2. Is that worth doing in Phase 2 or Phase 3?

## What's done in the current commit

- `qa_agent/runtime/page_signature.py` — full module with url_template, struct_hash, content_hash, compute_signature, helper keys.
- `qa_agent/extract.py::extract_elements` — returns `(elements, dsl_text, is_fallback, text_snippets)` (4-tuple) so signature can hash the visible-text bag.
- `qa_agent/runtime/actions.py::snapshot_page` — computes signature, embeds in snapshot dict.
- `qa_agent/runtime/fsm_actions.py::act_new_step` — surfaces `pre_signature` on each step record.
- `qa_agent/agent.py` — `_Capture` writer, `_wrap_step_callback` composer, both `run_task` and `run_tagged_task` write to `~/.config/qa_agent/captures/{browser,tagged}/<run_id>.jsonl` with start/step/result records. Default on; `QA_DISABLE_CAPTURE=1` opts out.

Next step is Phase 1 — offline miner. That's a separate effort, gated on having enough captured traces to mine against.
