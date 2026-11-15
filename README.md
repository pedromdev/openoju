<p align="center">
  <img src="docs/assets/brand/logo-lockup-card.svg" alt="OpenOju" width="340">
</p>

<p align="center"><strong>Olhos abertos para o que a câmera viu.</strong></p>

Plataforma self-hosted e open-source para receber vídeos de câmeras de segurança,
analisar movimentação de forma assíncrona e revisar eventos em uma UI.

A aplicação é multi-organização com Postgres, SSO OIDC, API keys, MinIO/S3,
webhooks assinados, retenção e fluxos LGPD/Marco Civil. Licença Apache-2.0.

> **Sobre o nome** — *Ojú* é uma palavra iorubá para “olhos” ou “face”. O nome é
> uma referência cultural à ideia de observação atenta.

## Como rodar

| Cenário | Caminho |
|---|---|
| Avaliar localmente com Docker | `docker compose up -d --build` |
| Kubernetes local (kind/k3d) | `python3 scripts/provision.py init --env local --target local` |
| On-premise (k3s/RKE2/Talos) | `deploy/helm/openoju/values-onprem.yaml` |
| AWS / GCP / Azure / Magalu | `python3 scripts/provision.py init --env prod --target <nuvem>` |

O wizard pergunta o alvo, o banco, o object storage, o TLS e o SSO, gera
`values.yaml`, `terraform.tfvars`, o Secret e um `runbook.md`. Depois:

```bash
python3 scripts/provision.py doctor --env prod
python3 scripts/provision.py plan   --env prod
python3 scripts/provision.py apply  --env prod
```

Detalhes em [`deploy/README.md`](deploy/README.md) e
[`docs/provisioning/`](docs/provisioning/README.md).

> O `docker-compose.yml` é apenas para desenvolvimento local: ele assume rede
> `proxy` do host, bind mounts em `/srv/openoju` e `/dev/dri`. Produção é
> Kubernetes.

## O que está implementado

### Catálogo e análise

- Upload multipart por organização e upload em partes para arquivos grandes.
- Importação por caminho/pasta dentro do diretório de mídia, com deduplicação
  por SHA-256 **por organização**.
- Geração de proxy MP4 para playback no navegador.
- Análise de movimento com OpenCV:
  - MOG2 + frame differencing;
  - máscaras normalizadas por perfil de câmera;
  - supressão de mudança global de luminosidade (IR/amanhecer/luzes);
  - agregação temporal com histerese, merge e duração mínima;
  - decode automático em VAAPI (H.264/H.265) com fallback para CPU.
- Fila de jobs em Postgres, worker dedicado e progresso em tempo real (SSE).
- Eventos com thumbnail no ponto médio do intervalo, clipe curto, score e
  revisão (confirmar/descartar).
- Outbox transacional para `event.created`, `analysis.completed` e
  `analysis.failed`, com dispatcher de webhooks.

### Identidade, tenancy e segurança

- Postgres com database e role dedicados; SQLite permanece apenas na suíte de
  testes.
- Sessão opaca com cookie `HttpOnly`, `Secure` e `SameSite=Lax`.
- CSRF double-submit (`openoju_csrf` + header `X-CSRF-Token`).
- Senha com Argon2id.
- Setup inicial protegido por `OJU_SETUP_TOKEN`, com organização, owner,
  grupos padrão e perfil `Default`.
- Grupos de permissão locais: `Owner`, `Admin`, `Operator`, `Viewer` e grupos
  customizados. Claims de IdP não concedem permissão.
- Todas as rotas de catálogo são scoped por `/api/v1/orgs/{slug}`.
- API keys `oju_<prefix>_<secret>` com hash HMAC-SHA256, escopos, expiração e
  revogação. A organização é implícita na credencial.
- Isolamento cross-tenant validado por testes; recursos de outra organização
  respondem 404.
- Audit logs para ações administrativas e access logs para visualização,
  streaming, download e exclusão.
- Headers de segurança, rate limit de login e break-glass local.
- Licença Apache-2.0 e templates de compliance em `docs/compliance/`.

### Operação

- MinIO/S3 com multipart presigned e playback por URL assinada.
- Dispatcher de webhooks com HMAC, retry/backoff e proteção SSRF.
- Maintenance com retenção de mídia, metadados, logs e sessões.
- Legal hold e DSR com formulário público por organização.
- Helm chart e guias de backup/upgrade.

## Estrutura

```text
backend/
  alembic/           # migrations
  app/
    analyzer/        # CLI e motor de análise
    api/             # rotas FastAPI (/api/v1)
    services/        # ffmpeg, ingestão, fila, organizações, outbox
    auth.py          # dependências de sessão/CSRF/API key
    tenancy.py       # contexto e queries scoped
    security.py      # Argon2, tokens, HMAC, Fernet, rate limit
    models.py        # schema multi-tenant
    main.py          # aplicação FastAPI + estáticos do Angular
    worker.py        # consumidor da fila + watcher opcional
  tests/
frontend/            # Angular 22 + Tailwind CSS v4
data/                # logs de jobs e dados locais (gitignored)
docs/compliance/     # LGPD, Marco Civil, ROPA, RIPD, DPA, retenção
```

