"""Pushes the currently-configured LLM provider API keys (read from `.env`/Settings) into the
local dev Vault (src/core/vault.py) -- the same pattern as
scripts/seed_vault_broker_credentials.py, for LLM keys instead of broker credentials (REL-002
E2.2 gap closure). Run once per environment or whenever a key is rotated, via
`docker exec tradingos-app python scripts/seed_vault_llm_keys.py`.

After this runs, src/agents/llm_router.py resolves each provider's key from Vault instead of
directly from `.env` -- a real Vault-issued-credential retrieval path, not just a copy sitting
unused. `.env` remains the fallback if Vault is ever unreachable or a provider's Vault entry is
missing, so nothing breaks if this script hasn't been run yet. Ollama needs no key and is never
seeded.
"""

from src.core import vault
from src.core.config import get_settings

_PROVIDER_SETTINGS_FIELDS = {
    "openai": "openai_api_key",
    "anthropic": "anthropic_api_key",
    "deepseek": "deepseek_api_key",
    "gemini": "gemini_api_key",
    "huggingface": "hf_token",
    "opencode": "opencode_api_key",
}


def main() -> None:
    settings = get_settings()
    wrote_any = False

    for provider, field_name in _PROVIDER_SETTINGS_FIELDS.items():
        api_key = getattr(settings, field_name)
        if not api_key:
            print(f"{provider}: not configured in .env -- nothing to seed for it.")
            continue
        ok = vault.write_llm_provider_key(provider, api_key)
        print(f"{provider}: {'written to' if ok else 'FAILED to write to'} Vault.")
        wrote_any = wrote_any or ok

    if not wrote_any:
        print(
            "\nWARNING: nothing was written to Vault -- either no LLM provider is configured "
            "in .env, or Vault is unreachable (check VAULT_ADDR/VAULT_TOKEN and that the "
            "`vault` container is running)."
        )


if __name__ == "__main__":
    main()
