from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import provision  # noqa: E402


def test_loads_secrets_without_overriding_environment(tmp_path, monkeypatch):
    monkeypatch.setattr(provision, "SECRETS_DIR", tmp_path)
    (tmp_path / "aws.env").write_text(
        "# comentário\nexport AWS_REGION=us-east-1\nexport AWS_PROFILE='openoju'\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("AWS_REGION", raising=False)
    monkeypatch.setenv("AWS_PROFILE", "existing")

    provision.load_cloud_credentials("aws")

    assert os.environ["AWS_REGION"] == "us-east-1"
    assert os.environ["AWS_PROFILE"] == "existing"


def test_ignores_local_missing_and_disabled(tmp_path, monkeypatch):
    monkeypatch.setattr(provision, "SECRETS_DIR", tmp_path)
    monkeypatch.setenv("AWS_REGION", "sa-east-1")
    assert provision.load_cloud_credentials("local") is None
    assert provision.load_cloud_credentials("gcp") is None
    assert provision.load_cloud_credentials("aws", enabled=False) is None
    assert os.environ["AWS_REGION"] == "sa-east-1"


def test_env_defaults_fill_identifiers(monkeypatch):
    monkeypatch.setenv("AZURE_SUBSCRIPTION_ID", "sub-123")
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "proj-123")
    azure = {"target": "azure", "azure_subscription": ""}
    gcp = {"target": "gcp", "gcp_project": ""}
    provision.apply_env_defaults(azure)
    provision.apply_env_defaults(gcp)
    assert azure["azure_subscription"] == "sub-123"
    assert gcp["gcp_project"] == "proj-123"


def test_default_answers_use_environment(monkeypatch):
    monkeypatch.setenv("AZURE_SUBSCRIPTION_ID", "sub-abc")
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "proj-abc")
    monkeypatch.setenv("AWS_REGION", "sa-east-1")
    assert provision.default_answers("x", "azure")["azure_subscription"] == "sub-abc"
    assert provision.default_answers("x", "gcp")["gcp_project"] == "proj-abc"
    assert provision.default_answers("x", "aws")["region"] == "sa-east-1"
