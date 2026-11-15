# Kubernetes on-premise

Testado com k3s; os passos valem para RKE2, Talos e kubeadm.

## Pré-requisitos

- Cluster com pelo menos 3 nós (API + worker + banco) ou 1 nó para laboratório.
- `storageClass` para volumes `ReadWriteOnce` (local-path, Longhorn, ceph).
- `ingress-nginx` e `cert-manager` para TLS.
- Nós do worker com `/dev/dri` para VAAPI.

## Bootstrap com k3s

O arquivo `deploy/onprem/k3s/cloud-init.yaml` instala k3s, MetalLB,
ingress-nginx, cert-manager e cria `/srv/openoju`. Ajuste o IP do MetalLB antes
de usar.

Use o arquivo como *user data* da VPS:

```text
deploy/onprem/k3s/cloud-init.yaml
```

Ou instale manualmente:

```bash
curl -sfL https://get.k3s.io | sh -s - server \
  --write-kubeconfig-mode 644 --disable traefik
kubectl apply -f https://raw.githubusercontent.com/metallb/metallb/main/config/manifests/metallb-native.yaml
helm repo add ingress-nginx https://kubernetes.github.io/ingress-nginx
helm install ingress-nginx ingress-nginx/ingress-nginx -n ingress-nginx --create-namespace
```

## Instalação

```bash
python3 scripts/provision.py init --env onprem --target onprem
python3 scripts/provision.py plan --env onprem
python3 scripts/provision.py apply --env onprem
```

O preset liga Postgres e MinIO embutidos, VAAPI e ingress com TLS.

## VAAPI

O chart monta `/dev/dri` via `hostPath` e adiciona `supplementalGroups: [110]`.
Confirme o grupo do device no nó:

```bash
stat -c '%g' /dev/dri/renderD128
```

Ajuste `vaapi.groupAdd` se o valor não for 110.

## MinIO público

As URLs assinadas usam `OJU_S3_ENDPOINT`, então o MinIO precisa ser resolvível
pelo navegador. O preset cria um Ingress em `s3.<domínio>`; o DNS precisa
apontar para o mesmo ponto de entrada da API.

## Backup

- Postgres: `kubectl exec` + `pg_dump` em CronJob ou backup do PVC.
- MinIO: `mc mirror` para um bucket externo.
- Secret: cópia em cofre separado.
