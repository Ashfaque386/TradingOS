#!/bin/sh
# REL-015 E15.1: real Vault init (scripts/vault_auto_unseal.py) generates a genuinely random
# root token, unlike the old fixed `dev-only-root-token` dev-mode value -- VAULT_TOKEN can no
# longer be a static docker-compose.yml env var. This wrapper reads the real token from the
# shared keys file vault_auto_unseal.py writes (both this container and that one already
# bind-mount the whole repo as /app, so no extra volume wiring is needed) and exports it before
# handing off to the real command.
#
# Waits up to 60s for the keys file to appear -- covers the real first-boot race (this
# container can start before vault-unsealer has finished a real `vault operator init` against a
# freshly-created data volume) -- then falls back to the legacy fixed token so the app still
# boots (Vault calls will honestly fail until unsealing catches up, rather than this script
# hanging forever).

ROOT_TOKEN_PATH="/app/vault/keys/root_token"
WAITED=0

while [ ! -f "$ROOT_TOKEN_PATH" ] && [ "$WAITED" -lt 60 ]; do
    sleep 2
    WAITED=$((WAITED + 2))
done

if [ -f "$ROOT_TOKEN_PATH" ]; then
    export VAULT_TOKEN="$(cat "$ROOT_TOKEN_PATH")"
else
    echo "docker-entrypoint-with-vault-token.sh: no real root token found after ${WAITED}s -- falling back to VAULT_TOKEN from the environment." >&2
fi

exec "$@"
