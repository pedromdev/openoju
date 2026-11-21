#!/usr/bin/env bash
# Roda o E2E completo contra um ambiente já provisionado.
#
#   ./scripts/cloud-e2e.sh aws val
#   ./scripts/cloud-e2e.sh azure val --minio
#
# Não provisiona nem destrói nada. Nunca roda no CI.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CLOUD="${1:-}"
ENV_NAME="${2:-}"
shift $(( $# >= 2 ? 2 : $# )) || true

PORT="18080"
MINIO=0
SKIP_HELM=0
VIDEO=""
USAGE="uso: $0 <aws|azure|gcp|magalu> <env> [--port N] [--minio] [--skip-helm] [--video arquivo]"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --port) PORT="${2:?}"; shift 2 ;;
    --minio) MINIO=1; shift ;;
    --skip-helm) SKIP_HELM=1; shift ;;
    --video) VIDEO="${2:?}"; shift 2 ;;
    -h|--help) echo "$USAGE"; exit 0 ;;
    *) echo "argumento desconhecido: $1" >&2; echo "$USAGE" >&2; exit 2 ;;
  esac
done

if [[ -z "$CLOUD" || -z "$ENV_NAME" ]]; then
  echo "$USAGE" >&2
  exit 2
fi

if [[ "${CI:-}" == "true" ]]; then
  echo "este script é apenas local; o CI usa kind e nunca credenciais de nuvem" >&2
  exit 2
fi

ENV_DIR="$ROOT/deploy/environments/$ENV_NAME"
if [[ ! -d "$ENV_DIR" ]]; then
  echo "ambiente não encontrado: $ENV_DIR (rode provision.py init/apply)" >&2
  exit 2
fi

if [[ -f "$ROOT/.secrets/$CLOUD.env" ]]; then
  # shellcheck disable=SC1090
  source "$ROOT/.secrets/$CLOUD.env"
else
  echo "aviso: .secrets/$CLOUD.env ausente; usando variáveis do shell" >&2
fi

KCFG="$ENV_DIR/kubeconfig.yaml"
if [[ ! -f "$KCFG" ]]; then
  KCFG="${KUBECONFIG:-$HOME/.kube/config}"
fi
export KUBECONFIG="$KCFG"

for binary in helm kubectl python3; do
  command -v "$binary" >/dev/null 2>&1 || { echo "falta $binary no PATH" >&2; exit 2; }
done

if [[ "$SKIP_HELM" -eq 0 ]]; then
  echo "== $ENV_NAME: helm upgrade (partes de 5 MiB) =="
  helm upgrade openoju "$ROOT/deploy/helm/openoju" -n openoju \
    -f "$ENV_DIR/values.yaml" \
    --set config.OJU_S3_PART_SIZE=5242880 \
    --set config.OJU_AZURE_BLOCK_SIZE=5242880 \
    --timeout 10m >/dev/null
fi

kubectl -n openoju rollout status deploy/openoju-openoju-api --timeout=600s >/dev/null
kubectl -n openoju rollout status deploy/openoju-openoju-worker --timeout=600s >/dev/null

cleanup() {
  [[ -n "${PF_API:-}" ]] && kill "$PF_API" 2>/dev/null || true
  [[ -n "${PF_MINIO:-}" ]] && kill "$PF_MINIO" 2>/dev/null || true
}
trap cleanup EXIT

echo "== $ENV_NAME: port-forward :$PORT =="
kubectl -n openoju port-forward svc/openoju-openoju "$PORT:8000" >/tmp/openoju-e2e-port.log 2>&1 &
PF_API=$!
if [[ "$MINIO" -eq 1 ]]; then
  kubectl -n openoju port-forward svc/openoju-openoju-minio 9000:9000 >/tmp/openoju-e2e-minio.log 2>&1 &
  PF_MINIO=$!
fi

for _ in $(seq 1 20); do
  curl -sf -m 3 "http://127.0.0.1:$PORT/api/health" >/dev/null 2>&1 && break
  sleep 2
done

if [[ -z "$VIDEO" ]]; then
  VIDEO="${TMPDIR:-/tmp}/openoju-e2e.mp4"
fi
if [[ ! -f "$VIDEO" ]]; then
  echo "== gerando vídeo de teste =="
  "$ROOT/scripts/make_sample.sh" "$VIDEO" 20 1280x720 5M >/dev/null
fi

TOKEN="$(kubectl -n openoju get secret openoju-secrets -o jsonpath='{.data.OJU_SETUP_TOKEN}' | base64 -d)"

echo "== $ENV_NAME: e2e =="
python3 "$ROOT/scripts/e2e.py" \
  --base-url "http://127.0.0.1:$PORT" \
  --token "$TOKEN" \
  --video "$VIDEO" \
  --log-reads 6 \
  --expect-multipart \
  --rate-limit

echo "== $ENV_NAME: helm test =="
helm test openoju -n openoju --timeout=300s | grep -E "Phase|PASSED|FAILED" || true
echo "== $ENV_NAME: OK =="
