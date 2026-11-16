# GCP

GKE + Cloud SQL + GCS (modo interoperabilidade) + GCLB.

## Pré-requisitos

- Projeto com APIs de GKE, Cloud SQL, Storage e IAM habilitadas.
- `gcloud auth application-default login`.
- Terraform >= 1.7, `helm`, `kubectl`.
- IP global estático e certificado gerenciado para o Ingress.

## Plugin de autenticação do GKE

`kubectl` no GKE usa o plugin `gke-gcloud-auth-plugin`:

```bash
gcloud components install gke-gcloud-auth-plugin
```

Sem ele, `gcloud container clusters get-credentials` funciona mas qualquer
comando `kubectl` falha com `ACTION REQUIRED: gke-gcloud-auth-plugin ...`.
O `provision.py doctor` verifica a presença do plugin.

## Infraestrutura

```bash
python3 scripts/provision.py init --env prod --target gcp
python3 scripts/provision.py plan  --env prod
python3 scripts/provision.py apply --env prod
```

O stack cria VPC, GKE (Autopilot ou Standard com node pool `app`), Cloud SQL
Postgres, bucket GCS com CORS, service account com Workload Identity e HMAC key
para o SDK S3.

## Custo e tamanhos para validação

O preset padrão cria 2 nós `e2-standard-2` no system e `node_count` nós
`e2-standard-4`. Para uma validação barata:

```yaml
system_node_count: 1
machine_type: e2-standard-2
node_count: 1
db_instance: db-f1-micro
db_authorized_networks: ["0.0.0.0/0"]   # somente validação
```

Cluster zonal tem control plane gratuito. Cloud SQL `db-f1-micro` é
shared-core; suficiente para o E2E. A partir de 2026 o Cloud SQL cria em
`ENTERPRISE_PLUS` por padrão, que rejeita tiers compartilhados — o stack fixa
`edition = "ENTERPRISE"` (ajustável em `db_edition`).

> **Billing:** GKE e Cloud SQL exigem conta de faturamento **aberta**. Contas
> fechadas aparecem com `open: false` em `gcloud billing accounts list` e o
> projeto fica com `billingEnabled: false`. Reabra/crie a conta e vincule:
>
> ```bash
> gcloud billing projects link <projeto> --billing-account=<ID>
> ```

## Artifact Registry

A imagem precisa existir antes do Helm. Crie o repositório e publique:

```bash
gcloud artifacts repositories create openoju-val \
  --repository-format=docker --location=us-central1
gcloud auth configure-docker us-central1-docker.pkg.dev
IMG=us-central1-docker.pkg.dev/<projeto>/openoju-val/openoju:val
docker build --platform linux/amd64 -t "$IMG" .
docker push "$IMG"
```

No `answers.yaml`:

```yaml
gcp_gar_repository: openoju-val
gcp_gar_location: us-central1
image_repository: us-central1-docker.pkg.dev/<projeto>/openoju-val/openoju
image_tag: val
```

O stack concede `roles/artifactregistry.reader` à service account padrão do
Compute usada pelos nós, então não é preciso `imagePullSecrets`.

## GCS como S3

O OpenOju usa boto3. O GCS entra pelo modo interoperabilidade:

```env
OJU_STORAGE_BACKEND=s3
OJU_S3_ENDPOINT=https://storage.googleapis.com
OJU_S3_INTERNAL_ENDPOINT=https://storage.googleapis.com
OJU_S3_REGION=auto
OJU_S3_ACCESS_KEY=<hmac access id>
OJU_S3_SECRET_KEY=<hmac secret>
```

O código já usa `addressing_style: path`, exigido pelo GCS.

Limitações conhecidas: `put_bucket_cors` pode ser recusado dependendo da
política do bucket. O CORS é aplicado pelo Terraform; falhas no runtime são
ignoradas.

## Workload Identity

O output `service_account_annotations` preenche:

```yaml
serviceAccount:
  annotations:
    iam.gke.io/gcp-service-account: openoju@<project>.iam.gserviceaccount.com
```

## Ingress

O preset usa `ingressClassName: gce` com certificado gerenciado. Se preferir
`ingress-nginx`, troque a classe e use cert-manager.

## Validação antecipada

Antes do `apply` completo, valide presign:

```bash
gcloud storage buckets describe gs://<bucket> --format='value(cors_config)'
```
