# Local (kind ou k3d)

Serve para validar o chart e o fluxo completo sem nuvem.

## 1. Cluster

```bash
kind create cluster --name openoju
kubectl create namespace openoju
```

## 2. Valores

```bash
python3 scripts/provision.py init --env local --target local --yes
python3 scripts/provision.py plan --env local
```

O preset gerado usa Postgres e MinIO embutidos, `media.mode=emptyDir` e sem
TLS. O endpoint S3 é `http://localhost:9000` e é alcançado por port-forward.

## 3. Instalação

```bash
helm upgrade --install openoju deploy/helm/openoju \
  -n openoju -f deploy/environments/local/values.yaml
```

## 4. Acesso

```bash
kubectl -n openoju port-forward svc/openoju-openoju 8000:8000
kubectl -n openoju port-forward svc/openoju-openoju-minio 9000:9000
```

Abra `http://localhost:8000`, pegue o token:

```bash
kubectl -n openoju get secret openoju-secrets \
  -o jsonpath='{.data.OJU_SETUP_TOKEN}' | base64 -d
```

## 5. Teste do chart

```bash
helm test openoju -n openoju
```
