from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import provision  # noqa: E402


@pytest.fixture()
def env_root(tmp_path, monkeypatch):
    monkeypatch.setattr(provision, "ENVIRONMENTS", tmp_path)
    return tmp_path


def test_env_name_validation(env_root):
    assert provision.env_dir("prod-1") == env_root / "prod-1"
    for invalid in ("Prod", "a", "com espaço", "x" * 40, "../etc"):
        with pytest.raises(provision.ProvisionError):
            provision.env_dir(invalid)


def test_dump_yaml_handles_nested_structures():
    data = {
        "a": 1,
        "b": True,
        "c": "texto",
        "d": {"e": "com: dois pontos"},
        "f": [{"g": "h"}, "i"],
        "j": {},
        "k": [],
    }
    rendered = provision.dump_yaml(data)
    assert 'a: 1' in rendered
    assert 'b: true' in rendered
    assert 'c: texto' in rendered
    assert '"com: dois pontos"' in rendered
    assert '  - ' in rendered
    assert '"0"' in provision.dump_yaml({"n": "0"})
    assert '"true"' in provision.dump_yaml({"b": "true"})
    assert 'j: {}' in rendered
    assert 'k: []' in rendered


def test_dump_tfvars_types():
    rendered = provision.dump_tfvars(
        {"name": "prod", "count": 2, "flag": False, "list": ["a", "b"]}
    )
    assert 'name = "prod"' in rendered
    assert "count = 2" in rendered
    assert "flag = false" in rendered
    assert 'list = ["a", "b"]' in rendered


def test_wizard_never_generates_secret_in_chart():
    local = provision.values_for(provision.default_answers("dev", "local"))
    assert local["secrets"]["create"] is False


def test_cloud_values_disable_generated_secret():
    answers = provision.default_answers("prod", "aws")
    answers["storage"] = "managed"
    answers["database"] = "managed"
    values = provision.values_for(answers)
    assert values["secrets"]["create"] is False
    assert values["postgresql"]["enabled"] is False
    assert values["minio"]["enabled"] is False
    assert values["config"]["OJU_S3_CREATE_BUCKET"] == "false"


def test_multiple_replicas_force_postgres_rate_limit():
    answers = provision.default_answers("prod", "onprem")
    answers["api_replicas"] = "2"
    values = provision.values_for(answers)
    assert values["config"]["OJU_RATE_LIMIT_BACKEND"] == "postgres"
    assert values["pdb"]["enabled"] is True


def test_single_replica_keeps_memory_rate_limit():
    answers = provision.default_answers("dev", "local")
    values = provision.values_for(answers)
    assert values["config"]["OJU_RATE_LIMIT_BACKEND"] == "memory"
    assert values["pdb"]["enabled"] is False


def test_bundled_database_builds_url_and_password(env_root):
    answers = provision.default_answers("dev", "local")
    secrets = provision.secrets_for(answers)
    assert "postgres-password" in secrets
    assert secrets["postgres-password"] in secrets["OJU_DATABASE_URL"]
    assert secrets["OJU_DATABASE_URL"].endswith(
        "@openoju-openoju-postgresql:5432/openoju"
    )


def test_render_is_idempotent_for_secrets(env_root):
    answers = provision.default_answers("dev", "local")
    directory = provision.render_environment(answers)
    first = provision.read_env_file(directory / "secrets.env")

    provision.render_environment(answers)
    second = provision.read_env_file(directory / "secrets.env")

    assert first == second
    assert (directory / "secrets.env").stat().st_mode & 0o777 == 0o600
    assert (directory / "values.yaml").exists()
    assert (directory / "answers.yaml").exists()
    assert (directory / "runbook.md").exists()
    assert (directory / "state.json").exists()


def test_render_keeps_secret_but_updates_values(env_root):
    answers = provision.default_answers("dev", "local")
    directory = provision.render_environment(answers)
    before = provision.read_env_file(directory / "secrets.env")

    answers["api_replicas"] = "2"
    provision.render_environment(answers)
    after = provision.read_env_file(directory / "secrets.env")

    assert before == after
    values = (directory / "values.yaml").read_text(encoding="utf-8")
    assert "OJU_RATE_LIMIT_BACKEND: postgres" in values


