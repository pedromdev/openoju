# Exposição pública (reverse proxy + Cloudflare Tunnel)

> Este guia cobre o caminho legado de **docker compose atrás de proxy**. Para
> provisionamento em Kubernetes (nuvem ou on-premise) use
> [`docs/provisioning/`](provisioning/README.md) e o wizard
> `scripts/provision.py`.

## Resultado esperado

- URL pública: `https://openoju.example.com`
- Autenticação: sessão local (cookie `HttpOnly`) + CSRF; API keys para máquinas
- Origem: container `openoju-api:8000` na rede do reverse proxy
- Banco: Postgres dedicado; o host vem de `OJU_DATABASE_URL`
- TLS: terminado no Cloudflare ou no reverse proxy
- Estáticos do Angular: servidos pela própria API (`FileResponse`/SPA fallback)

## Componentes

```text
Internet
  └─ Cloudflare Tunnel / balanceador
       └─ reverse proxy (porta 80)
            └─ openoju-api:8000
                 ├─ API FastAPI
                 └─ frontend Angular build
            openoju-worker (sem porta pública)
```

## Configuração

### Cloudflare Tunnel

Exemplo de configuração do `cloudflared`:

```yaml
ingress:
  - hostname: openoju.example.com
    service: http://<reverse-proxy>:80
  - service: http_status:404
```

Rota DNS no túnel correto:

```bash
cloudflared tunnel route dns --overwrite-dns <TUNNEL_ID> openoju.example.com
```

### Nginx Proxy Manager

Proxy Hosts:

- `openoju.example.com` → `openoju-api:8000`, websockets habilitado.
- `s3-openoju.example.com` → `openoju-minio:9000`, sem block-exploits,
  `client_max_body_size 0`, buffering desabilitado.
- Opcional: um host legado pode responder `301` para `openoju.example.com`.

- Scheme: `http`
- SSL: desabilitado no NPM quando o Cloudflare termina TLS.

Se o NPM não regenerar os arquivos `/data/nginx/proxy_host/*.conf` no restart,
recrie o host pelo painel ou crie o arquivo manualmente e valide com
`nginx -t` antes do reload. Mantenha backup do banco do NPM e da configuração
do Cloudflare antes de alterar.

## Banco de dados e migrations

O Compose entra nas redes externas configuradas por `OJU_PROXY_NETWORK` e
`OJU_DATABASE_NETWORK` e usa o database dedicado:

```env
OJU_DATABASE_URL=postgresql+psycopg://openoju:<senha>@<postgres-host>:5432/openoju
```

A API executa `alembic upgrade head` antes do uvicorn. Para rodar manualmente:

```bash
docker compose run --rm api alembic upgrade head
```

O `.env` deve ter permissão `600` e nunca ser versionado.

## Autenticação

Não há mais HTTP Basic. O fluxo é:

1. `OJU_SETUP_TOKEN` habilita o setup inicial.
2. `POST /api/v1/auth/setup` cria organização, owner, grupos padrão, perfil
   `Default` e privacy settings.
3. Login em `POST /api/v1/auth/login` cria uma sessão opaca.
4. Mutações exigem o cookie `openoju_csrf` e o header `X-CSRF-Token`.
5. Rotas de máquina usam `Authorization: Bearer oju_...`.

Variáveis relevantes:

```env
OJU_SESSION_COOKIE=openoju_session
OJU_SESSION_TTL_HOURS=720
OJU_COOKIE_SECURE=true
OJU_CSRF_ENABLED=true
OJU_SETUP_TOKEN=...
OJU_SECRET_KEY=...
OJU_FERNET_KEY=...
```

Para revogar todas as sessões de um usuário, use `POST /api/v1/auth/logout-all`.
API keys são criadas e revogadas em `/api/v1/orgs/{slug}/api-keys`.

## Limite importante do Cloudflare

O Cloudflare Tunnel/plano Free limita o corpo de uma requisição a cerca de
100 MB. Vídeos DAV longos não devem ser enviados em uma única requisição.

Para arquivos grandes, use uma das opções:

1. Importar por caminho/pasta na UI (recomendado): o arquivo já está no disco.
2. Copiar para a pasta monitorada e usar "Varrer pasta" (requer
   `OJU_WATCH_ORG_SLUG`).
3. Upload em partes pela API (`/api/v1/orgs/{slug}/uploads` ou
   `/api/v1/ingest/uploads`), respeitando o limite por requisição.
4. Enviar pela rede local (`http://127.0.0.1:8000`), fora do Cloudflare.

Uploads grandes usam multipart presigned no MinIO (`/api/v1/ingest/...`) ou
upload em partes pela API, conforme a configuração de storage.

## Migração de marca (camera-anomaly → openoju)

Passos executados no cutover, com os serviços parados:

1. `pg_dump` do banco antigo antes de qualquer alteração.
2. `ALTER ROLE camera_anomaly RENAME TO openoju` e
   `ALTER DATABASE camera_anomaly RENAME TO openoju`.
3. Mover o diretório de mídia para o novo media root:
   `mv "$OLD_MEDIA_ROOT" "$OJU_MEDIA_ROOT"` (ajuste os caminhos do seu
   ambiente).
4. Mover o bucket local do MinIO, se aplicável:
   `mv "$OJU_MEDIA_ROOT/minio/camera_anomaly" "$OJU_MEDIA_ROOT/minio/openoju"`.
5. Atualizar `OJU_DATABASE_URL`, `OJU_MEDIA_ROOT` e `OJU_S3_BUCKET`.
6. **Atualizar os caminhos gravados no banco**, porque as colunas guardam o
   caminho absoluto da raiz antiga. Salve o SQL abaixo em um arquivo e rode com
   `psql -v old_root="$OLD_MEDIA_ROOT" -v new_root="$OJU_MEDIA_ROOT" -f migration.sql`:

```sql
UPDATE videos SET source_path    = replace(source_path,    :'old_root', :'new_root') WHERE source_path    LIKE :'old_root' || '%';
UPDATE videos SET proxy_path     = replace(proxy_path,     :'old_root', :'new_root') WHERE proxy_path     LIKE :'old_root' || '%';
UPDATE videos SET thumbnail_path = replace(thumbnail_path, :'old_root', :'new_root') WHERE thumbnail_path LIKE :'old_root' || '%';
UPDATE events SET clip_path      = replace(clip_path,      :'old_root', :'new_root') WHERE clip_path      LIKE :'old_root' || '%';
UPDATE events SET thumbnail_path = replace(thumbnail_path, :'old_root', :'new_root') WHERE thumbnail_path LIKE :'old_root' || '%';
```

Sem esse passo, vídeos gravados com `storage_backend=local` perdem thumbnail,
proxy e clipes, porque o fallback local aponta para um diretório que não existe
mais. Vídeos em S3 não são afetados, pois usam a chave do objeto.

7. Recriar containers e imagem (`docker compose build && docker compose up -d`).

## Verificação

```bash
# health público (o container usa este endpoint no healthcheck)
curl https://openoju.example.com/api/health

# sem sessão deve retornar 401
curl -i https://openoju.example.com/api/v1/auth/me

# setup pendente?
curl https://openoju.example.com/api/v1/auth/setup/status
```

Se o DNS local ainda não resolver, use `--resolve <host>:443:<edge-ip>` ou
aguarde a propagação.
