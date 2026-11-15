# Backup e Restore

## Postgres

Use uma URL libpq (sem o sufixo `+psycopg` do SQLAlchemy):

```bash
pg_dump "$PG_DATABASE_URL" -Fc -f backup-openoju-$(date +%F).dump
```

Restore em um database vazio:

```bash
pg_restore -d "$PG_DATABASE_URL" --clean --if-exists \
  backup-openoju-YYYY-MM-DD.dump
```

Se o Postgres roda em container, execute os comandos com
`docker exec -i <container> pg_dump ...` ou `docker exec -i <container>
pg_restore ...`.

## MinIO / S3

```bash
mc alias set openoju https://s3-openoju.example.com "$OJU_S3_ACCESS_KEY" "$OJU_S3_SECRET_KEY"
mc mirror --preserve openoju/openoju ./backup-minio
```

Restore:

```bash
mc mirror --preserve ./backup-minio openoju/openoju
```

## Configuração

- Guarde `.env` (modo 600) ou o Secret do Kubernetes em cofre separado.
- `OJU_SECRET_KEY` invalida sessões e API keys se trocado.
- `OJU_FERNET_KEY` é necessário para descriptografar segredos de webhooks/IdP.
- Teste restore trimestralmente em ambiente isolado.

## RPO/RTO sugeridos

- Postgres: backup diário, RPO 24h.
- MinIO: mirror diário, RPO 24h.
- Configuração: versionada em cofre, RPO imediato.