def test_environment_answers_never_contain_secrets(env_root):
    answers = provision.default_answers("dev", "local")
    directory = provision.render_environment(answers)
    answers_text = (directory / "answers.yaml").read_text(encoding="utf-8")
    secrets_values = provision.read_env_file(directory / "secrets.env")
    for value in secrets_values.values():
        assert value not in answers_text


def test_terraform_stack_none_for_local_and_existing(env_root):
    local = provision.default_answers("dev", "local")
    assert provision.terraform_stack(local) is None

    aws = provision.default_answers("prod", "aws")
    aws["cluster_mode"] = "existing"
    assert provision.terraform_stack(aws) is None

    aws["cluster_mode"] = "create"
    assert provision.terraform_stack(aws) == provision.TERRAFORM / "aws"


def test_oidc_preset_maps_provider_to_issuer():
    answers = provision.default_answers("prod", "aws")
    answers["oidc"] = "entra"
    values = provision.values_for(answers)
    assert values["config"]["OJU_OIDC_ENABLED"] == "true"
    assert "microsoftonline.com" in values["config"]["OJU_OIDC_ISSUER"]
    assert values["config"]["OJU_OIDC_REDIRECT_URI"].endswith(
        "/api/v1/auth/oidc/callback"
    )


def test_tfvars_maps_cloud_identifiers():
    gcp = provision.default_answers("prod", "gcp")
    gcp["gcp_project"] = "openoju-prod"
    data = provision.tfvars_for(gcp)
    assert data["project_id"] == "openoju-prod"

    azure = provision.default_answers("prod", "azure")
    azure["azure_subscription"] = "00000000-0000-0000-0000-000000000000"
    data = provision.tfvars_for(azure)
    assert data["subscription_id"] == azure["azure_subscription"]
    assert data["create_bucket"] is False

    magalu = provision.default_answers("prod", "magalu")
    magalu["mgc_key_pair_id"] = "abc"
    data = provision.tfvars_for(magalu)
    assert data["mgc_key_pair_id"] == "abc"
    assert "mgc_key_pair_secret" not in data
    assert "mgc_api_key" not in data


def test_answers_keep_provider_identifiers_but_no_secrets(env_root):
    answers = provision.default_answers("prod", "gcp")
    answers["gcp_project"] = "openoju-prod"
    directory = provision.render_environment(answers)
    tfvars = (directory / "terraform.tfvars").read_text(encoding="utf-8")
    secrets = provision.read_env_file(directory / "secrets.env")
    assert "project_id" in tfvars
    for value in secrets.values():
        assert value not in tfvars


def test_aws_managed_storage_does_not_generate_static_s3_keys():
    answers = provision.default_answers("prod", "aws")
    answers["storage"] = "managed"
    secrets = provision.secrets_for(answers)
    assert "OJU_S3_ACCESS_KEY" not in secrets
    assert "OJU_S3_SECRET_KEY" not in secrets

    bundled = provision.default_answers("dev", "local")
    bundled_secrets = provision.secrets_for(bundled)
    assert "OJU_S3_ACCESS_KEY" in bundled_secrets


def test_render_preserves_terraform_outputs(env_root):
    answers = provision.default_answers("prod", "gcp")
    answers["gcp_project"] = "openoju-prod"
    directory = provision.render_environment(answers)
    (directory / "outputs.json").write_text(
        '{"bucket": "openoju-prod-media", "s3_endpoint": "https://storage.googleapis.com", '
        '"service_account_annotations": {"iam.gke.io/gcp-service-account": "sa@x"}}',
        encoding="utf-8",
    )
    provision.render_environment(answers)
    values = (directory / "values.yaml").read_text(encoding="utf-8")
    assert "OJU_S3_BUCKET: openoju-prod-media" in values
    assert "iam.gke.io/gcp-service-account: sa@x" in values
