"""Text embeddings for the Qdrant RAG pipeline (Phase 2 Epic E2.4).

Provider is a settings toggle (`EMBEDDING_PROVIDER`, default "ollama"), not a hardcoded choice
-- switching to HuggingFace, "local", OpenAI, or Gemini is a `.env` change, same pattern as the
LLM completion router (src/agents/llm_router.py).

Each provider has a different embedding dimension, and Qdrant has no in-place vector resize, so
changing EMBEDDING_PROVIDER requires re-running src/memory/collections.py's bootstrap with
recreate_if_dim_mismatch=True (this drops and recreates the collections -- fine while they hold
no data you need, not fine once real strategies are stored).

Why the default is Ollama, not HuggingFace: Phase_11_Database_Design.md's original sketch
assumed OpenAI text-embedding-3-small. No OpenAI key is configured. HuggingFace was tried next
(HF_TOKEN is configured), but HF's Inference Providers backend rejects every embedding model for
free-tier accounts without billing/Pro enabled (confirmed via
https://huggingface.co/api/whoami-v2: isPro=false, canPay=false) -- an account-tier gate, not a
code issue, verified across 7+ models and a litellm-bypassing raw request (Phase 2 E2.4), and
re-confirmed against 6 more model names during REL-005's live E2E verification (2026-07-25).

"local" runs the exact same all-MiniLM-L6-v2 model HuggingFace's hosted API was going to serve,
but in-process on CPU via the `sentence-transformers` package -- no network call, no billing
gate, no external dependency at all. Added during REL-005 verification after Ollama's own
embedding call proved unreliable on this machine (a real ~17s failure investigated but not
resolved) and HuggingFace's hosted API was confirmed a dead end above. This is the default for
any environment where neither the account-tier gate nor local Ollama reliability can be assumed.
"""

from dataclasses import dataclass
from functools import lru_cache
from typing import Literal

import litellm

from src.core.config import Settings, get_settings

EmbeddingProvider = Literal["ollama", "huggingface", "local", "openai", "gemini"]

LOCAL_MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"


@dataclass(frozen=True)
class EmbeddingProviderConfig:
    model: str
    dim: int


# Add a new provider by adding one entry here plus one branch in _litellm_kwargs (or, for a
# non-litellm provider like "local", a branch in embed_texts) -- nothing else needs to change.
EMBEDDING_PROVIDERS: dict[EmbeddingProvider, EmbeddingProviderConfig] = {
    "ollama": EmbeddingProviderConfig(model="nomic-embed-text", dim=768),
    "huggingface": EmbeddingProviderConfig(model="sentence-transformers/all-MiniLM-L6-v2", dim=384),
    "local": EmbeddingProviderConfig(model=LOCAL_MODEL_NAME, dim=384),
    "openai": EmbeddingProviderConfig(model="text-embedding-3-small", dim=1536),
    "gemini": EmbeddingProviderConfig(model="text-embedding-004", dim=768),
}


class EmbeddingProviderNotConfiguredError(RuntimeError):
    pass


def get_embedding_dim(settings: Settings | None = None) -> int:
    settings = settings or get_settings()
    return EMBEDDING_PROVIDERS[settings.embedding_provider].dim


@lru_cache(maxsize=1)
def _local_model() -> "SentenceTransformer":  # type: ignore[name-defined] # noqa: F821
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(LOCAL_MODEL_NAME)


def _litellm_kwargs(settings: Settings) -> dict[str, str]:
    provider = settings.embedding_provider
    config = EMBEDDING_PROVIDERS[provider]

    if provider == "ollama":
        return {"model": f"ollama/{config.model}", "api_base": settings.ollama_base_url}
    if provider == "huggingface":
        if not settings.hf_token:
            raise EmbeddingProviderNotConfiguredError(
                "EMBEDDING_PROVIDER=huggingface but HF_TOKEN is not set"
            )
        return {"model": f"huggingface/{config.model}", "api_key": settings.hf_token}
    if provider == "openai":
        if not settings.openai_api_key:
            raise EmbeddingProviderNotConfiguredError(
                "EMBEDDING_PROVIDER=openai but OPENAI_API_KEY is not set"
            )
        return {"model": f"openai/{config.model}", "api_key": settings.openai_api_key}
    if provider == "gemini":
        if not settings.gemini_api_key:
            raise EmbeddingProviderNotConfiguredError(
                "EMBEDDING_PROVIDER=gemini but GEMINI_API_KEY is not set"
            )
        return {"model": f"gemini/{config.model}", "api_key": settings.gemini_api_key}
    raise ValueError(f"unknown embedding provider: {provider}")


def embed_text(text: str) -> list[float]:
    return embed_texts([text])[0]


def embed_texts(texts: list[str]) -> list[list[float]]:
    settings = get_settings()
    if settings.embedding_provider == "local":
        vectors = _local_model().encode(texts, convert_to_numpy=True)
        return [v.tolist() for v in vectors]
    response = litellm.embedding(input=texts, **_litellm_kwargs(settings))  # type: ignore[call-overload]
    return [item["embedding"] for item in response.data]
