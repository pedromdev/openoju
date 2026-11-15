# Helm

```bash
helm upgrade --install openoju deploy/helm/openoju \
  --namespace openoju --create-namespace \
  -f my-values.yaml
```

Crie o Secret antes:

```bash
kubectl -n openoju create secret generic openoju-secrets \
  --from-literal=OJU_DATABASE_URL='postgresql+psycopg://...' \
  --from-literal=OJU_SECRET_KEY='...' \
  --from-literal=OJU_FERNET_KEY='...' \
  --from-literal=OJU_SETUP_TOKEN='...' \
  --from-literal=OJU_S3_ACCESS_KEY='...' \
  --from-literal=OJU_S3_SECRET_KEY='...' \
  --from-literal=OJU_OIDC_CLIENT_SECRET='...'
```

O chart **não** instala Postgres nem MinIO; aponte `OJU_DATABASE_URL` e os
endpoints S3 para serviços gerenciados/externos. Ajuste `media`/`data` para
`ReadWriteMany` ou use um único nó com `ReadWriteOnce`.

O chart usa `securityContext` uid/gid 1000; garanta que os volumes tenham as
permissões correspondentes.
