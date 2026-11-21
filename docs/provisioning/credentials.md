# Credenciais por nuvem

O wizard usa **as CLIs oficiais** para autenticar; segredos nunca entram em
`answers.yaml`. Este guia cria o mínimo necessário para `terraform plan` e
`terraform apply` funcionarem.

```text
AWS      -> AWS_PROFILE (SSO) ou AWS_ACCESS_KEY_ID/AWS_SECRET_ACCESS_KEY
GCP      -> GOOGLE_APPLICATION_CREDENTIALS (service account) ou ADC
Azure    -> ARM_CLIENT_ID / ARM_CLIENT_SECRET / ARM_TENANT_ID / ARM_SUBSCRIPTION_ID
Magalu   -> TF_VAR_mgc_api_key (+ TF_VAR_mgc_key_pair_id/secret)
```

## Forma rápida (recomendada)

```bash
./scripts/cloud-setup.sh --cloud aws      # ou azure | gcp | magalu
eval "$(./scripts/cloud-env.sh aws)"      # opcional: exporta no shell atual
./scripts/cloud-setup.sh --check          # permissões + login
```

Os valores ficam em `.secrets/<nuvem>.env` (diretório 700, arquivos 600, no
`.gitignore`). O `provision.py` carrega esse arquivo automaticamente pelo alvo
do ambiente; use `--no-credentials` para desligar. Nada é impresso em claro.

> O CI **nunca** recebe essas credenciais: os jobs usam SQLite, Azurite e
> `kind`. Há um teste de guarda que falha se um workflow referenciar
> credenciais de nuvem.

Antes de começar:

- Use uma conta/projeto **dedicado** ao OpenOju. É mais fácil destruir e evita
  colisão de nomes (bucket S3 é global).
- Tenha `terraform >= 1.11`, `helm`, `kubectl` e a CLI da nuvem instalados.
- Nunca versione `secrets.env`, `*.tfstate`, chaves JSON ou service principals.

---

## AWS

### Opção A — SSO (recomendado)

```bash
aws configure sso --profile openoju
# SSO session name, start URL, region (ex.: us-east-1), account, role
aws sso login --profile openoju
export AWS_PROFILE=openoju
aws sts get-caller-identity
```

Anexe a política de provisionamento à role usada no SSO.

### Opção B — usuário de serviço

```bash
# 1. política
aws iam create-policy \
  --policy-name OpenOjuProvisioning \
  --policy-document file://deploy/terraform/policies/aws-provisioning.json

# 2. usuário e vínculo (substitua o ARN retornado)
aws iam create-user --user-name openoju-tf
aws iam attach-user-policy --user-name openoju-tf \
  --policy-arn arn:aws:iam::<ACCOUNT_ID>:policy/OpenOjuProvisioning

# 3. credenciais (aparecem uma única vez)
aws iam create-access-key --user-name openoju-tf
export AWS_ACCESS_KEY_ID=...
export AWS_SECRET_ACCESS_KEY=...
```

A política cobre VPC, EKS, IAM (roles e OIDC provider), RDS, S3, ELB, logs e
KMS. Ela é ampla por natureza: EKS exige `iam:PassRole` e criação de roles. Em
produção, depois do primeiro apply, restrinja por `Resource`/condições ou separe
uma role só para o state.

### Root não serve para o EKS

O usuário root autentica o Terraform (via `aws login`), mas **não é um principal
válido no EKS** e também não pode assumir roles. Para o `kubectl`/Helm
funcionarem, crie um usuário IAM de validação:

```bash
aws iam create-user --user-name openoju-val-admin
aws iam attach-user-policy --user-name openoju-val-admin \
  --policy-arn arn:aws:iam::aws:policy/AdministratorAccess
aws iam create-access-key --user-name openoju-val-admin
```

Exporte as chaves em um arquivo `600` e use esse usuário no `apply`. O módulo
cria a access entry do criador e habilita
`bootstrap_cluster_creator_admin_permissions`, então o `update-kubeconfig`
funciona de imediato. Ao terminar, apague o usuário:

```bash
aws iam delete-access-key --user-name openoju-val-admin --access-key-id <id>
aws iam detach-user-policy --user-name openoju-val-admin \
  --policy-arn arn:aws:iam::aws:policy/AdministratorAccess
aws iam delete-user --user-name openoju-val-admin
```

### Verificação e limites

