# Judging

The canonical rubric the judge panel actually scores against lives at
[`scripts/judge/rubric.md`](../../scripts/judge/rubric.md). That file is
the source of truth — if anything in this document drifts from it,
trust the rubric, not this page, and file an issue so we can fix the
drift.

This page is the participant-facing summary of how scoring works in
practice.

## How it works

1. When you open a PR, CI runs `uv sync`, `uv run ruff check .`,
   `uv run ruff format --check .`, `uv run pyright`, and
   `uv run pytest -v`. **Any non-zero exit knocks you out of contention
   until you fix it.** The judge panel does not score broken PRs.
2. Once CI is green, the judge panel
   ([`scripts/judge/judge_pr.py`](../../scripts/judge/judge_pr.py))
   reads the PR body, the diff, and the checks summary, and runs N
   independent LLM judges (default 3) against the rubric. Each judge
   returns a structured JSON verdict with a per-dimension integer score
   and a short rationale.
3. The aggregator takes the per-dimension median across judges, and the
   headline "total" is `median_low` of the per-judge totals — both are
   written verbatim to [`docs/hackathon/scores.json`](./scores.json),
   along with a deterministic three-sentence consensus narrative.
4. The leaderboard sort key is that headline total (the `median` field
   in `scores.json`, an integer-valued float in `[6, 30]`). Ties go to
   the earlier PR.

## The six dimensions

Each dimension is scored as an integer in `[1, 5]`. The headline total
is the sum of the dimension medians across judges and therefore lives
in `[6, 30]`. For the full anchor descriptions at 1, 3, and 5 see
[`scripts/judge/rubric.md`](../../scripts/judge/rubric.md); this table
is a one-line summary.

| # | Dimension          | What it measures (1-5 scale)                                                                                                                                                                                          |
|---|--------------------|-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| 1 | **correctness**       | Does the code do what the PR claims; are obvious bugs and edge cases handled; does the algorithm match the cited spec.                                                                                                |
| 2 | **test_rigor**        | Coverage of failure modes, property-based vs example-only, adversarial / byzantine inputs. Tests should catch the bugs in score-1 territory.                                                                          |
| 3 | **api_fit**           | Implements the layer Protocol exactly; entry point wired in `pyproject.toml`; uses `nest_core` types; idiomatic to NEST (SPDX header, `from __future__ import annotations`, `Example::` blocks).                       |
| 4 | **docs_quality**      | PR body covers motivation, design, tradeoffs, and a runnable verification snippet; every public function/class has a docstring with an `Example::` block; scenario YAML or runnable command included where relevant.   |
| 5 | **novelty**           | Materially different from the reference plugin and from already-merged peers; bonus for non-obvious invariant checks, novel layer compositions, benchmarks that surface hidden properties.                            |
| 6 | **persona_fidelity**  | The persona declared in the branch / PR title is legible in the code itself — risk model, test emphasis, idioms — not just a label on a generic submission.                                                            |

Scoring discipline (from the rubric):

- Score the artifact *as it stands in this PR*, not what it could become.
- "Textbook restatement" is not a sin if the textbook is right; it just
  caps novelty. Correctness, fit, and tests are judged on their own.
- Do not penalize a submission for being small if it is correct,
  tested, and idiomatic. Do not reward a submission for being large
  if the bulk is filler.
- If a judge can't tell from the diff (e.g., tests live in a file the
  diff truncates), they say so in their rationale and score
  conservatively (3 = "can't fully verify but no red flags").

## Scoreboard

The scoreboard is regenerated after every merge by
[`scripts/judge/run_all.py`](../../scripts/judge/run_all.py) and
published at [`docs/hackathon/scores.json`](./scores.json). Each
submission entry carries the per-dimension medians, the headline
`median` total (`[6, 30]`), the `consensus` narrative, and per-judge
verdicts. The `/hackathon` marketplace UI in the dashboard reads from
this file via the marketplace adapter. The leaderboard is monotone: a
later PR cannot demote an earlier one.

## Anti-gaming

- **No "judge the judges" PRs.** Modifying the rubric, the seed bank,
  or the scoreboard JSON itself is out of scope for hackathon PRs and
  will be reverted on merge.
- **No proprietary tricks.** If your plugin needs `OPENAI_API_KEY` or
  any other secret to run, declare it in the PR description and provide
  a deterministic mock fallback. Tier 1 must remain deterministic.

If something here is ambiguous, file an issue and ask. We would rather
be explicit than catch you out on a technicality.
