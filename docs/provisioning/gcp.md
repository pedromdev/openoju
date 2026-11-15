# GCP

GKE + Cloud SQL + GCS (modo interoperabilidade) + GCLB.

## Pré-requisitos

- Projeto com APIs de GKE, Cloud SQL, Storage e IAM habilitadas.
- `gcloud auth application-default login`.
- Terraform >= 1.7, `helm`, `kubectl`.
- IP global estático e certificado gerenciado para o Ingress.

## Infraestrutura

```bash
python3 scripts/provision.py init --env prod --target gcp
python3 scripts/provision.py plan  --env prod
python3 scripts/provision.py apply --env prod
```

O stack cria VPC, GKE (Autopilot ou Standard com node pool `app`), Cloud SQL
Postgres, bucket GCS com CORS, service account com Workload Identity e HMAC key
para o SDK S3.

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
