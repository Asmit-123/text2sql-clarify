"""Compare execution accuracy WITH vs WITHOUT the clarification engine.

    python -m eval.run_eval                 # full run, writes eval/results.json
    python -m eval.run_eval --check-gold    # just print gold row counts (sanity-check your dataset)

Protocol
- Each case has a vague `question` and, for ambiguous ones, the user's hidden intent as `clarification_answer`
  plus a `gold_sql` that encodes that intent.
- BASELINE: the raw question goes straight to SQL generation (the model must guess).
- CLARIFY:  full engine. If it asks a question, a simulated user replies with `clarification_answer`.
- Metric: execution accuracy = result-set match against gold. Row order only matters if gold has ORDER BY.
  Extra columns in the generated result are tolerated (gold columns must all be present).
"""
import argparse
import json
import re
import statistics
import time
from decimal import Decimal
from pathlib import Path

from app.config import Settings
from app.db import execute_query
from app.engine import Text2SQLEngine
from app.llm import LLMClient
from app.schema_introspect import SchemaProvider
from eval.user_sim import SimulatedUser

CASES = Path(__file__).with_name("test_cases.json")
MAX_TURNS = 3


# ---------------------------------------------------------------- result comparison
def _norm(v):
    if isinstance(v, (int, float, Decimal)) and not isinstance(v, bool):
        return round(float(v), 2)
    return None if v is None else str(v)


def _same(a, b, ordered):
    return a == b if ordered else sorted(a, key=repr) == sorted(b, key=repr)


def results_match(gold_rows, gen_rows, ordered: bool) -> bool:
    gold = [tuple(_norm(v) for v in r) for r in gold_rows]
    gen = [tuple(_norm(v) for v in r) for r in gen_rows]
    if len(gold) != len(gen):
        return False
    if not gold:
        return True
    if _same(gold, gen, ordered):
        return True
    # tolerate extra / differently-ordered columns: map each gold column to an equal generated column
    gold_cols, gen_cols = list(zip(*gold)), list(zip(*gen))
    mapping: list[int] = []
    for gc in gold_cols:
        key = sorted(map(repr, gc))
        idx = next((i for i, c in enumerate(gen_cols) if i not in mapping and sorted(map(repr, c)) == key), None)
        if idx is None:
            return False
        mapping.append(idx)
    return _same(gold, [tuple(r[i] for i in mapping) for r in gen], ordered)


# ---------------------------------------------------------------- runner
def run_mode(name, cases, gold, clarify, settings, llm, schema, user=None):
    engine = Text2SQLEngine(settings, llm=llm, schema=schema, enable_clarification=clarify)
    records = []
    for case in cases:
        sid, turns, t0 = f"{name}-{case['id']}", 0, time.time()
        resp = engine.ask(sid, case["question"])
        while resp.status == "needs_clarification" and turns < MAX_TURNS:
            turns += 1
            if user:
                answer = user.reply(case, resp.clarification_question, resp.options)
            else:
                answer = case.get("clarification_answer", "Use your best judgment.")
            print(f"      user> {answer}")
            resp = engine.ask(sid, answer)
        correct = False
        if resp.status == "answered":
            ordered = bool(re.search(r"order\s+by", case["gold_sql"], re.I))
            correct = results_match(gold[case["id"]], resp.rows, ordered)
        records.append({"id": case["id"], "ambiguous": case["ambiguous"], "turns": turns, "status": resp.status,
                        "correct": correct, "sql": resp.sql, "error": resp.error,
                        "latency_s": round(time.time() - t0, 2)})
        print(f"  [{name:8}] {case['id']:3} {'OK ' if correct else 'FAIL'} turns={turns} {resp.status}")
    return records

def summarize(records):
    def acc(rs):
        return round(100 * sum(r["correct"] for r in rs) / len(rs), 1) if rs else None
    amb = [r for r in records if r["ambiguous"]]
    clear = [r for r in records if not r["ambiguous"]]
    return {
        "overall_accuracy_%": acc(records),
        "ambiguous_accuracy_%": acc(amb),
        "unambiguous_accuracy_%": acc(clear),
        "clarification_recall_%": round(100 * sum(r["turns"] > 0 for r in amb) / len(amb), 1) if amb else None,
        "unneeded_clarification_%": round(100 * sum(r["turns"] > 0 for r in clear) / len(clear), 1) if clear else None,
        "avg_turns": round(statistics.mean(r["turns"] for r in records), 2),
        "errors": sum(r["status"] == "error" for r in records),
        "avg_latency_s": round(statistics.mean(r["latency_s"] for r in records), 2),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check-gold", action="store_true")
    ap.add_argument("--user", choices=["perfect", "realistic"], default="perfect")
    args = ap.parse_args()

    settings = Settings()
    settings.row_limit = 10_000
    cases = json.loads(CASES.read_text())
    gold = {}
    for c in cases:
        _, rows = execute_query(settings, c["gold_sql"], row_limit=10_000)
        gold[c["id"]] = rows
    if args.check_gold:
        for c in cases:
            print(f"{c['id']:3} gold rows: {len(gold[c['id']])}")
        return

    llm, schema = LLMClient(settings), SchemaProvider(settings)
    user = SimulatedUser(llm) if args.user == "realistic" else None
    print(f"Model: {settings.provider}/{settings.model}  |  cases: {len(cases)}")
    base = run_mode("baseline", cases, gold, False, settings, llm, schema)
    clar = run_mode("clarify", cases, gold, True, settings, llm, schema, user)
    sb, sc = summarize(base), summarize(clar)

    print(f"\n{'metric':28}{'baseline':>12}{'clarify':>12}")
    for k in sb:
        print(f"{k:28}{str(sb[k]):>12}{str(sc[k]):>12}")

    out = Path(__file__).with_name("results.json")
    out.write_text(json.dumps({"model": f"{settings.provider}/{settings.model}", "baseline": {"summary": sb, "cases": base},
                               "clarify": {"summary": sc, "cases": clar}}, indent=2))
    print(f"\nDetailed results -> {out}")


if __name__ == "__main__":
    main()
