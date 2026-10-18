"""RAG unit tests (no database, no API key, no model download)."""

import hashlib
import math
import re
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from chromadb import Documents, EmbeddingFunction, Embeddings  # noqa: E402

import rag  # noqa: E402


class WordHashEmbedding(EmbeddingFunction):
    """Tiny offline embedding: hashed bag of words."""

    def __init__(self):
        pass

    def __call__(self, input: Documents) -> Embeddings:
        vectors = []
        for text in input:
            v = [0.0] * 128
            for w in re.findall(r"[a-z_]+", text.lower()):
                v[int(hashlib.md5(w.encode()).hexdigest(), 16) % 128] += 1
            norm = math.sqrt(sum(x * x for x in v)) or 1.0
            vectors.append([x / norm for x in v])
        return vectors

    @staticmethod
    def name():
        return "word-hash-test"

    def get_config(self):
        return {}

    @staticmethod
    def build_from_config(config):
        return WordHashEmbedding()


SCHEMA = [
    {"id": "schema-students", "kind": "schema", "text": "Table students has columns: student_id, name, program."},
    {"id": "schema-courses", "kind": "schema", "text": "Table courses has columns: course_id, course_code, title."},
]


def test_static_documents_have_unique_ids():
    docs = rag.static_documents()
    ids = [d["id"] for d in docs]
    assert len(ids) == len(set(ids))
    assert {d["kind"] for d in docs} == {"semantic", "example"}


def test_retrieval_returns_schema_and_knowledge():
    collection = rag.build_collection(SCHEMA + rag.static_documents(), WordHashEmbedding())
    context = rag.retrieve(collection, "Which courses did Ava Chen take in Spring 2026?", k=3)
    kinds = [c["kind"] for c in context]
    assert kinds[:2] == ["schema", "schema"]
    assert len(context) == 5
    assert "ex-join-term" in [c["id"] for c in context]


def test_extract_sql_from_code_block():
    reply = "Sure:\n```sql\nSELECT 1;\n```\nDone."
    assert rag.extract_sql(reply) == "SELECT 1;"
    assert rag.extract_sql("SELECT 2") == "SELECT 2"


def test_generate_sql_sends_retrieved_context():
    seen = {}

    def create(**kwargs):
        seen.update(kwargs)
        msg = SimpleNamespace(content="```sql\nSELECT name FROM students;\n```")
        return SimpleNamespace(choices=[SimpleNamespace(message=msg)])

    fake = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    context = [{"kind": "schema", "text": "Table students has columns: name."}]
    out = rag.generate_sql("List student names", context, client=fake)
    assert out["sql"] == "SELECT name FROM students;"
    assert "Table students has columns: name." in seen["messages"][1]["content"]
