#!/usr/bin/env bash
# Configura credenciais locais para validação em nuvem.
#
#   ./scripts/cloud-setup.sh --cloud aws
#   ./scripts/cloud-setup.sh --check
#
# Os valores ficam em .secrets/<cloud>.env (700/600, no .gitignore).
# O script nunca imprime segredos.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SECRETS="$ROOT/.secrets"
umask 077

CLOUD=""
CHECK=0
FORCE=0

usage() {
  cat <<'EOF'
Uso: scripts/cloud-setup.sh [--cloud aws|azure|gcp|magalu] [--check] [--force]

  --cloud   configura (ou valida) uma nuvem
  --check   apenas verifica permissões, variáveis e login
  --force   reescreve o arquivo existente

Sem --cloud, pergunta qual configurar.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --cloud) CLOUD="${2:-}"; shift 2 ;;
    --check) CHECK=1; shift ;;
    --force) FORCE=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "argumento desconhecido: $1" >&2; usage; exit 2 ;;
  esac
done

ensure_dir() {
  mkdir -p "$SECRETS"
  chmod 700 "$SECRETS"
}

mask() {
  local value="$1"
  if [[ -z "$value" ]]; then
    printf '<vazio>'
  else
    printf '<%s caracteres>' "${#value}"
  fi
}

write_env() {
  local cloud="$1"; shift
  local file="$SECRETS/$cloud.env"
  if [[ -f "$file" && "$FORCE" -eq 0 ]]; then
    echo "  mantendo $file (use --force para reescrever)"
    return
  fi
  {
    echo "# Gerado por scripts/cloud-setup.sh — não versionar."
    for line in "$@"; do
      echo "export $line"
    done
  } > "$file"
  chmod 600 "$file"
  echo "  gravado $file"
}

ask() {
  local prompt="$1" default="$2" answer
  if [[ -t 0 ]]; then
    read -r -p "$prompt [$default]: " answer || true
    echo "${answer:-$default}"
  else
    echo "$default"
  fi
}

ask_secret() {
  local prompt="$1" answer
  if [[ -t 0 ]]; then
    read -r -s -p "$prompt: " answer || true
    echo >&2
    echo "$answer"
  else
    echo ""
  fi
}

setup_aws() {
  echo "AWS"
  local profile region
  profile="$(ask "Profile" "${AWS_PROFILE:-openoju}")"
  region="$(ask "Região" "${AWS_REGION:-us-east-1}")"
  write_env aws "AWS_PROFILE=$profile" "AWS_REGION=$region" "AWS_DEFAULT_REGION=$region"
  if command -v aws >/dev/null 2>&1; then
    if ! aws sts get-caller-identity --profile "$profile" >/dev/null 2>&1; then
      echo "  aviso: credenciais ainda inválidas. Rode:"
      echo "    aws login --profile $profile   (ou aws configure sso --profile $profile)"
    fi
  else
    echo "  aviso: aws CLI não encontrada no PATH"
  fi
}

setup_azure() {
  echo "Azure"
  if ! command -v az >/dev/null 2>&1; then
    echo "  aviso: az CLI não encontrada no PATH"
    return
  fi
  local subscription tenant
  subscription="$(az account show --query id -o tsv 2>/dev/null || true)"
  tenant="$(az account show --query tenantId -o tsv 2>/dev/null || true)"
  if [[ -z "$subscription" ]]; then
    echo "  aviso: sem sessão. Rode:"
    echo "    az login --tenant aae54b12-077a-46ae-abe1-1a03fb48ae4e"
    return
  fi
  write_env azure "AZURE_SUBSCRIPTION_ID=$subscription" "AZURE_TENANT_ID=$tenant"
}

setup_gcp() {
  echo "GCP"
  if ! command -v gcloud >/dev/null 2>&1; then
    echo "  aviso: gcloud não encontrada no PATH"
    return
  fi
  local project
  project="$(gcloud config get-value project 2>/dev/null || true)"
  if [[ -z "$project" || "$project" == "(unset)" ]]; then
    project="$(ask "Projeto GCP" "")"
  fi
  if [[ -z "$project" ]]; then
    echo "  aviso: defina o projeto com gcloud config set project <id>"
    return
  fi
  if ! gcloud auth application-default print-access-token >/dev/null 2>&1; then
    echo "  aviso: ADC ausente. Rode: gcloud auth application-default login"
  fi
  write_env gcp "GOOGLE_CLOUD_PROJECT=$project" "TF_VAR_project_id=$project"
}

