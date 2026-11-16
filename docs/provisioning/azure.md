# Azure

AKS + Azure Database for PostgreSQL Flexible Server + MinIO no cluster.

## Storage: Blob nativo

O Azure Blob **não é S3**. A aplicação tem um backend nativo `azure`:

- Terraform cria um Storage Account (LRS, TLS 1.2), um container privado e
  concede `Storage Blob Data Contributor` à identidade gerenciada do app.
- No AKS o acesso usa **Workload Identity**: o pod leva o label
  `azure.workload.identity/use: "true"` e a ServiceAccount tem a anotação
  `azure.workload.identity/client-id`.
- Upload em partes usa **staged blocks** (`stage_block` → `commit_block_list`),
  então continua funcionando com várias réplicas de API.
- Leitura usa **SAS**: user delegation key (preferido) → account key (fallback)
  → streaming pela API quando não há SAS (storage privado/RBAC restrito).
- `storage=bundled` continua subindo MinIO no cluster (laboratório/on-prem).

```yaml
config:
  OJU_STORAGE_BACKEND: azure
  OJU_AZURE_STORAGE_ACCOUNT: <output storage_account>
  OJU_AZURE_STORAGE_CONTAINER: openoju-media
  OJU_AZURE_STORAGE_ENDPOINT: https://<account>.blob.core.windows.net
podLabels:
  azure.workload.identity/use: "true"
minio:
  enabled: false
```

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
  OJU_STORAGE_BACKEND: azure
  OJU_AZURE_STORAGE_ACCOUNT: <storage_account>
  OJU_AZURE_STORAGE_CONTAINER: openoju-media
  OJU_AZURE_STORAGE_ENDPOINT: <storage_endpoint>
podLabels:
  azure.workload.identity/use: "true"
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
