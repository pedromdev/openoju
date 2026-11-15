#!/usr/bin/env bash
# Cria o service principal usado pelo Terraform no Azure.
#
#   ./deploy/terraform/policies/azure-setup.sh <subscription_id> [nome]
#
# Requer az login com permissão de Owner/Contributor + User Access Administrator
# na subscription.
set -euo pipefail

SUBSCRIPTION_ID="${1:?uso: $0 <subscription_id> [nome]}"
NAME="${2:-openoju-tf}"

echo "==> selecionando subscription ${SUBSCRIPTION_ID}"
az account set --subscription "${SUBSCRIPTION_ID}"
az account show --query '{name:name, id:id, tenant:tenantId}' -o table

echo "==> registrando providers"
for ns in Microsoft.ContainerService Microsoft.DBforPostgreSQL Microsoft.ManagedIdentity Microsoft.Network Microsoft.Compute; do
  az provider register --namespace "${ns}" --wait >/dev/null
done

echo "==> criando service principal ${NAME}"
CREDS=$(az ad sp create-for-rbac \
  --name "${NAME}" \
  --role Contributor \
  --scopes "/subscriptions/${SUBSCRIPTION_ID}" \
  --query '{clientId:appId, clientSecret:password, tenantId:tenant}' \
  -o json)

CRED_FILE="${PWD}/azure-${NAME}.json"
umask 077
printf '%s\n' "${CREDS}" > "${CRED_FILE}"
chmod 600 "${CRED_FILE}"

cat <<MSG

Pronto. Credenciais salvas em ${CRED_FILE} (600, não versione).

Exporte com:

  export ARM_CLIENT_ID=\$(python3 -c 'import json,sys;print(json.load(open("${CRED_FILE}"))["clientId"])')
  export ARM_CLIENT_SECRET=\$(python3 -c 'import json,sys;print(json.load(open("${CRED_FILE}"))["clientSecret"])')
  export ARM_TENANT_ID=\$(python3 -c 'import json,sys;print(json.load(open("${CRED_FILE}"))["tenantId"])')
  export ARM_SUBSCRIPTION_ID=${SUBSCRIPTION_ID}

Se perder o secret, gere outro:

  az ad sp credential reset --id <clientId> --query password -o tsv

Confira a cota de vCPU na região antes do apply:

  az vm list-usage -l brazilsouth -o table | grep -i ddsv5
MSG
