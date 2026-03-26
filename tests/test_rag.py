# tests/test_rag.py
import hashlib
from unittest.mock import MagicMock, patch
import pytest
import config
import rag


def test_index_pair_noop_when_openai_key_missing(monkeypatch):
    """index_pair silently no-ops when OPENAI_API_KEY is not set."""
    monkeypatch.setattr(config, "OPENAI_API_KEY", "")
    # Must not raise
    rag.index_pair("Some customer inquiry", "Our response")


def test_index_pair_calls_upsert_with_sha256_id(monkeypatch, tmp_path):
    """index_pair embeds and upserts with deterministic SHA-256 ID."""
    monkeypatch.setattr(config, "OPENAI_API_KEY", "fake-key")
    mock_embedding = [0.1] * 1536
    mock_openai = MagicMock()
    mock_openai.embeddings.create.return_value = MagicMock(
        data=[MagicMock(embedding=mock_embedding)]
    )
    mock_collection = MagicMock()
    mock_chroma = MagicMock()
    mock_chroma.get_or_create_collection.return_value = mock_collection
    with patch("rag.CHROMA_PATH", str(tmp_path / "chroma")), \
         patch("openai.OpenAI", return_value=mock_openai), \
         patch("chromadb.PersistentClient", return_value=mock_chroma):
        rag.index_pair("Hello inquiry", "Hello response")
    expected_id = hashlib.sha256("Hello inquiry".encode()).hexdigest()[:16]
    mock_collection.upsert.assert_called_once_with(
        ids=[expected_id],
        embeddings=[mock_embedding],
        metadatas=[{"inquiry": "Hello inquiry", "response": "Hello response"}],
    )


def test_index_pair_truncates_long_texts(monkeypatch, tmp_path):
    """index_pair truncates inquiry and response to 2000 chars in metadata."""
    monkeypatch.setattr(config, "OPENAI_API_KEY", "fake-key")
    long_inquiry = "A" * 3000
    long_response = "B" * 3000
    mock_openai = MagicMock()
    mock_openai.embeddings.create.return_value = MagicMock(
        data=[MagicMock(embedding=[0.0] * 1536)]
    )
    mock_collection = MagicMock()
    mock_chroma = MagicMock()
    mock_chroma.get_or_create_collection.return_value = mock_collection
    with patch("rag.CHROMA_PATH", str(tmp_path / "chroma")), \
         patch("openai.OpenAI", return_value=mock_openai), \
         patch("chromadb.PersistentClient", return_value=mock_chroma):
        rag.index_pair(long_inquiry, long_response)
    metadata = mock_collection.upsert.call_args.kwargs["metadatas"][0]
    assert len(metadata["inquiry"]) == 2000
    assert len(metadata["response"]) == 2000


def test_index_pair_noop_on_exception(monkeypatch):
    """index_pair catches exceptions and does not propagate them."""
    monkeypatch.setattr(config, "OPENAI_API_KEY", "fake-key")
    mock_openai = MagicMock()
    mock_openai.embeddings.create.side_effect = RuntimeError("API error")
    with patch("openai.OpenAI", return_value=mock_openai):
        # Must not raise
        rag.index_pair("inquiry", "response")
