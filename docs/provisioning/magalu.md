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
