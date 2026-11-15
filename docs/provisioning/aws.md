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

## Cota de vCPU

A cota padrão de "Running On-Demand Standard" em contas novas costuma ser **5
vCPUs**. O stack padrão pede 2 nós `system` + `node_count` nós `app`; com
`m7i.large` (2 vCPU cada) isso são 8 vCPUs se `node_count=2`.

Para validar sem pedir aumento:

```hcl
system_node_count = 1
node_count        = 1
```

Total: 4 vCPUs, cabe na cota. Para produção, peça aumento
(`aws service-quotas request-service-quota-increase --service-code ec2 --quota-code L-1216C47A --desired-value 32`)
ou use instâncias maiores.

## Imagem no ECR

A imagem pública `ghcr.io/pedromdev/openoju:<tag>` só existe para tags de
release do repositório. Em ambientes novos, publique no ECR antes do Helm:

```bash
ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
REGION=us-east-1
REPO=openoju-val

aws ecr create-repository --repository-name "$REPO" --region "$REGION" \
  --image-scanning-configuration scanOnPush=true

aws ecr get-login-password --region "$REGION" \
  | docker login --username AWS --password-stdin "$ACCOUNT.dkr.ecr.$REGION.amazonaws.com"

docker build --platform linux/amd64 -t "$ACCOUNT.dkr.ecr.$REGION.amazonaws.com/$REPO:val" .
docker push "$ACCOUNT.dkr.ecr.$REGION.amazonaws.com/$REPO:val"
```

Depois aponte no `answers.yaml` (o wizard injeta no chart):

```yaml
image_repository: <account>.dkr.ecr.<region>.amazonaws.com/openoju-val
image_tag: val
```

O node role já tem `AmazonEC2ContainerRegistryReadOnly`, então não é preciso
`imagePullSecrets`.

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
