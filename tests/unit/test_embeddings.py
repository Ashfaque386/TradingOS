from unittest.mock import patch

import pytest

from src.core.config import Settings
from src.memory.embeddings import (
    EmbeddingProviderNotConfiguredError,
    get_embedding_dim,
)


def _settings(**overrides) -> Settings:
    return Settings(_env_file=None, **overrides)


def test_default_provider_is_ollama_no_key_needed():
    settings = _settings()
    assert settings.embedding_provider == "ollama"
    assert get_embedding_dim(settings) == 768


def test_get_embedding_dim_varies_by_provider():
    assert get_embedding_dim(_settings(embedding_provider="huggingface")) == 384
    assert get_embedding_dim(_settings(embedding_provider="local")) == 384
    assert get_embedding_dim(_settings(embedding_provider="openai")) == 1536
    assert get_embedding_dim(_settings(embedding_provider="gemini")) == 768


def test_local_provider_embeds_in_process_no_network_call():
    """REL-005 live E2E verification: sentence-transformers runs locally on CPU, bypassing
    both Ollama's unreliable embedding call and HuggingFace's hosted-API account-tier gate."""
    from src.memory.embeddings import embed_text, embed_texts

    local_settings = _settings(embedding_provider="local")
    with (
        patch("src.memory.embeddings.litellm.embedding") as mock_litellm,
        patch("src.memory.embeddings.get_settings", return_value=local_settings),
    ):
        vector = embed_text("a real strategy hypothesis about momentum breakouts")

    assert len(vector) == 384
    assert all(isinstance(v, float) for v in vector)
    mock_litellm.assert_not_called()  # the whole point: no external API call at all

    with patch("src.memory.embeddings.get_settings", return_value=local_settings):
        vectors = embed_texts(["first text", "second text"])
    assert len(vectors) == 2
    assert len(vectors[0]) == 384


def test_ollama_kwargs_need_no_key():
    from src.memory.embeddings import _litellm_kwargs

    settings = _settings()
    kwargs = _litellm_kwargs(settings)
    assert kwargs["model"] == "ollama/nomic-embed-text"
    assert "api_base" in kwargs


def test_huggingface_provider_without_token_raises_clear_error():
    from src.memory.embeddings import _litellm_kwargs

    settings = _settings(embedding_provider="huggingface")
    with pytest.raises(EmbeddingProviderNotConfiguredError, match="HF_TOKEN"):
        _litellm_kwargs(settings)


def test_openai_provider_without_key_raises_clear_error():
    from src.memory.embeddings import _litellm_kwargs

    settings = _settings(embedding_provider="openai")
    with pytest.raises(EmbeddingProviderNotConfiguredError, match="OPENAI_API_KEY"):
        _litellm_kwargs(settings)


def test_huggingface_provider_with_token_builds_correct_kwargs():
    from src.memory.embeddings import _litellm_kwargs

    settings = _settings(embedding_provider="huggingface", hf_token="hf-test")
    kwargs = _litellm_kwargs(settings)
    assert kwargs["model"] == "huggingface/sentence-transformers/all-MiniLM-L6-v2"
    assert kwargs["api_key"] == "hf-test"


def test_switching_provider_via_settings_changes_request_shape():
    """The whole point: no code edit needed to switch providers, just a Settings/.env value."""
    from src.memory.embeddings import embed_texts

    with (
        patch("src.memory.embeddings.get_settings", return_value=_settings()),
        patch(
            "src.memory.embeddings.litellm.embedding",
            return_value=type("R", (), {"data": [{"embedding": [0.1, 0.2]}]})(),
        ) as mock_embedding,
    ):
        embed_texts(["hello"])
    assert mock_embedding.call_args.kwargs["model"] == "ollama/nomic-embed-text"

    with (
        patch(
            "src.memory.embeddings.get_settings",
            return_value=_settings(embedding_provider="openai", openai_api_key="sk-test"),
        ),
        patch(
            "src.memory.embeddings.litellm.embedding",
            return_value=type("R", (), {"data": [{"embedding": [0.1, 0.2]}]})(),
        ) as mock_embedding,
    ):
        embed_texts(["hello"])
    assert mock_embedding.call_args.kwargs["model"] == "openai/text-embedding-3-small"
    assert mock_embedding.call_args.kwargs["api_key"] == "sk-test"