```bash
aws sts get-caller-identity
aws ec2 describe-availability-zones --region us-east-1 \
  --query 'AvailabilityZones[].ZoneName' --output text
aws service-quotas get-service-quota \
  --service-code ec2 --quota-code L-1216C47A \
  --query 'Quota.Value'   # vCPUs On-Demand
```

- Bucket S3 tem nome global: o wizard usa `openoju-<ambiente>`; se colidir,
  ajuste `bucket_name` no módulo.
- O EKS consome 2 nós `system` + `node_count` nós `app`. Confira a cota de vCPU.
- `db.t4g.medium` é o padrão; troque por `db.m5.large` se precisar de mais IOPS.

---

## GCP

### Script pronto

```bash
./deploy/terraform/policies/gcp-setup.sh <project_id>
export GOOGLE_APPLICATION_CREDENTIALS=$PWD/gcp-openoju-tf-key.json
export TF_VAR_project_id=<project_id>
```

O script habilita as APIs (Compute, GKE, Cloud SQL, Storage, IAM) e cria a
service account `openoju-tf` com:

| Role | Para quê |
|---|---|
| `compute.admin` | VPC, subnets, NAT |
| `container.admin` | GKE, node pools |
| `cloudsql.admin` | Cloud SQL |
| `storage.admin` + `storage.hmacKeyAdmin` | bucket, CORS e HMAC keys |
| `iam.serviceAccountAdmin/User/KeyAdmin` | GSA, Workload Identity, chaves |
| `resourcemanager.projectIamAdmin` | bindings de IAM |
| `serviceusage.serviceUsageAdmin` | habilitar APIs futuras |

### Alternativa — ADC (uso pessoal)

```bash
gcloud auth login
gcloud auth application-default login
gcloud config set project <project_id>
export TF_VAR_project_id=<project_id>
```

ADC funciona, mas usa sua identidade: prefira a service account para CI.

### Verificação

```bash
gcloud auth application-default print-access-token >/dev/null && echo ok
gcloud services list --enabled --filter='config.name:(container.googleapis.com OR sqladmin.googleapis.com OR storage.googleapis.com)'
gcloud compute regions describe us-central1 --format='value(quotas)' | head -c 300
```

- O GCS entra por interoperabilidade S3 com HMAC keys (criadas pelo stack).
- `OJU_S3_REGION=auto` e endpoint `https://storage.googleapis.com`.
- Workload Identity exige o pool `<project>.svc.id.goog` (criado pelo GKE).

---

## Azure

### Script pronto

```bash
az login
./deploy/terraform/policies/azure-setup.sh <subscription_id>
```

O script:

1. seleciona a subscription;
2. registra `Microsoft.ContainerService`, `Microsoft.DBforPostgreSQL`,
   `Microsoft.ManagedIdentity`, `Microsoft.Network`, `Microsoft.Compute`;
3. cria o service principal `openoju-tf` com `Contributor` na subscription;
4. grava `azure-openoju-tf.json` (600) e imprime os `export`.

Exporte manualmente os quatro valores:

```bash
export ARM_CLIENT_ID=$(python3 -c 'import json;print(json.load(open("azure-openoju-tf.json"))["clientId"])')
export ARM_CLIENT_SECRET=$(python3 -c 'import json;print(json.load(open("azure-openoju-tf.json"))["clientSecret"])')
export ARM_TENANT_ID=$(python3 -c 'import json;print(json.load(open("azure-openoju-tf.json"))["tenantId"])')
export ARM_SUBSCRIPTION_ID=<subscription_id>
```

`Contributor` cobre AKS, Postgres Flexible Server e a identidade gerenciada
(inclusive a credencial federada usada pelo Workload Identity).

### Verificação e cota

```bash
az account show --query '{name:name,id:id,tenant:tenantId}' -o table
az vm list-usage -l brazilsouth -o table | grep -i ddsv5
az provider show -n Microsoft.ContainerService --query registrationState -o tsv
```

- O padrão usa `Standard_D2ds_v5` (system) e `Standard_D4ds_v5` (app). A cota de
  vCPU em `brazilsouth` costuma ser baixa em contas novas; peça aumento antes.
- Zona `1` é usada no Postgres; se a região não tiver zonas, remova `zone` no
  stack.

---

## Magalu Cloud (experimental)

A Magalu usa **API key** para a API e um **key pair** para o Object Storage
(S3). Os dois saem do mesmo fluxo de criação: ao marcar escopos de Object
Storage, o console mostra o API Key e o Key Pair (ID + Secret).

### 1. Criar a API key no console

