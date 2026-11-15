# Upgrade

1. Leia o `CHANGELOG.md` e faça backup do Postgres e do MinIO.
2. Atualize a imagem (`OJU_IMAGE_TAG`).
3. Rode as migrations antes de subir a API:

```bash
docker compose run --rm api alembic upgrade head
```

No Kubernetes o comando da API já executa `alembic upgrade head`.

4. Suba API, worker, dispatcher e maintenance.
5. Valide `/api/health`, login e um upload pequeno.
6. Monitore erros de webhook e retenção por 24h.

## Rollback

- Reverta a tag da imagem.
- Migrations destrutivas exigem restore do backup; migrations deste projeto são
  aditivas por padrão.
- Nunca reutilize um `OJU_SETUP_TOKEN` já consumido.