Os arquivos de mídia ficam em `OJU_MEDIA_ROOT` (padrão `/srv/openoju`),
prefixados por organização:

```text
org/{org_id}/videos/   # originais gerenciados
org/{org_id}/proxy/    # MP4 H.264 para o navegador
org/{org_id}/clips/    # trechos dos eventos
org/{org_id}/thumbs/   # miniaturas
uploads/.tmp/          # partes de upload em andamento
inbox/                 # pasta do watcher (single-org opcional)
```

O watcher de pasta é desabilitado por padrão. Para habilitá-lo, defina
`OJU_WATCH_ORG_SLUG`; sem isso, nenhum arquivo é importado para uma
organização ambígua.

## Banco de dados

O projeto usa um Postgres com database e role dedicados. Crie ambos uma vez
no servidor:

```bash
# criar o database (uma vez, no host do Postgres)
psql "$ADMIN_DATABASE_URL" -c "CREATE ROLE openoju LOGIN PASSWORD '...';"
psql "$ADMIN_DATABASE_URL" -c "CREATE DATABASE openoju OWNER openoju;"

# aplicar migrations
make migrate
```

`OJU_DATABASE_URL` deve apontar para o database dedicado. O host, a porta e as
credenciais vêm do seu ambiente (Postgres local, container, serviço gerenciado
ou cluster externo) — o projeto não assume nomes de rede ou de container.

## Desenvolvimento local

Pré-requisitos: Python 3.12, Node 24, ffmpeg, Docker.

```bash
make install
cp .env.example .env
# edite .env: DATABASE_URL, SECRET_KEY, FERNET_KEY, SETUP_TOKEN
make migrate

# terminal 1
make api

# terminal 2
make worker

# terminal 3
make ui
```

Testes (SQLite isolado, sem tocar no Postgres):

```bash
make test
```

Gerar uma amostra sintética com movimento:

```bash
make sample
```

## Setup inicial

1. Gere `OJU_SECRET_KEY`, `OJU_FERNET_KEY` e `OJU_SETUP_TOKEN`.
2. Suba a API.
3. Confira `GET /api/v1/auth/setup/status` (`setup_required: true`).
4. Envie `POST /api/v1/auth/setup` com o token, dados da organização e do
   owner. O setup cria grupos, perfil `Default`, privacy settings e já abre a
   sessão do owner.
5. O setup é bloqueado depois da primeira organização.

Exemplo:

```bash
curl -s http://127.0.0.1:8000/api/v1/auth/setup \
  -H 'Content-Type: application/json' \
  -d '{
    "token": "'"$OJU_SETUP_TOKEN"'",
    "organization_name": "Minha Empresa",
    "organization_slug": "minha-empresa",
    "owner_email": "owner@example.com",
    "owner_password": "uma-senha-muito-segura",
    "owner_display_name": "Owner"
  }'
```

## Docker

```bash
docker compose up -d --build
```

- A API roda `alembic upgrade head` antes de iniciar o uvicorn.
- API: `127.0.0.1:8000`.
- Worker: mesmo volume de dados/mídia da API.
- A rede externa do reverse proxy é configurável por `OJU_PROXY_NETWORK`
  (padrão `proxy`).
- Caminhos de mídia e de importação vêm de `OJU_MEDIA_HOST_DIR` e
  `OJU_IMPORT_HOST_DIR` (padrões `/srv/openoju` e `/srv/openoju/import`).
- VAAPI: `/dev/dri` e grupo `render` são mapeados para o container.
- Autenticação: sessão/CSRF; não há mais HTTP Basic.

## API principal

Todas as rotas de catálogo exigem sessão e são scoped por organização.

