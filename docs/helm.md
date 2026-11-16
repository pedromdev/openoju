# Helm

## Instalação rápida

```bash
helm upgrade --install openoju deploy/helm/openoju \
  --namespace openoju --create-namespace \
  -f deploy/helm/openoju/values-minimal.yaml
```

O preset `minimal` sobe Postgres e MinIO embutidos e gera o Secret com
`secrets.create=true`. Bom para avaliação em um único nó.

## Perfis disponíveis

| Arquivo | Alvo | Banco | Object storage | VAAPI |
|---|---|---|---|---|
| `values-minimal.yaml` | laboratório | embutido | embutido | não |
| `values-onprem.yaml` | k3s/RKE2/Talos | embutido | embutido | sim |
| `values-aws.yaml` | EKS | RDS | S3 + IRSA | não |
| `values-gcp.yaml` | GKE | Cloud SQL | GCS (interop) | não |
| `values-azure.yaml` | AKS | Flexible Server | MinIO no cluster | não |
| `values-magalu.yaml` | MKE (experimental) | DBaaS | Object Storage | não |

Os presets de nuvem esperam que `deploy/terraform/stacks/<cloud>` já tenha
criado banco, bucket e role. Use `scripts/provision.py` para gerar o
`values.yaml` a partir dos outputs do Terraform.

## Secret

Em produção o Secret é criado fora do chart:

```bash
kubectl -n openoju create secret generic openoju-secrets \
  --from-literal=OJU_DATABASE_URL='postgresql+psycopg://...' \
  --from-literal=OJU_SECRET_KEY='...' \
  --from-literal=OJU_FERNET_KEY='...' \
  --from-literal=OJU_SETUP_TOKEN='...' \
  --from-literal=OJU_S3_ACCESS_KEY='...' \
  --from-literal=OJU_S3_SECRET_KEY='...' \
  --from-literal=OJU_OIDC_CLIENT_SECRET='...'
```

`secrets.create=true` gera as chaves com `randAlphaNum` e preserva as já
existentes via `lookup`. Use apenas em desenvolvimento: qualquer `helm
uninstall` sem `--keep-history` remove o Secret.

## Migrations

O chart roda `alembic upgrade head` em um Job de hook. A API **não** migra no
start, então `replicaCount.api` pode passar de 1 sem corrida de migrations.

O hook é `pre-install,pre-upgrade` quando o Secret já existe e o banco é externo
(produção). Ele vira `post-install,pre-upgrade` quando:

- `secrets.create=true` (dev/minimal) — o Secret só existe com o release; ou
- `postgresql.enabled=true` — o Service do Postgres só existe depois que o
  StatefulSet é criado.

Nesses casos a API sobe antes das migrations e pode reiniciar por alguns
segundos até o Job concluir.

Para desligar (por exemplo, quando as migrations rodam fora do Helm):

```bash
--set migrations.enabled=false
```

## MinIO embutido

`minio.persistence.mode=emptyDir` usa um volume em memória (efêmero) e é o modo
recomendado para CI e laboratório. Em produção use `pvc`, preferencialmente em um
disco premium.

## Volumes

- `media.mode=pvc` — backend de storage local; exige volume compartilhado.
- `media.mode=emptyDir` — backend S3/GCS/Object Storage; usa rascunho por pod.
- `data.mode=emptyDir` — recomendado sempre que `OJU_STORAGE_BACKEND=s3`, já que
  logs de job vão para o object storage.

`emptyDir.sizeLimit` precisa caber o maior vídeo importado pelo upload em
partes (`OJU_UPLOAD_MAX_BYTES`).

## Alta disponibilidade

| Item | Requisito |
|---|---|
| `replicaCount.api > 1` | `OJU_RATE_LIMIT_BACKEND=postgres` |
| `replicaCount.worker > 1` | nenhum (fila usa `SKIP LOCKED`) |
| `pdb.enabled=true` | `replicaCount` do componente > 1 |
| RWX | apenas se `media.mode=pvc` |

## VAAPI

`vaapi.enabled=true` monta `/dev/dri` via `hostPath` e adiciona
`supplementalGroups`. Em nuvem mantenha `false`: o worker cai para CPU e evita
pods presos em `Pending`.

## Falha em hook de install

Se o primeiro `install` falhar em um hook, o release fica em estado `failed`.
Um `helm upgrade --install` seguinte roda os hooks de **pre-upgrade**, que
executam antes dos recursos do release — com Postgres embutido isso repete o
erro (`failed to resolve host ...-postgresql`). Antes de tentar de novo:

```bash
helm uninstall <release> -n <ns>
kubectl -n <ns> delete job <release>-openoju-migrate --ignore-not-found
```

## Verificação

```bash
helm test openoju -n openoju
```

O teste consulta `/api/health` de dentro do cluster e aceita `ok` ou
`degraded` (volume de mídia ausente).

## Notas por provedor

- **AWS**: anote a ServiceAccount com a role IRSA; o ALB precisa de
  `idle_timeout` alto para downloads longos.
- **GCP**: o GCS em modo interoperabilidade exige HMAC keys e
  `addressing_style: path` (já configurado no código). Use `OJU_S3_REGION=auto`.
- **Azure**: Blob não é S3; o preset sobe MinIO e expõe `minio.public.host`
  para as URLs assinadas.
- **Magalu**: não há RWX; mantenha `media.mode=emptyDir` e
  `OJU_STORAGE_BACKEND=s3`.
