#!/usr/bin/env bash
# Cria a service account usada pelo Terraform no GCP.
#
#   ./deploy/terraform/policies/gcp-setup.sh <project_id> [service-account-name]
#
# Requer gcloud autenticado com permissão para alterar IAM do projeto.
set -euo pipefail

PROJECT_ID="${1:?uso: $0 <project_id> [sa_name]}"
SA_NAME="${2:-openoju-tf}"
SA_EMAIL="${SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"

echo "==> projeto ${PROJECT_ID}"
gcloud config set project "${PROJECT_ID}" >/dev/null

echo "==> habilitando APIs"
gcloud services enable \
  compute.googleapis.com \
  container.googleapis.com \
  sqladmin.googleapis.com \
  storage.googleapis.com \
  iam.googleapis.com \
  cloudresourcemanager.googleapis.com \
  serviceusage.googleapis.com \
  logging.googleapis.com

echo "==> criando service account ${SA_EMAIL}"
if ! gcloud iam service-accounts describe "${SA_EMAIL}" >/dev/null 2>&1; then
  gcloud iam service-accounts create "${SA_NAME}" \
    --display-name "OpenOju Terraform" \
    --description "Provisiona GKE, Cloud SQL e GCS do OpenOju"
fi

ROLES=(
  roles/compute.admin
  roles/container.admin
  roles/cloudsql.admin
  roles/storage.admin
  roles/storage.hmacKeyAdmin
  roles/iam.serviceAccountAdmin
  roles/iam.serviceAccountUser
  roles/iam.serviceAccountKeyAdmin
  roles/resourcemanager.projectIamAdmin
  roles/serviceusage.serviceUsageAdmin
)

for role in "${ROLES[@]}"; do
  echo "    bind ${role}"
  gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
    --member "serviceAccount:${SA_EMAIL}" \
    --role "${role}" \
    --condition None >/dev/null
done

KEY_FILE="${PWD}/gcp-${SA_NAME}-key.json"
if [[ ! -f "${KEY_FILE}" ]]; then
  echo "==> gerando chave em ${KEY_FILE}"
  gcloud iam service-accounts keys create "${KEY_FILE}" --iam-account "${SA_EMAIL}"
  chmod 600 "${KEY_FILE}"
fi

cat <<MSG

Pronto.

  export GOOGLE_APPLICATION_CREDENTIALS=${KEY_FILE}
  export TF_VAR_project_id=${PROJECT_ID}

Valide com:

  gcloud auth application-default print-access-token >/dev/null && echo ok

A chave fica fora do controle de versão; guarde em cofre e remova com
\`gcloud iam service-accounts keys delete\` quando não precisar mais.
MSG