1. Abra **https://id.magalu.com/api-keys** (Magalu ID) e autentique.
2. Clique em **Create API Key**.
3. Nome: `openoju-val`.
4. Expiração: 30 dias para validação (ou 90 em produção).
5. Marque as aplicações/escopos:
   - **MKE (Kubernetes)** — *Resources creation*
   - **ID Magalu** — *Manage service accounts* (o MKE cria recursos em seu nome)
   - **DBaaS** — criar instância PostgreSQL
   - **Object Storage** — *Read* e *Write*
   - **Network** e **Block Storage** — VPC/subnets e volumes do cluster
   - **Container Registry** — se for publicar a imagem no registry da Magalu
6. Copie o **API Key** (aparece uma única vez) e salve o **Key Pair ID** e o
   **Key Pair Secret** exibidos no mesmo fluxo.

### 2. Exportar no terminal

```bash
umask 077
cat > ~/.config/openoju-magalu.env <<'ENV'
export TF_VAR_mgc_api_key='...'
export TF_VAR_mgc_key_pair_id='...'
export TF_VAR_mgc_key_pair_secret='...'
ENV
chmod 600 ~/.config/openoju-magalu.env
source ~/.config/openoju-magalu.env
```

O `key_pair_id` é o *access key* do S3 e o secret é a senha; os três valores
são sensíveis. Nunca versione.

### 3. Verificar

```bash
terraform -chdir=deploy/terraform/stacks/magalu init -backend=false
terraform -chdir=deploy/terraform/stacks/magalu plan \
  -var-file=deploy/environments/val-magalu/terraform.tfvars
```

Uma API key inválida falha com `401` antes de criar qualquer recurso. O
`provision.py doctor` também exige `TF_VAR_mgc_api_key`.

### 4. CLI (rotação e chaves adicionais)

Depois de ter uma API key válida:

```bash
mgc auth api-key create --name=openoju-val-2
mgc auth api-key get <uuid>   # mostra API key e key pair
```

### Região e endpoint

Regiões: `br-se1` (São Paulo, padrão), `br-ne1`, `br-mgl1`, `br-mc1`.
O endpoint S3 é `https://<região>.magaluobjects.com`.

> Sem `ReadWriteMany` na Magalu: mantenha `media.mode=emptyDir` e
> `OJU_STORAGE_BACKEND=s3` (o preset já faz isso).

## Depois de criar as credenciais

```bash
# GCP e Azure exigem o identificador do projeto/subscription:
python3 scripts/provision.py init --env prod --target gcp \
  --gcp-project <project_id>
python3 scripts/provision.py init --env prod --target azure \
  --azure-subscription <subscription_id>

# AWS e Magalu não pedem identificador extra (Magalu lê TF_VAR_mgc_api_key):
python3 scripts/provision.py init --env prod --target aws
python3 scripts/provision.py init --env prod --target magalu

python3 scripts/provision.py doctor --env prod
python3 scripts/provision.py plan   --env prod
python3 scripts/provision.py apply  --env prod
```

O `doctor` valida a identidade de cada nuvem e avisa quando falta
`gcp_project`, `azure_subscription` ou `TF_VAR_mgc_api_key`.

## Segurança

- `chmod 600` em `secrets.env`, chaves JSON e service principals; todos já estão
  no `.gitignore` (ou deveriam: confirme).
- Rotacione credenciais a cada 90 dias ou após qualquer vazamento.
- Configure backend remoto de state (S3/GCS/Azure Blob) antes de trabalho em
  equipe; o state contém a senha do banco.
- Para produção, use uma conta/projeto por ambiente (`prod`, `staging`).

## Troubleshooting

| Sintoma | Causa provável | Correção |
|---|---|---|
| `Unable to locate credentials` | perfil/env AWS ausente | `aws sso login --profile openoju` + `AWS_PROFILE` |
| `AccessDenied` ao criar role | IAM limitado | anexe `OpenOjuProvisioning` ou `IAMFullAccess` |
| `InvalidClientSecret` (Azure) | secret expirado/rotacionado | `az ad sp credential reset --id <clientId>` |
| `403` no plan da Magalu | API key sem escopo | recrie a chave com MKE + DBaaS + Object Storage |
| `project_id` vazio | respostas incompletas | edite `answers.yaml` e rode `render` |
| `subscription_id` divergente | `az account set` em outra conta | `az account set -s <id>` |
| `Quota exceeded` (vCPU) | cota baixa na região | peça aumento ou use região maior |
| Bucket já existe | nome global S3 | mude `bucket_name`/ambiente |
