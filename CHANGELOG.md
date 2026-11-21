# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and versions follow
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Changed

- Produto renomeado para **OpenOju**; repositório em `pedromdev/openoju`.
- Prefixo de ambiente `CAMERA_` → `OJU_` (**breaking change**).
- Database, role, bucket, containers, imagens, Helm chart e realm Keycloak
  renomeados para `openoju`.
- Cookies renomeados para `openoju_session`, `openoju_csrf` e
  `openoju_oidc_state`.
- API keys passam de `cam_<prefix>_<secret>` para `oju_<prefix>_<secret>`
  (**breaking change**; não havia chaves emitidas).
- Domínio público migrado para `openoju.pedromdev.com.br`.

### Added

- Identidade visual: símbolo, favicon, ícones PWA, og-image e social preview.
- `docs/branding.md` e `scripts/brand-assets.sh`.
- Provisionamento em Kubernetes: chart endurecido (PDB, NetworkPolicy,
  ServiceAccount com IRSA/Workload Identity, `helm test`, NOTES) e presets
  `minimal`, `onprem`, `aws`, `gcp`, `azure` e `magalu`.
- Wizard `scripts/provision.py` (`init`, `doctor`, `render`, `plan`, `apply`,
  `destroy`) que gera values, tfvars, Secret e runbook por ambiente.
- Stacks Terraform para AWS (EKS/RDS/S3), GCP (GKE/Cloud SQL/GCS), Azure
  (AKS/Flexible Server) e Magalu Cloud (MKE/DBaaS/Object Storage).
- `deploy/onprem/k3s/cloud-init.yaml` com k3s, MetalLB, ingress-nginx e
  cert-manager.
- `scripts/e2e.py` e job `e2e` no CI com cluster `kind`, duas réplicas de API,
  Postgres e MinIO embutidos.
- Postgres e MinIO opcionais como StatefulSets do próprio chart.

### Changed

- Migrations rodam em Job de hook (`pre-install,pre-upgrade`), não mais no start
  da API; `replicaCount.api > 1` deixa de ter corrida de migrations.
- Logs de job vão para o object storage quando `OJU_STORAGE_BACKEND=s3`, então a
  API serve `/api/v1/jobs/{id}/log` de qualquer réplica.
- Upload multipart grava direto no bucket quando o backend é S3 (sem depender de
  volume compartilhado).
- `OJU_RATE_LIMIT_BACKEND=postgres` compartilha a janela entre réplicas.
- MinIO embutido e do Compose usa o fork `pgsty` (o MinIO parou de publicar no
  Docker Hub).
- Docker Compose documentado como ambiente de desenvolvimento local.

### Fixed

- `/api/health` não entra em loop de restart quando o volume de mídia está
  indisponível; responde `degraded`.
- `boto3` deixa de receber credenciais vazias quando o acesso vem de IRSA ou
  Workload Identity.
- Caminhos de mídia gravados no banco atualizados para o novo media root
  (`OJU_MEDIA_ROOT`), restaurando thumbnail, proxy e clipes de vídeos com
  `storage_backend=local`.
- `og:image` e `twitter:image` agora usam URL absoluta, permitindo preview de
  link fora do domínio.

## [0.3.0] - 2026-11-14

### Added

- Apache-2.0 license, NOTICE, contribution, security and conduct documents.
- Compliance documentation templates under `docs/compliance/`.
- Postgres schema with organizations, users, memberships, permission groups,
  sessions, invitations, identity providers, API keys, ingest batches, webhooks,
  audit/access logs, privacy settings, data subject requests and legal holds.
- Alembic migrations.
- Local authentication with Argon2id, opaque HttpOnly sessions and CSRF.
- Initial setup flow protected by `OJU_SETUP_TOKEN`.
- Organization-scoped RBAC with default Owner/Admin/Operator/Viewer groups.
- Cross-tenant isolation tests.
- OIDC with PKCE/state/nonce, invitation acceptance and Keycloak development setup.
- MinIO/S3 multipart presigned upload, server-side probe and worker download/upload.
- Presigned playback for proxy, clips and thumbnails.
- Transactional outbox dispatcher with HMAC signatures, retry/backoff and SSRF protection.
- Webhook endpoints, test delivery and delivery log.
- Automatic retention for media, event metadata, access/audit logs, sessions and deliveries.
- Legal holds and data subject requests with public form, export and media deletion.
- Angular login/setup/invite, auth guard, CSRF interceptor, org switcher, administration UI, public privacy form and i18n toggle.
- Video deletion (single and bulk) with S3/local artifact cleanup, legal-hold and running-job guards, audit/access logs and a dedicated `videos.manage` permission.
- Helm chart, backup/upgrade guides, multi-architecture CI and SBOM.

### Changed

- The database is now Postgres-first; SQLite remains supported for the test
  suite.
- HTTP Basic Auth was removed in favor of session authentication.
- All resource routes are scoped by organization.

### Removed

- SQLite production database and the legacy single-tenant catalog.
