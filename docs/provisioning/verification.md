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

| Data | Alvo | Responsável | Resultado | Observações |
|---|---|---|---|---|
| | | | | |
