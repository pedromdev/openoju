# AWS

EKS + RDS Postgres + S3 + ALB.

## Pré-requisitos

- `AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY` com permissão para VPC, EKS, RDS,
  S3, IAM e ELB.
- Terraform >= 1.7, `aws` CLI, `helm`, `kubectl`.
- Zona DNS (Route 53 ou externa) para o domínio público.
- Certificado ACM na mesma região do ALB.

## Infraestrutura

```bash
python3 scripts/provision.py init --env prod --target aws
python3 scripts/provision.py plan  --env prod
python3 scripts/provision.py apply --env prod
```

O stack `deploy/terraform/stacks/aws` cria:

| Recurso | Detalhe |
|---|---|
| VPC | 3 AZs, subnets privadas para nós, públicas para o ALB |
| EKS | versão gerenciada, node groups `system` e `app` |
| Add-ons | VPC CNI, CoreDNS, EBS CSI, AWS Load Balancer Controller |
| RDS | Postgres 16, KMS, backup 7 dias, multi-AZ opcional |
| S3 | SSE, versioning, lifecycle, CORS, bloqueio de acesso público |
| IRSA | role com permissão apenas no bucket/prefixo do OpenOju |

## Valores relevantes

- `serviceAccount.annotations` recebe a role IRSA via output.
- `config.OJU_S3_ENDPOINT=https://s3.<region>.amazonaws.com`.
- `config.OJU_S3_CREATE_BUCKET=false` (bucket criado pelo Terraform).
- `media.mode=emptyDir` e `data.mode=emptyDir`: sem EFS, sem RWX.
- `nodeSelector.openoju.io/pool=app` mantém o worker no pool certo.

## ALB

O preset `values-aws.yaml` já traz as anotações. Ajuste
`alb.ingress.kubernetes.io/certificate-arn` para o seu certificado.

Timeouts altos são importantes para downloads longos:

```yaml
alb.ingress.kubernetes.io/load-balancer-attributes: idle_timeout.timeout_seconds=3600
```

## Imagem

Para usar o ECR em vez do ghcr:

```bash
aws ecr get-login-password --region us-east-1 | docker login --username AWS --password-stdin <account>.dkr.ecr.us-east-1.amazonaws.com
docker tag ghcr.io/pedromdev/openoju:0.3.0 <account>.dkr.ecr.us-east-1.amazonaws.com/openoju:0.3.0
docker push <account>.dkr.ecr.us-east-1.amazonaws.com/openoju:0.3.0
```

Depois ajuste `image.repository` e crie o `image.pullSecrets`.

## Custos

O worker precisa de CPU (sem VAAPI). Use instâncias `c7g`/`c7i` para o pool
`app` e no mínimo 2 réplicas para não perder o SLA de análise.