setup_magalu() {
  echo "Magalu Cloud"
  local api_key key_id key_secret region
  api_key="$(ask_secret "API key")"
  key_id="$(ask_secret "Object Storage key pair ID")"
  key_secret="$(ask_secret "Object Storage key pair secret")"
  region="$(ask "Região" "${MGC_REGION:-br-se1}")"
  if [[ -z "$api_key" ]]; then
    echo "  aviso: API key vazia; nada gravado"
    return
  fi
  echo "  API key: $(mask "$api_key")"
  write_env magalu \
    "TF_VAR_mgc_api_key=$api_key" \
    "TF_VAR_mgc_key_pair_id=$key_id" \
    "TF_VAR_mgc_key_pair_secret=$key_secret" \
    "MGC_REGION=$region"
}

check_permissions() {
  local problems=0
  if [[ ! -d "$SECRETS" ]]; then
    echo "  .secrets/ ausente (rode scripts/cloud-setup.sh)"
    return 1
  fi
  local dir_mode
  dir_mode="$(stat -c '%a' "$SECRETS")"
  if [[ "$dir_mode" != "700" ]]; then
    echo "  .secrets/ com permissão $dir_mode (esperado 700)"
    problems=1
  fi
  local file
  for file in "$SECRETS"/*.env; do
    [[ -e "$file" ]] || continue
    local mode
    mode="$(stat -c '%a' "$file")"
    if [[ "$mode" != "600" ]]; then
      echo "  $(basename "$file") com permissão $mode (esperado 600)"
      problems=1
    fi
    if ! bash -n "$file" 2>/dev/null; then
      echo "  $(basename "$file") com sintaxe inválida"
      problems=1
    fi
  done
  return "$problems"
}

check_cloud() {
  local cloud="$1" file="$SECRETS/$1.env"
  if [[ ! -f "$file" ]]; then
    echo "  $file ausente"
    return 1
  fi
  # shellcheck disable=SC1090
  source "$file"
  case "$cloud" in
    aws)
      if command -v aws >/dev/null 2>&1 && aws sts get-caller-identity --profile "${AWS_PROFILE:-}" >/dev/null 2>&1; then
        echo "  aws: ok (profile ${AWS_PROFILE:-})"
        return 0
      fi
      echo "  aws: credenciais inválidas (rode aws login)"
      return 1
      ;;
    azure)
      if command -v az >/dev/null 2>&1 && az account show --query id -o tsv >/dev/null 2>&1; then
        echo "  azure: ok (${AZURE_SUBSCRIPTION_ID:-})"
        return 0
      fi
      echo "  azure: sem sessão (rode az login)"
      return 1
      ;;
    gcp)
      if command -v gcloud >/dev/null 2>&1 && gcloud auth application-default print-access-token >/dev/null 2>&1; then
        echo "  gcp: ok (${GOOGLE_CLOUD_PROJECT:-})"
        return 0
      fi
      echo "  gcp: sem ADC (rode gcloud auth application-default login)"
      return 1
      ;;
    magalu)
      if [[ -n "${TF_VAR_mgc_api_key:-}" ]]; then
        echo "  magalu: api key presente ($(mask "$TF_VAR_mgc_api_key"))"
        return 0
      fi
      echo "  magalu: api key ausente"
      return 1
      ;;
  esac
}

if [[ "$CHECK" -eq 1 ]]; then
  echo "Verificando .secrets/"
  rc=0
  check_permissions || rc=1
  if [[ -n "$CLOUD" ]]; then
    check_cloud "$CLOUD" || rc=1
  else
    for cloud in aws azure gcp magalu; do
      [[ -f "$SECRETS/$cloud.env" ]] && { check_cloud "$cloud" || rc=1; }
    done
  fi
  exit "$rc"
fi

ensure_dir
if [[ -z "$CLOUD" ]]; then
  CLOUD="$(ask "Nuvem (aws/azure/gcp/magalu)" "aws")"
fi
case "$CLOUD" in
  aws) setup_aws ;;
  azure) setup_azure ;;
  gcp) setup_gcp ;;
  magalu) setup_magalu ;;
  *) echo "nuvem inválida: $CLOUD" >&2; exit 2 ;;
esac
echo "pronto. Use: eval \"\$(./scripts/cloud-env.sh $CLOUD)\""
