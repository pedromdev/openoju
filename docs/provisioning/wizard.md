# Wizard de provisionamento

`scripts/provision.py` é stdlib puro: roda com `python3` sem venv.

## Comandos

| Comando | Função |
|---|---|
| `init` | perguntas e geração do ambiente |
| `doctor` | confere binários, kubeconfig, credenciais e arquivos |
| `render` | regenera `values.yaml` a partir de `answers.yaml` |
| `plan` | `terraform plan` + `helm template` (grava `render.yaml`) |
| `apply` | `terraform apply` → Secret → `helm upgrade` → rollout → `helm test` |
| `destroy` | `helm uninstall` + `terraform destroy` (exige digitar o nome) |

## Flags

```text
--env/-e NOME        ambiente (default: dev)
--target             local|onprem|aws|azure|gcp|magalu
--answers ARQUIVO    respostas prontas (modo não interativo)
--yes/-y             aceita todos os defaults
--force              sobrescreve ambiente existente
--verbose/-v         mais saída
```

## Credenciais por nuvem

O wizard não guarda segredo em `answers.yaml`. Ele carrega
`.secrets/<alvo>.env` automaticamente (veja `credentials.md`) e usa variáveis
já definidas no shell com prioridade. Para desligar o auto-load:

```bash
python3 scripts/provision.py apply --env prod --no-credentials
```

Variáveis esperadas por alvo:

| Alvo | Variáveis |
|---|---|
| AWS | `AWS_PROFILE` ou `AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY` |
| GCP | `GOOGLE_APPLICATION_CREDENTIALS` e `TF_VAR_project_id` |
| Azure | `ARM_CLIENT_ID`, `ARM_CLIENT_SECRET`, `ARM_TENANT_ID`, `ARM_SUBSCRIPTION_ID` |
| Magalu | `TF_VAR_mgc_api_key` e `TF_VAR_mgc_key_pair_id/secret` |

Passo a passo em [`credentials.md`](credentials.md).

## Modo não interativo

```bash
cp deploy/environments/prod/answers.yaml /tmp/answers.yaml
python3 scripts/provision.py init --env prod --answers /tmp/answers.yaml --yes
```

`answers.yaml` nunca contém segredos; `secrets.env` nunca é versionado.

`apply` grava os valores que só o Terraform conhece (bucket, endpoint, anotações
de IRSA/Workload Identity) em `outputs.json`. `render` reaplica esse arquivo,
então regenerar os values não perde o bucket real do provedor.

`destroy` tolera um cluster já removido: se o `helm uninstall` não alcançar o
API server (destroy parcial anterior), ele avisa e segue para o
`terraform destroy` do restante da infraestrutura.

## O que é gerado

```text
answers.yaml       respostas
values.yaml        valores do Helm
terraform.tfvars   variáveis do stack (quando aplicável)
secrets.env        segredos (600)
runbook.md         sequência e checklist
state.json         alvo, hash dos values e timestamp
render.yaml        manifesto do último plan
```

## Idempotência

`init` e `render` preservam segredos já existentes: só chaves ausentes são
geradas. `apply` reaplica o Secret com `kubectl apply`, então rotacionar um
segredo é editar `secrets.env` e rodar `apply`.
