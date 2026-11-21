# Contributing

Thanks for your interest in OpenOju.

## Development setup

Requirements: Python 3.12+, Node.js 24+, Docker, FFmpeg.

```bash
make install
cp .env.example .env
# edit .env
make test
```

Backend only:

```bash
PYTHONPATH=backend .venv/bin/uvicorn app.main:app --reload --port 8000
```

Frontend:

```bash
cd frontend && npm start
```

## Before opening a pull request

- Run `make test` and `cd frontend && npm test` (or `npm run build`).
- Add tests for behavior changes. Security and tenant-isolation changes require
  tests proving cross-tenant access returns 404.
- Keep the API under `/api/v1` backward compatible within a major version.
- Never commit secrets, real camera footage, or personal data. Test fixtures
  must be synthetic.
- Update `CHANGELOG.md` for user-facing changes.
- Migrations must be additive and reversible when practical.

## Commit style

Conventional commits are preferred: `feat:`, `fix:`, `docs:`, `test:`,
`refactor:`, `chore:`.

## Reporting security issues

Do not open a public issue. Follow `SECURITY.md`.

## License

By contributing you agree that your contribution is licensed under
Apache-2.0.

## Credenciais e CI

Validação em nuvem é **local**. Configure uma vez:

```bash
./scripts/cloud-setup.sh --cloud aws   # azure | gcp | magalu
./scripts/cloud-setup.sh --check
```

Os arquivos ficam em `.secrets/` (700/600, gitignored) e o `provision.py` os
carrega sozinho. Para rodar o E2E contra um ambiente já provisionado:

```bash
./scripts/cloud-e2e.sh aws val
```

O CI não usa credenciais de nuvem: os jobs rodam com SQLite, Azurite e `kind`.
`scripts/tests/test_ci_no_cloud_credentials.py` falha se algum workflow
referenciar `AWS_*`, `ARM_*`, `GOOGLE_*`, `TF_VAR_mgc_*` ou comandos de login.
