# REL-015 E15.1 (GLH-01): real Vault server config, replacing `-dev` mode.
#
# `-dev` mode is always in-memory by Vault's own design -- there is no flag that makes it
# persistent, so GLH-01 ("Vault survives a restart with persistent storage") could never be
# closed while running in dev mode. The `file` storage backend below is the simplest real,
# persistent backend for a single-node Docker Compose host (no Consul/Raft cluster needed) --
# proportionate to this project's permanent single-environment model (Phase 1 ADR 10).
#
# TLS is intentionally disabled on this listener: this is the same internal-only Docker bridge
# network every other Postgres/Redis/Qdrant connection already stays inside (see
# docker-compose.yml's own `app-tls` service comment on why TLS between internal services is out
# of scope for this single-host topology), not a new gap this file introduces.

storage "file" {
  # /vault/file, not an arbitrary path: the official image's own docker-entrypoint.sh only
  # auto-chowns /vault/config, /vault/logs, and /vault/file to the non-root `vault` user it
  # su-exec's into -- any other path (confirmed the hard way: /vault/data failed with a real
  # "mkdir /vault/data/core: permission denied" against a fresh named volume, since Docker
  # creates new named volumes root-owned by default) needs a manual chown this config avoids by
  # just using the path the entrypoint already knows about.
  path = "/vault/file"
}

listener "tcp" {
  address     = "0.0.0.0:8200"
  tls_disable = "true"
}

# Real Vault UI at http://localhost:8200/ui -- useful for a human to inspect seal/init status
# directly, same convenience `-dev` mode already provided.
ui = true

# The default -- real, initial storage location this data is looked up from, not overridden.
api_addr = "http://vault:8200"

# Found and fixed investigating a real, reproduced CI-only hang: Vault's default (mlock enabled)
# requires the `mlock` syscall to succeed, which needs both the `IPC_LOCK` capability
# (docker-compose.yml's `vault` service already grants this) AND a sufficient `RLIMIT_MEMLOCK`
# ulimit -- GitHub-hosted `ubuntu-latest` runners default to a low one (64KB), which this local
# dev host's own Docker Desktop VM does not. Reproduced directly: `docker run --ulimit
# memlock=65536:65536 --cap-add=IPC_LOCK ... vault server` fails immediately with "Error
# initializing core: Failed to lock memory: cannot allocate memory" -- exactly Vault's own
# documented error for this condition, and exactly why every recent CI run silently hung forever
# on "Wait for Vault" (Vault's HTTP listener never opened at all, so nothing was ever there to
# heal or unseal). Confirmed the fix the same way: the identical constrained-ulimit repro starts
# cleanly with this line added. Accepted tradeoff, stated plainly (same class already accepted
# for the unseal key living in a plaintext file, see scripts/vault_auto_unseal.py's own module
# docstring): Vault's own protection against ITS OWN memory being swapped to disk is disabled --
# proportionate for this project's single-host, non-adversarial threat model (Phase 1 ADR 10),
# not a new category of risk this single-operator environment doesn't already accept elsewhere.
disable_mlock = true
