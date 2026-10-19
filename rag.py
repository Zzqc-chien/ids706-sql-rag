"""RAG for Text-to-SQL.

Question -> vector retrieval (ChromaDB) -> LLM -> SQL

The knowledge base has three kinds of documents:
  schema   - one document per table, read live from PostgreSQL (information_schema)
  semantic - business rules from knowledge.json
  example  - few-shot question/SQL pairs from knowledge.json

The LLM is called through the OpenAI Python SDK, which also works with any
OpenAI-compatible API (Duke AI Gateway, Gemini's OpenAI endpoint, etc.)
by setting LLM_BASE_URL.
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path

import chromadb
from chromadb.config import Settings

import quizlib

ROOT = Path(__file__).resolve().parent
KNOWLEDGE_FILE = ROOT / "knowledge.json"
COLLECTION = "quiz_knowledge"
TOP_K = 6

SYSTEM_PROMPT = """You write PostgreSQL queries for a quiz database.
Use only the tables and columns that appear in the context.
Return exactly one read-only query (SELECT or WITH ... SELECT) in a ```sql code block.
Do not explain the query."""


# ---------------------------------------------------------------------------
# 1. Build the knowledge documents
# ---------------------------------------------------------------------------
def schema_documents() -> list[dict]:
    """One document per table in the quiz schema, read from the live database."""
    columns_sql = """
        SELECT c.table_name, c.column_name, c.data_type
        FROM information_schema.columns c
        WHERE c.table_schema = 'quiz'
        ORDER BY c.table_name, c.ordinal_position
    """
    # pg_constraint is readable by every role (information_schema hides
    # constraints from a role that only has SELECT).
    fk_sql = """
        SELECT t.relname, pg_get_constraintdef(c.oid)
        FROM pg_constraint c
        JOIN pg_class t ON t.oid = c.conrelid
        JOIN pg_namespace n ON n.oid = t.relnamespace
        WHERE n.nspname = 'quiz' AND c.contype = 'f'
    """
    _, col_rows = quizlib.run_readonly(columns_sql)
    _, fk_rows = quizlib.run_readonly(fk_sql)

    tables: dict[str, list[str]] = {}
    for table, column, dtype in col_rows:
        tables.setdefault(table, []).append(f"{column} ({dtype})")
    links: dict[str, list[str]] = {}
    for table, definition in fk_rows:   # e.g. FOREIGN KEY (student_id) REFERENCES quiz.students(student_id)
        links.setdefault(table, []).append(definition.replace("quiz.", ""))

    docs = []
    for table, cols in tables.items():
        text = f"Table {table} has columns: {', '.join(cols)}."
        if links.get(table):
            text += " Foreign keys: " + "; ".join(sorted(links[table])) + "."
        docs.append({"id": f"schema-{table}", "kind": "schema", "text": text})
    return docs


def static_documents(path: Path = KNOWLEDGE_FILE) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    docs = [{"id": s["id"], "kind": "semantic", "text": s["text"]} for s in data["semantics"]]
    docs += [{"id": e["id"], "kind": "example",
              "text": f"Question: {e['question']}\nSQL:\n{e['sql']}"} for e in data["examples"]]
    return docs


# ---------------------------------------------------------------------------
# 2. Vector store
# ---------------------------------------------------------------------------
def build_collection(docs: list[dict], embedding_function=None):
    """Load the documents into an in-memory Chroma collection.

    The default embedding function is Chroma's built-in all-MiniLM-L6-v2
    (runs locally, no API key needed).
    """
    client = chromadb.EphemeralClient(settings=Settings(anonymized_telemetry=False))
    try:
        client.delete_collection(COLLECTION)
    except Exception:
        pass
    kwargs = {"name": COLLECTION, "metadata": {"hnsw:space": "cosine"}}
    if embedding_function is not None:
        kwargs["embedding_function"] = embedding_function
    collection = client.create_collection(**kwargs)
    collection.add(
        ids=[d["id"] for d in docs],
        documents=[d["text"] for d in docs],
        metadatas=[{"kind": d["kind"]} for d in docs],
    )
    return collection


def _query(collection, question: str, n: int, where: dict) -> list[dict]:
    res = collection.query(query_texts=[question], n_results=n, where=where)
    return [
        {"id": i, "kind": m["kind"], "text": t, "distance": round(float(d), 3)}
        for i, t, m, d in zip(res["ids"][0], res["documents"][0],
                              res["metadatas"][0], res["distances"][0])
    ]


def retrieve(collection, question: str, k: int = TOP_K) -> list[dict]:
    """Two vector searches: the closest tables, then the closest rules/examples.

    Searching the schema separately means the table definitions are never
    pushed out by long examples (a simple form of schema linking).
    """
    n_schema = len(collection.get(where={"kind": "schema"})["ids"])
    tables = _query(collection, question, min(3, n_schema), {"kind": "schema"})
    knowledge = _query(collection, question, k, {"kind": {"$in": ["semantic", "example"]}})
    return tables + knowledge


# ---------------------------------------------------------------------------
# 3. LLM
# ---------------------------------------------------------------------------
def build_prompt(question: str, context: list[dict]) -> str:
    blocks = "\n\n".join(f"[{c['kind']}] {c['text']}" for c in context)
    return f"Context retrieved from the knowledge base:\n\n{blocks}\n\nQuestion: {question}"


def extract_sql(text: str) -> str:
    """Pull the SQL out of the model's reply."""
    match = re.search(r"```(?:sql)?\s*(.*?)```", text, re.DOTALL | re.IGNORECASE)
    sql = match.group(1) if match else text
    return sql.strip()


def llm_client():
    from openai import OpenAI

    key = quizlib.setting("LLM_API_KEY")
    if not key:
        raise RuntimeError("Missing setting LLM_API_KEY.")
    base_url = quizlib.setting("LLM_BASE_URL") or None
    timeout = float(quizlib.setting("LLM_TIMEOUT", "90"))
    return OpenAI(api_key=key, base_url=base_url, timeout=timeout, max_retries=1)


def is_config_error(exc) -> bool:
    """True for errors that mean the setup is wrong (bad key, bad model name),
    False for temporary ones (timeout, rate limit, server error)."""
    return getattr(exc, "status_code", None) in (400, 401, 403, 404)


class QuotaExhausted(RuntimeError):
    """Every configured model hit its API quota."""


def _retry_seconds(exc) -> float | None:
    """How long the API asked us to wait after a 429, in seconds."""
    text = str(exc)
    match = re.search(r"retryDelay['\"]?\s*:\s*['\"](\d+(?:\.\d+)?)s", text)
    if match:
        return float(match.group(1))
    match = re.search(r"retry in (?:(\d+)h)?(?:(\d+)m)?([0-9.]+)s", text)
    if match:
        h, m, sec = match.groups()
        return int(h or 0) * 3600 + int(m or 0) * 60 + float(sec)
    return None


def models_to_try() -> list[str]:
    """LLM_MODEL first, then any LLM_FALLBACK_MODELS (comma separated)."""
    main = quizlib.setting("LLM_MODEL", "gpt-4o-mini")
    extra = [m.strip() for m in (quizlib.setting("LLM_FALLBACK_MODELS") or "").split(",") if m.strip()]
    return [main] + [m for m in extra if m != main]


def generate_sql(question: str, context: list[dict], client=None, retries: int = 2) -> dict:
    """Ask the LLM for SQL.

    Free API tiers have per-minute and per-day limits. A short wait (per-minute
    limit) is retried on the same model; a long one (daily limit) moves on to
    the next model in LLM_FALLBACK_MODELS, since each model has its own quota.
    """
    client = client or llm_client()
    prompt = build_prompt(question, context)
    messages = [{"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt}]
    for model in models_to_try():
        for attempt in range(retries + 1):
            try:
                resp = client.chat.completions.create(model=model, temperature=0, messages=messages)
            except Exception as exc:
                if getattr(exc, "status_code", None) != 429:
                    raise
                wait = _retry_seconds(exc)
                if (wait is not None and wait > 60) or "PerDay" in str(exc) or attempt == retries:
                    break                      # this model is out of quota: try the next one
                time.sleep((wait or 10) + 1)
                continue
            raw = resp.choices[0].message.content or ""
            return {"sql": extract_sql(raw), "raw": raw, "model": model, "prompt": prompt}
    raise QuotaExhausted(
        "The AI API quota is used up for now (free tier limit) for: " + ", ".join(models_to_try())
        + ". Please try again later.")


def answer(question: str, collection, client=None, k: int = TOP_K) -> dict:
    """The full pipeline: retrieve, then generate."""
    context = retrieve(collection, question, k)
    result = generate_sql(question, context, client)
    result["context"] = context
    return result
