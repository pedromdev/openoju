# Verificação pendente por nuvem

As trilhas de AWS, GCP, Azure e Magalu foram entregues sem validação em conta
real. Use este checklist na primeira execução e registre o resultado.

## Antes do apply

```bash
python3 scripts/provision.py doctor --env <env>
python3 scripts/provision.py plan   --env <env>
```

Revise:

- [ ] `terraform plan` sem `destroy`/`replace` inesperado
- [ ] CIDR da VPC não colide com a rede local
- [ ] nome do bucket é único na conta
- [ ] `render.yaml` mostra `OJU_S3_CREATE_BUCKET: "false"`
- [ ] `render.yaml` mostra `OJU_RATE_LIMIT_BACKEND: postgres` quando há 2+ réplicas

## Depois do apply

```bash
kubectl -n <ns> get pods
kubectl -n <ns> get jobs
helm test <release> -n <ns>
kubectl -n <ns> logs deploy/<release>-openoju-api --tail=100
```

- [ ] pods `Ready`; Job de migrations `Complete`
- [ ] `/api/health` responde `ok`
- [ ] setup inicial aceito com o token do Secret
- [ ] login local funciona
- [ ] upload de 5 MB conclui
- [ ] job de análise conclui
- [ ] `/api/v1/jobs/{id}/log` responde
- [ ] URL assinada do objeto abre no navegador (CORS + DNS)
- [ ] `terraform destroy` limpa tudo

## Checklist por provedor

### AWS

```bash
aws eks update-kubeconfig --name <cluster> --region <region>
kubectl get ingress -n <ns>   # ADDRESS do ALB
aws s3api get-bucket-cors --bucket <bucket>
aws rds describe-db-instances --db-instance-identifier <id> \
  --query 'DBInstances[0].Endpoint'
```

### GCP

```bash
gcloud container clusters get-credentials <cluster> --region <region>
gcloud sql instances describe <instancia> --format='value(connectionName)'
gcloud storage buckets describe gs://<bucket> --format='value(cors_config)'
```

### Azure

```bash
az aks get-credentials -g <rg> -n <cluster>
az postgres flexible-server show -g <rg> -n <server> --query fullyQualifiedDomainName
kubectl get ingress -n <ns>
```

### Magalu

```bash
mgc kubernetes cluster list
mgc dbaas instances list
mgc object-storage buckets list
kubectl get svc -n <ns>
```

## Registro

| Data | Alvo | Resultado | Observações |
|---|---|---|---|
| 2026-11-15 | AWS | OK | EKS 1.37, RDS `db.t4g.medium`, S3 via IRSA, 2 réplicas de API, 1 worker; `helm test` e E2E verdes; destroy + limpeza do ECR confirmados. Cota de 5 vCPU exigiu `system_node_count=1`/`node_count=1`; root não é principal válido no EKS. |
| 2026-11-16 | GCP | OK | GKE 1.36.4 zonal + Cloud SQL `db-f1-micro` (edition ENTERPRISE) + GCS interop (HMAC) + GAR; E2E verde. Billing precisou ser reaberto; `gke-gcloud-auth-plugin` obrigatório; botocore ≥1.36 quebrava o GCS com checksums opcionais. |
| 2026-11-16 | Azure | OK | AKS 1.36 + Postgres Flexible `B_Standard_B1ms` + MinIO no cluster + ACR com `AcrPull`; E2E verde. Cota de 4 vCPU exigiu `Standard_D2ds_v4` (família v5 não liberada em `brazilsouth`); `az acr build` bloqueado → push via skopeo. |
