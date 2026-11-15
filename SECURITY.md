# Security Policy

## Supported versions

Only the latest release receives security fixes.

## Reporting a vulnerability

Report privately to the maintainer e-mail configured for the deployment, or
open a private security advisory on the hosting platform. Do not open a public
issue.

Include:

- affected version or commit;
- reproduction steps;
- impact assessment (cross-tenant data exposure, auth bypass, SSRF, etc.);
- any suggested fix.

You can expect an acknowledgement within 5 business days.

## Scope

In scope:

- authentication and session handling (local, OIDC, API keys);
- authorization and tenant isolation;
- presigned upload and playback flows;
- webhook signing and SSRF protections;
- secrets handling and audit logging.

Out of scope:

- vulnerabilities requiring a compromised host or database;
- missing disk encryption when the deployment explicitly documents LUKS as
  deferred;
- social engineering.

## Deployment hardening

- Run behind HTTPS; set `OJU_COOKIE_SECURE=true`.
- Keep `.env` at mode `600` and never commit it.
- Use a dedicated database and role.
- Restrict MinIO console access.
- Enable backups and test restores.
- Rotate API keys and webhook secrets periodically.
