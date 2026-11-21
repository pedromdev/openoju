from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = sorted((ROOT / ".github" / "workflows").glob("*.yml"))

# O CI nunca deve autenticar em conta de nuvem nem rodar plan/apply.
FORBIDDEN = (
    "AWS_ACCESS_KEY_ID",
    "AWS_SECRET_ACCESS_KEY",
    "AWS_SESSION_TOKEN",
    "ARM_CLIENT_ID",
    "ARM_CLIENT_SECRET",
    "ARM_TENANT_ID",
    "GOOGLE_APPLICATION_CREDENTIALS",
    "TF_VAR_mgc",
    "secrets.AWS",
    "secrets.AZURE",
    "secrets.GCP",
    "secrets.MAGALU",
    "aws login",
    "aws sso login",
    "az login",
    "gcloud auth",
    "mgc auth",
    "terraform plan",
    "terraform apply",
)


def test_workflows_do_not_use_cloud_credentials():
    assert WORKFLOWS, "nenhum workflow encontrado"
    for workflow in WORKFLOWS:
        text = workflow.read_text(encoding="utf-8")
        for token in FORBIDDEN:
            assert token not in text, f"{token!r} encontrado em {workflow.name}"


def test_e2e_job_uses_kind_only():
    text = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "helm/kind-action" in text
    assert "kind load docker-image openoju:e2e" in text
    assert "kubeconfig" not in text.lower()


def test_secrets_directory_is_ignored():
    gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
    assert ".secrets/" in gitignore
