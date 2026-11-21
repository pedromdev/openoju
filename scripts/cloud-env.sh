#!/usr/bin/env bash
# Emite os exports de .secrets/<cloud>.env.
#
#   eval "$(./scripts/cloud-env.sh aws)"
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CLOUD="${1:-}"

if [[ -z "$CLOUD" ]]; then
  echo "uso: $0 aws|azure|gcp|magalu" >&2
  exit 2
fi

FILE="$ROOT/.secrets/$CLOUD.env"
if [[ ! -f "$FILE" ]]; then
  echo "arquivo ausente: .secrets/$CLOUD.env" >&2
  echo "rode: ./scripts/cloud-setup.sh --cloud $CLOUD" >&2
  exit 1
fi

grep -E '^export [A-Za-z_][A-Za-z0-9_]*=' "$FILE"
