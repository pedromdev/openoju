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

## Cota de vCPU (conta gratuita)

Assinaturas de avaliação costumam ter **4 vCPUs regionais**. O preset padrão
(2 nós `system` + `node_count` × `D4ds_v5`) não cabe. Para validar:

```yaml
system_node_count: 1
node_count: 1
# opcional: banco menor
db_instance: B_Standard_B1ms
```

Com `Standard_D2ds_v4` em ambos os pools são 4 vCPUs no total. Assinaturas de
avaliação podem não permitir a família `v5` em `brazilsouth` — o erro
`The VM size ... is not allowed` lista os SKUs válidos; use um deles
(`Standard_D2ds_v4` costuma estar disponível). Para produção,
peça aumento em **Subscriptions → Usage + quotas → Total Regional vCPUs**.

## ACR e imagem

O ACR não é criado pelo stack (a imagem precisa existir antes do Helm). Crie
antes:

```bash
RG=openoju-val-images
ACR=openojuval$(python3 -c 'import secrets;print(secrets.token_hex(3))')

az group create -n "$RG" -l brazilsouth
az acr create -g "$RG" -n "$ACR" --sku Basic --admin-enabled false
az acr login -n "$ACR"
docker build --platform linux/amd64 -t "$ACR.azurecr.io/openoju:val" .
docker push "$ACR.azurecr.io/openoju:val"
```

Depois informe no `answers.yaml`:

```yaml
azure_acr_name: <acr>
azure_acr_resource_group: openoju-val-images
image_repository: <acr>.azurecr.io/openoju
image_tag: val
```

O stack cria a role `AcrPull` para a kubelet identity do AKS, então não é
preciso `imagePullSecrets` nem `--attach-acr`.

> **Assinatura de avaliação:** `az acr build` (ACR Tasks) costuma ser bloqueado
> (`TasksOperationsNotAllowed`). Use `docker push`. Se o domínio
> `<acr>.azurecr.io` não resolver localmente logo após a criação, o DNS público
> já funciona — publique de um container com DNS explícito:
>
> ```bash
> docker save "$ACR.azurecr.io/openoju:val" -o /tmp/openoju.tar
> TOKEN=$(az acr login -n "$ACR" --expose-token --query accessToken -o tsv)
> docker run --rm --dns 8.8.8.8 -v /tmp/openoju.tar:/img.tar \
>   quay.io/skopeo/stable copy \
>   --dest-creds "00000000-0000-0000-0000-000000000000:$TOKEN" \
>   docker-archive:/img.tar "docker://$ACR.azurecr.io/openoju:val"
> ```

## StorageClass

O preset usa `managed-csi` (Azure Disk). Para MinIO maior, prefira um disco
Premium (`managed-csi-premium`) e ajuste `minio.persistence.storageClassName`.

## Workload Identity

O output `service_account_annotations` preenche
`azure.workload.identity/client-id`. Hoje é usado apenas se você habilitar
acesso a recursos Azure; o storage do OpenOju continua via MinIO.
