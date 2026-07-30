#!/usr/bin/env bash
# REL-009 E9.3: wrapper so the pre-commit gitleaks hook gets a real, resolved absolute path for
# the bind mount. Real bug found running this repo's own pre-commit hooks on Windows: pre-commit's
# "system" hooks execute the `entry:` command directly (not through a shell that performs
# variable substitution), so the literal `${PWD}` string was being passed straight to `docker run
# -v` instead of being expanded -- confirmed via the real error `create ${PWD}: "${PWD}" includes
# invalid characters for a local volume name`. This script IS invoked through bash (pre-commit
# runs `bash scripts/run_gitleaks.sh`), so `$(pwd)` here is resolved by bash itself.
set -euo pipefail
MSYS_NO_PATHCONV=1 docker run --rm -v "$(pwd):/repo" zricethezav/gitleaks:latest detect --source /repo --config /repo/.gitleaks.toml -v