| Método | Rota | Descrição |
|---|---|---|
| GET | `/api/health` | saúde e espaço em disco |
| GET | `/api/v1/auth/setup/status` | setup pendente? |
| POST | `/api/v1/auth/setup` | setup inicial com token |
| POST | `/api/v1/auth/login` | login local |
| POST | `/api/v1/auth/logout` | revoga a sessão |
| POST | `/api/v1/auth/logout-all` | revoga todas as sessões |
| GET | `/api/v1/auth/me` | usuário, org ativa, permissões |
| POST | `/api/v1/auth/switch-organization` | troca a org ativa |
| GET | `/api/v1/organizations` | organizações do usuário |
| GET | `/api/v1/orgs/{slug}/videos` | catálogo da organização |
| POST | `/api/v1/orgs/{slug}/videos/upload` | upload multipart |
| POST | `/api/v1/orgs/{slug}/uploads/init` | inicia upload em partes |
| PUT | `/api/v1/orgs/{slug}/uploads/{id}/parts/{n}` | envia uma parte |
| POST | `/api/v1/orgs/{slug}/uploads/{id}/complete` | conclui o upload |
| POST | `/api/v1/orgs/{slug}/videos/import` | importar por caminho |
| DELETE | `/api/v1/orgs/{slug}/videos/{id}` | excluir vídeo e mídia (exige `videos.manage`) |
| POST | `/api/v1/orgs/{slug}/videos/bulk-delete` | exclusão em lote |
| POST | `/api/v1/orgs/{slug}/videos/{id}/analyze` | reenfileirar |
| GET | `/api/v1/orgs/{slug}/videos/{id}/stream` | proxy com Range |
| GET | `/api/v1/orgs/{slug}/jobs/{id}/events` | SSE de progresso |
| PATCH | `/api/v1/orgs/{slug}/events/{id}` | revisão |
| GET/POST/PUT/DELETE | `/api/v1/orgs/{slug}/profiles` | perfis de câmera |
| GET/POST | `/api/v1/orgs/{slug}/members` | membros e convites |
| GET/POST/PUT | `/api/v1/orgs/{slug}/groups` | grupos e permissões |
| GET/POST/DELETE | `/api/v1/orgs/{slug}/api-keys` | API keys |
| GET | `/api/v1/orgs/{slug}/audit` | audit log |
| POST | `/api/v1/ingest/batches` | lote de ingestão (API key) |
| POST | `/api/v1/ingest/uploads` | upload por API key |
| PUT | `/api/v1/ingest/uploads/{id}/parts/{n}` | parte do upload |
| POST | `/api/v1/ingest/uploads/{id}/complete` | conclui e enfileira |

Rotas de máquina usam `Authorization: Bearer oju_...`; a organização vem da
credencial e `organization_id` no corpo é ignorado.

## Análise

O motor recebe o proxy MP4 (ou o original, se o proxy não existir) e amostra
frames em 1 fps por padrão. Para cada frame:

1. aplica as máscaras do perfil;
2. calcula foreground com MOG2 e diferença entre frames;
3. detecta mudança global de luminosidade e reseta o background sem criar evento;
4. remove ruído com morfologia;
5. calcula score e maior componente;
6. agrega eventos com histerese.

O resultado inclui início/fim em segundos, horário do container quando disponível,
score de pico, bbox e caminho de thumbnail/clipe. A thumbnail é extraída no
ponto médio do evento, para mostrar o momento mais representativo da passagem.

## GPU

Benchmark com um DAV de referência (1280×720, 15 fps, H.264, 5 minutos):

| Pipeline | CPU | VAAPI | Ganho |
|---|---:|---:|---:|
| Decode + 1 fps + 640×360 + pipe | 29,13 s | 11,79 s | **2,47×** |
| Analyzer completo | 39,58 s | 16,69 s | **2,37×** |
| Eventos detectados | 2 | 2 | idênticos |

No analyzer completo, o CPU usou 51,28 s de user time; o VAAPI usou 10,44 s.
Por isso o decoder `auto` prefere **VAAPI para H.264 e H.265** quando o
dispositivo está disponível, com fallback automático para CPU. O proxy H.264
continua sendo remux (`-c:v copy`), sem encode.

O uso de CPU caiu de ~190% para ~100% no worker durante a análise, e a GPU passou
a ser usada no decode. O `gpu_busy_percent` do sysfs não contabiliza o motor de
vídeo UVD; a evidência é o comando `ffmpeg -hwaccel vaapi` e a queda de CPU.

## Compliance

- [`docs/compliance/`](docs/compliance/) contém templates de LGPD, Marco Civil,
  ROPA, RIPD, DPA, retenção, incidentes, subprocessadores e avisos de câmera.
- Retenção padrão: mídia 30 dias, access logs 6 meses, audit logs 12 meses.
- LUKS/criptografia em repouso está adiado e registrado como risco.
- Nenhum dado real deve ser usado em testes ou logs.

## Marca

- Identidade, assets e regras de uso em [`docs/branding.md`](docs/branding.md).
- Símbolo: lente aberta com ponto de evento.
- Assets gerados por `./scripts/brand-assets.sh` a partir de `docs/assets/brand/`.

## Pendências

- Validar qualidade e volume de eventos com mais amostras reais de DAV.
- Configurar o provedor OIDC institucional em produção.
- Migrar a imagem MinIO para o registry oficial quando houver acesso.
- Avaliar criptografia em repouso (LUKS/SSE) — risco documentado.
- Testes de carga com o volume real de vídeos.
- Publicar a release `v1.0.0`.
- Registrar `openoju.dev`/`openoju.org` e fazer busca formal de marca.
