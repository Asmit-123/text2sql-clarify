# Text-to-SQL with a Clarification Engine

A natural-language interface to a PostgreSQL database that **asks before it guesses**. When a question is ambiguous
("show me the best customers"), the system pauses, asks one targeted clarification question, remembers the conversation,
and only then generates SQL.

Most text-to-SQL demos silently pick an interpretation of vague words like *best*, *top*, *recent* or *active*. The result
looks right but answers a different question. This project measures how much that costs and how much a clarification
step recovers.

## How it works

```
user ─► State Manager ─► Ambiguity Detector ──ambiguous──► ONE closed question + 2-4 options ─► user
            ▲                   │ clear                                                          │
            └──────── answer ───┼────────────────────────────────────────────────────────────────┘
                                ▼
              SQL Generator  (Pydantic: sql, explanation, tables_used)
                                ▼
         sqlglot validator (single SELECT, known tables) ─► READ ONLY transaction + timeout + row cap
                                ▼   (one self-correction retry on validator or database error)
                         rows + SQL + explanation
```

| Layer | File | Role |
|---|---|---|
| Ambiguity detector | `app/ambiguity.py` | Decides whether two reasonable readings would give materially different results. If so, asks one closed question with 2-4 options taken from real columns and values. |
| State manager | `app/state.py` | Holds the original question and every question/answer pair until the intent is resolved. Serializable, behind a small store interface (swap in Redis for multi-worker use). |
| SQL generator | `app/sql_generator.py` | Produces a strict JSON object (`SQLResult`) with the SQL and a short explanation. |
| Safety | `app/validator.py`, `app/db.py` | AST-level read-only check, known-table check, read-only transaction, statement timeout, row cap. |
| LLM client | `app/llm.py` | JSON mode + Pydantic validation + repair loop. Works with any OpenAI-compatible endpoint. |

Design choices worth noting:

- **Ambiguity means different results, not vague wording.** A plain count with an explicit filter is never flagged.
- **Ranking questions have two open dimensions**: the measure (*best by what?*) and the size (*how many?*). The detector asks about both.
- **Schema grounding.** The prompt includes keys, column comments and the real values of low-cardinality columns, so offered options reference real data.
- **Rate-limit tolerant.** The client retries with backoff on 429 errors.

## Evaluation

`eval/run_eval.py` runs 14 questions (6 clear, 8 ambiguous) against a seeded e-commerce database and compares **execution
accuracy** (result set matches a gold query) in two modes:

- **Baseline**: the raw question goes straight to SQL generation.
- **Clarification engine**: full pipeline. A simulated user answers any clarification question.

Two simulated users are supported: a *perfect* user who replies with the exact intent, and a *realistic* user (an LLM) who
replies casually in one sentence (`--user realistic`).

Results with `openai/gpt-oss-120b` on Groq:

| Metric | Baseline | Clarification (perfect user) | Clarification (realistic user) |
|---|---|---|---|
| Overall accuracy | 57.1% | 100% | 92.9% |
| Ambiguous questions | 25% | 100% | 87.5% |
| Clear questions | 100% | 100% | 100% |
| Clarification recall | 0% | 100% | 100% |
| Unneeded clarifications | 0% | 16.7%* | 0% |

\*Before the prompt fix described below.

What the baseline got wrong: it guessed a definition (for example "underperforming" as below-average sales instead of a
unit threshold), included cancelled orders in an average, or returned every row when the user wanted a top-N.

### Honest caveats

- **Small test set**: 14 cases. Treat the numbers as a demonstration, not a benchmark.
- **Run-to-run variance**: model output varies slightly between runs. In the realistic-user runs a single case flipped
  between passing and failing (78.6% before the ranking-size fix, 92.9% after in two consecutive runs).
- **Simulated users are friendlier than real ones.** The perfect-user 100% is an upper bound.
- **Cost**: the clarification mode is roughly 10x slower per question than the baseline, because of the extra model call(s).
- **One model family** was evaluated end to end (Groq). The Gemini path (`gemini-3.5-flash`) runs the interactive app
  correctly but a full evaluation has not been recorded.

### What iteration taught me

1. A first run showed one clear question being flagged as ambiguous. A targeted prompt rule fixed it, verified over repeated calls.
2. Switching to a realistic simulated user dropped accuracy from 100% to 78.6%. The failures showed that "top" and "newest"
   hide a second ambiguity (how many rows), which led to the two-dimension ranking rule above.
3. One remaining failure traced to the test itself ("top product" is singular while the gold answer expects five), so the test
   question was fixed, not the engine.

## Setup

Requirements: Python 3.10+, PostgreSQL 14+ (or Docker), and an API key for Groq or Gemini (both have free tiers).

```bash
# 1. Database (Docker option)
docker compose up -d
# or, with a local PostgreSQL: createdb shop, then  psql -U postgres -d shop -f db/init.sql

# 2. Python environment
python -m venv .venv
source .venv/bin/activate          # Windows PowerShell: .venv\Scripts\Activate.ps1
pip install -r requirements.txt

# 3. Configure
cp .env.example .env               # Windows: copy .env.example .env
# set LLM_PROVIDER (groq | gemini), the matching API key, and LLM_MODEL
```

Model names change often, so list what your key can use and set `LLM_MODEL` explicitly. Some models appear in a provider's
list but reject new accounts; a quick test call confirms.

```bash
python -m app.cli                          # interactive: try "show me the best customers"
python -m eval.run_eval --check-gold       # print gold-query row counts
python -m eval.run_eval                    # baseline vs clarification, perfect simulated user
python -m eval.run_eval --user realistic   # same, with a casual simulated user
uvicorn app.api:app --reload               # optional HTTP API: POST /ask
```

Free tiers have per-minute and per-day token limits. A full evaluation makes dozens of calls, so a run can stop partway
through when a daily limit is reached; wait and rerun.

## Project layout

```
app/    config, models (Pydantic contracts), llm, schema_introspect, ambiguity, state,
        sql_generator, validator, db, engine, cli, api
eval/   test_cases.json, run_eval.py, user_sim.py
db/     init.sql  (deterministic seed data)
```

## Limitations and next steps

- Conversation state is in memory and resets on restart.
- No follow-up questions ("now only for 2025"); that needs the previous SQL stored in the conversation state.
- The whole schema goes into every prompt; large databases need table retrieval first.
- OpenAI endpoints are supported by the code path but untested.
- A larger, harder test set with several runs per case, and a cross-model comparison.
