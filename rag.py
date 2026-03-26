"""
RAG retrieval — embed an incoming email and fetch similar past examples.
Returns None gracefully if the index hasn't been built yet.
"""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path

import config

_rag_logger = logging.getLogger(__name__)

COLLECTION_NAME = "focusgraphics_email_pairs"
CHROMA_PATH = "./data/chroma"
EMBED_MODEL = "text-embedding-3-small"
TOP_K = 3


def _get_collection():
    import chromadb
    client = chromadb.PersistentClient(path=CHROMA_PATH)
    return client.get_collection(COLLECTION_NAME)


def retrieve_examples(query: str) -> list[dict] | None:
    """
    Return up to TOP_K similar past inquiry/response pairs for a given query.
    Returns None if the index doesn't exist yet (graceful degradation).
    """
    if not Path(CHROMA_PATH).exists():
        return None

    try:
        from openai import OpenAI
        openai_client = OpenAI(api_key=config.OPENAI_API_KEY)
        response = openai_client.embeddings.create(model=EMBED_MODEL, input=[query])
        embedding = response.data[0].embedding

        collection = _get_collection()
        results = collection.query(query_embeddings=[embedding], n_results=TOP_K)

        examples = []
        for meta in results["metadatas"][0]:
            examples.append({
                "inquiry": meta["inquiry"],
                "response": meta["response"],
            })
        return examples
    except Exception:
        return None


def index_pair(inquiry: str, response: str) -> None:
    """Embed an inquiry/response pair and upsert into ChromaDB."""
    if not config.OPENAI_API_KEY:
        _rag_logger.warning("[rag] OPENAI_API_KEY not set — skipping index_pair")
        return
    try:
        from openai import OpenAI
        import chromadb

        openai_client = OpenAI(api_key=config.OPENAI_API_KEY)
        embedding_response = openai_client.embeddings.create(
            model=EMBED_MODEL, input=[inquiry]
        )
        embedding = embedding_response.data[0].embedding

        chroma_client = chromadb.PersistentClient(path=CHROMA_PATH)
        collection = chroma_client.get_or_create_collection(COLLECTION_NAME)

        doc_id = hashlib.sha256(inquiry.encode()).hexdigest()[:16]
        collection.upsert(
            ids=[doc_id],
            embeddings=[embedding],
            metadatas=[{"inquiry": inquiry[:2000], "response": response[:2000]}],
        )
    except Exception as e:
        _rag_logger.warning(f"[rag] index_pair failed: {e}")
