# Provisionamento

O OpenOju roda em Kubernetes, em nuvem ou on-premise. O Compose na raiz é
apenas para desenvolvimento local.

## Matriz

| Alvo | Cluster | Banco | Object storage | Ingress | Status |
|---|---|---|---|---|---|
| Local | kind/k3d | embutido | embutido | port-forward | validado |
| On-premise | k3s/RKE2/Talos | embutido | embutido | nginx + cert-manager | primeira execução pendente |
| AWS | EKS | RDS PG16 | S3 + IRSA | ALB + ACM | primeira execução pendente |
| GCP | GKE | Cloud SQL | GCS interop | GCLB | primeira execução pendente |
| Azure | AKS | Flexible Server | MinIO no cluster | nginx + cert-manager | primeira execução pendente |
| Magalu | MKE | DBaaS PG | Object Storage | nginx + LB addon | experimental |

## Requisitos por alvo

Terraform >= 1.11 é obrigatório: o provider da Magalu usa atributos
*write-only* para usuário e senha do banco.

| Alvo | Terraform | Ferramentas locais |
|---|---|---|
| Local | não | docker, kind, helm, kubectl |
| On-premise | não (cloud-init) | helm, kubectl, acesso ao cluster |
| AWS | sim | terraform, aws, helm, kubectl |
| GCP | sim | terraform, gcloud, helm, kubectl |
| Azure | sim | terraform, az, helm, kubectl |
| Magalu | sim | terraform, mgc (opcional), helm, kubectl |

## Contrato de outputs do Terraform

Todos os stacks exportam o mesmo conjunto, e é isso que o wizard consome:

```hcl
cluster_name                = "openoju-prod"
cluster_endpoint            = "https://..."
database_url                = "postgresql+psycopg://..."   # sensitive
bucket                      = "openoju-prod"
service_account_annotations = { "eks.amazonaws.com/role-arn" = "arn:..." }
```

## Decisões que o wizard toma por você

| Resposta | Efeito |
|---|---|
| `api_replicas > 1` | `OJU_RATE_LIMIT_BACKEND=postgres` + PDB |
| `storage=managed` | `media.mode=emptyDir` (sem RWX) e backend nativo (Azure Blob) |
| `storage=bundled` | MinIO com PVC + Ingress público para presign |
| `tls=cert-manager` | anotações de issuer e Secret TLS |
| `vaapi=on` | `hostPath /dev/dri` + `supplementalGroups` |
| `database=bundled` | Postgres StatefulSet + `OJU_DATABASE_URL` gerado |

## Pós-instalação (todos os alvos)

1. DNS aponta para o ingress/LB.
2. CORS do bucket inclui a origem pública (obrigatório para upload direto).
3. Token de setup aplicado em `POST /api/v1/auth/setup`.
4. Upload de vídeo e análise concluídos.
5. `/api/v1/jobs/{id}/log` responde com a API em outra réplica.
