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

### Fixed

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
