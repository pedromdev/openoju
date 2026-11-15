# Azure

AKS + Azure Database for PostgreSQL Flexible Server + MinIO no cluster.

## Por que MinIO

O Azure Blob Storage não expõe a API S3 que o boto3 consome. Na v1 o MinIO roda
dentro do cluster com PVC em Azure Disk e o chart cria o bucket. Um backend
`azure` nativo fica para uma fase posterior.

Consequências:

- `minio.enabled=true` e um Ingress público em `s3.<domínio>` para o presign.
- O MinIO é single-replica: aceite indisponibilidade durante manutenção do nó.
- Backup do bucket é responsabilidade sua (`mc mirror` para Blob ou outra conta).

## Pré-requisitos

- `az login` com permissão de Contributor na subscription.
- Terraform >= 1.7, `helm`, `kubectl`.
- `ingress-nginx` e `cert-manager` no cluster (o stack pode instalar).

## Infraestrutura

```bash
python3 scripts/provision.py init --env prod --target azure
python3 scripts/provision.py plan  --env prod
python3 scripts/provision.py apply --env prod
```

O stack cria Resource Group, VNet, AKS com node pools `system` e `app`,
Flexible Server Postgres, e as identidades gerenciadas.

## Valores relevantes

```yaml
config:
  OJU_S3_ENDPOINT: https://s3.<dominio>
  OJU_S3_INTERNAL_ENDPOINT: http://openoju-openoju-minio:9000
minio:
  enabled: true
  public:
    enabled: true
    host: s3.<dominio>
```

## StorageClass

O preset usa `managed-csi` (Azure Disk). Para MinIO maior, prefira um disco
Premium (`managed-csi-premium`) e ajuste `minio.persistence.storageClassName`.

## Workload Identity

O output `service_account_annotations` preenche
`azure.workload.identity/client-id`. Hoje é usado apenas se você habilitar
acesso a recursos Azure; o storage do OpenOju continua via MinIO.
