# Magalu Cloud (experimental)

MKE (Magalu Kubernetes Engine) + DBaaS PostgreSQL + Object Storage.

> **Experimental.** O provider `MagaluCloud/mgc` evolui rápido e o ambiente não
> foi validado em conta real. Rode `plan` e revise o `terraform plan` antes do
> `apply`, e registre o resultado em `verification.md`.

## Pré-requisitos

- API key com escopos de MKE, DBaaS, Object Storage e rede.
- Terraform >= 1.7 com o provider `MagaluCloud/mgc` (o stack fixa a versão).
- `mgc` CLI é opcional; o Terraform cobre a criação.
- `ingress-nginx` e `cert-manager` no cluster.

## O que existe na Magalu

| Recurso | Uso no OpenOju |
|---|---|
| Kubernetes Engine (MKE) | cluster e node pools |
| DBaaS PostgreSQL | `OJU_DATABASE_URL` |
| Object Storage (S3) | bucket de mídia e logs |
| Load Balancer as a Service | exposição do ingress |
| Container Registry | imagem alternativa ao ghcr |

## DBaaS: rede privada e bug do provider

Na conta validada o DBaaS só expõe endereço **PRIVATE**, e o MKE é criado em
outra rede — sem peering/subnet compartilhada o pod não alcança o banco. Além
disso, o provider 0.56 cria a instância e falha em um `PUT` seguinte com
`400 Invalid HTTP request`, deixando a instância órfã (fora do state).

Consequências práticas:

- Para **validar** o cluster + Object Storage, use Postgres embutido:
  `database: bundled` (o chart sobe um StatefulSet com volume).
- Para produção com DBaaS, crie o cluster com `subnet_ids` da mesma rede do
  banco (ou configure peering) e confirme se o tipo oferece acesso público.
- Se o provider falhar no `PUT`, importe a instância
  (`terraform import 'mgc_dbaas_instances.this[0]' <id>`) ou apague pelo
  console/CLI após sair de `CREATING`:
  `mgc dbaas instances update --instance-id <id> --deletion-protected=false`
  e `mgc dbaas instances delete --instance-id <id>`.

## Node pool: flavor de VM, não de Kubernetes

O data source `mgc_kubernetes_flavor` devolve nomes no formato
`cloud-k8s.gp1.small`, que a API de node pools rejeita ("use magalu virtual
machine API to get valid machine type"). Use um tipo de VM:

```yaml
mgc_node_flavor: BV2-4-100   # 2 vCPU, 4 GB, 100 GB
```

Liste os válidos com `mgc virtual-machine machine-types list`.

## DBaaS: engine e tipo explícitos

O provider 0.56 pagina `instance-types` até um offset que a API rejeita com
`400 Invalid HTTP request` e não expõe `scopes` na API key. Para evitar a
paginação, informe explicitamente:

```yaml
db_engine_version: "17"      # postgresql 15/16/17 ACTIVE
db_instance: BV1-4-10        # label do tipo (1 vCPU / 4 GB), não o name
```

O stack pula os data sources quando os valores estão preenchidos. Mantenha
`db_engine_name: postgresql` (default).

**Atenção ao `db_instance`:** o provider compara o campo `label`, não o `name`.
Para `cloud-dbas-pgs-bv-i1-c1-r4-d10` o label é `BV1-4-10`. Liste com:

```bash
mgc dbaas instance-types list \
  --engine-id <uuid-do-postgres> --status ACTIVE --compatible-product SINGLE_INSTANCE
``` Os tipos antigos (`i0-*`,
`cloud-dbaas-bs1.*`) estão `DEPRECATED`; confirme com
`mgc dbaas instance-types list --engine-id <uuid> --status ACTIVE`.

## Imagem

O registry da Magalu exige o escopo **Container Registry [Write]** na API key;
sem ele, `registries create` responde `403`. Duas saídas:

1. criar uma API key nova marcando Container Registry (Write) e publicar em
   `<registry>.registry.br-se1.magalu.cloud`;
2. usar um registry público efêmero para validação:

```bash
docker tag openoju:local ttl.sh/openoju-val:24h
docker push ttl.sh/openoju-val:24h
```

```yaml
image_repository: ttl.sh/openoju-val
image_tag: "24h"
```

## Infraestrutura

```bash
python3 scripts/provision.py init --env prod --target magalu
python3 scripts/provision.py plan  --env prod
python3 scripts/provision.py apply --env prod
```

## Restrição estrutural: sem RWX

A Magalu não oferece volume `ReadWriteMany`. Por isso:

- `media.mode=emptyDir` e `data.mode=emptyDir`;
- `OJU_STORAGE_BACKEND=s3` obrigatório;
- logs de job vão para o object storage (implementado na Fase 0), então a API
  serve `/api/v1/jobs/{id}/log` de qualquer réplica.

## Endpoint S3

```env
OJU_S3_ENDPOINT=https://br-se1.magaluobjects.com
OJU_S3_INTERNAL_ENDPOINT=https://br-se1.magaluobjects.com
OJU_S3_REGION=br-se1
OJU_S3_CREATE_BUCKET=false
```

Confirme que o presign gerado abre no navegador: o bucket precisa de CORS com a
origem pública e de acesso via HTTPS.

## Load balancer

O addon de load balancer do MKE pode expor um `Service type=LoadBalancer`.
O preset usa `ingress-nginx` com `Service` interno e o LB na frente; ajuste
conforme o addon do seu cluster.
