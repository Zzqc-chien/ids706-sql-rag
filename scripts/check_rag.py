"""Check the RAG pipeline against the live database.

1. Build the Chroma index from the live schema + knowledge.json.
2. For every quiz question, run the vector retrieval and print what came back.
3. If LLM_API_KEY is set, generate SQL, run it read-only, and compare with the
   expected answer. Wrong SQL is reported but does not fail the job
   (accuracy is not graded); a broken pipeline does.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import quizlib  # noqa: E402
import rag  # noqa: E402


def main() -> int:
    docs = rag.schema_documents() + rag.static_documents()
    kinds = {k: sum(d["kind"] == k for d in docs) for k in ("schema", "semantic", "example")}
    print(f"Knowledge documents: {kinds}")
    if kinds["schema"] == 0:
        print("FAIL  no schema documents were read from the database")
        return 1
    collection = rag.build_collection(docs)
    print(f"Chroma collection holds {collection.count()} documents\n")

    use_llm = bool(quizlib.setting("LLM_API_KEY"))
    client = rag.llm_client() if use_llm else None
    # CI sets RAG_CHECK_LLM_LIMIT=1 so each run spends only one API call
    # (free tiers allow ~20 calls per model per day; the website needs them more).
    limit = int(quizlib.setting("RAG_CHECK_LLM_LIMIT", "0") or 0)
    correct = generated = tried = 0
    quota_hit = False
    for q in quizlib.load_questions():
        context = rag.retrieve(collection, q["prompt"])
        top = ", ".join(f"{c['id']} ({c['distance']})" for c in context)
        print(f"{q['id']}: retrieved {top}")
        if not context:
            print("FAIL  retrieval returned nothing")
            return 1
        if not use_llm or (limit and tried >= limit):
            continue
        tried += 1
        try:
            sql = rag.generate_sql(q["prompt"], context, client)["sql"]
            generated += 1
        except rag.QuotaExhausted as exc:
            quota_hit = True
            print(f"      skipped: {exc}")
            continue
        except Exception as exc:
            print(f"      LLM call failed: {str(exc).strip().splitlines()[0][:150]}")
            continue
        try:
            _, rows = quizlib.run_readonly(sql)
            ok = quizlib.results_match(rows, q["expected"]["rows"], q.get("ordered", False))
        except Exception as exc:  # generated SQL may be invalid
            ok = False
            print(f"      SQL error: {str(exc).strip().splitlines()[0]}")
        correct += ok
        print(f"      generated SQL {'matches' if ok else 'does not match'} the expected result")

    print()
    if use_llm:
        print(f"LLM model {quizlib.setting('LLM_MODEL', 'gpt-4o-mini')}: generated SQL for "
              f"{generated}/{tried} questions tried, {correct} correct")
        if generated == 0 and quota_hit:
            print("NOTE  API quota used up right now; retrieval was still checked")
        elif generated == 0:
            print("FAIL  the LLM did not answer any question")
            return 1
    else:
        print("LLM_API_KEY not set: checked retrieval only")
    print("RAG pipeline OK.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
