#!/usr/bin/env python3
"""OpenOju provisioning wizard.

Interactive helper that turns a few questions into a deployable environment:
Helm values, Terraform variables, the Kubernetes Secret and a runbook.

Only the Python standard library is used, so it runs on any host with
``python3`` (no virtualenv, no dependencies).

    python3 scripts/provision.py init --env prod
    python3 scripts/provision.py doctor --env prod
    python3 scripts/provision.py plan --env prod
    python3 scripts/provision.py apply --env prod
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEPLOY = ROOT / "deploy"
ENVIRONMENTS = DEPLOY / "environments"
CHART = DEPLOY / "helm" / "openoju"
TERRAFORM = DEPLOY / "terraform" / "stacks"

STATE_SCHEMA = 1

TARGETS: dict[str, dict[str, object]] = {
    "local": {
        "label": "Cluster local (kind/k3d) ou Docker Desktop",
        "terraform": None,
        "cloud": False,
        "managed_db": False,
        "managed_storage": False,
        "vaapi": False,
        "ingress_class": "nginx",
        "node_pool": False,
        "secret": "create",
    },
    "onprem": {
        "label": "Kubernetes on-premise (k3s/RKE2/Talos/kubeadm)",
        "terraform": "onprem",
        "cloud": False,
        "managed_db": False,
        "managed_storage": False,
        "vaapi": True,
        "ingress_class": "nginx",
        "node_pool": False,
        "secret": "create",
    },
    "aws": {
        "label": "AWS (EKS + RDS + S3)",
        "terraform": "aws",
        "cloud": True,
        "managed_db": True,
        "managed_storage": True,
        "vaapi": False,
        "ingress_class": "alb",
        "node_pool": True,
        "secret": "terraform",
    },
    "azure": {
        "label": "Azure (AKS + Flexible Server + MinIO)",
        "terraform": "azure",
        "cloud": True,
        "managed_db": True,
        "managed_storage": False,
        "vaapi": False,
        "ingress_class": "nginx",
        "node_pool": True,
        "secret": "terraform",
    },
    "gcp": {
        "label": "GCP (GKE + Cloud SQL + GCS)",
        "terraform": "gcp",
        "cloud": True,
        "managed_db": True,
        "managed_storage": True,
        "vaapi": False,
        "ingress_class": "gce",
        "node_pool": True,
        "secret": "terraform",
    },
    "magalu": {
        "label": "Magalu Cloud (MKE + DBaaS + Object Storage) [experimental]",
        "terraform": "magalu",
        "cloud": True,
        "managed_db": True,
        "managed_storage": True,
        "vaapi": False,
        "ingress_class": "nginx",
        "node_pool": True,
        "secret": "terraform",
    },
}

TLS_MODES = {
    "cert-manager": "ingress-nginx + cert-manager (Let's Encrypt)",
    "cloud": "Certificado gerenciado pelo balanceador da nuvem",
    "existing": "Secret TLS já existente no cluster",
    "none": "Sem TLS (apenas laboratório)",
}

OIDC_PROVIDERS = {
    "none": "Sem SSO (login local)",
    "entra": "Microsoft Entra ID",
    "google": "Google Workspace",
    "keycloak": "Keycloak",
}

REGISTRIES = {
    "ghcr": "ghcr.io (imagem pública)",
    "ecr": "Amazon ECR",
    "acr": "Azure Container Registry",
    "gar": "Google Artifact Registry",
    "magalu": "Magalu Cloud Container Registry",
}

SECRET_KEYS = (
    "OJU_SECRET_KEY",
    "OJU_FERNET_KEY",
    "OJU_SETUP_TOKEN",
    "OJU_S3_ACCESS_KEY",
    "OJU_S3_SECRET_KEY",
)


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------


class ProvisionError(RuntimeError):
    pass


def env_dir(name: str) -> Path:
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{1,30}", name):
        raise ProvisionError(
            "nome do ambiente deve ter 2-31 caracteres: a-z, 0-9 e hífen"
        )
    return ENVIRONMENTS / name


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def generate_password(length: int = 32) -> str:
    return secrets.token_urlsafe(length)


def generate_fernet_key() -> str:
    # 32 bytes encoded as urlsafe base64: exactly what Fernet expects.
    return base64.urlsafe_b64encode(secrets.token_bytes(32)).decode()


def generate_secret_key() -> str:
    return base64.urlsafe_b64encode(secrets.token_bytes(36)).decode()


def read_yaml_like(path: Path) -> dict:
    """Read the flat ``key: value`` files the wizard writes.

    ``answers.yaml`` and ``terraform.tfvars`` are flat by design, so a full YAML
    parser is unnecessary (and the wizard must stay stdlib-only).
    """
    data: dict[str, str] = {}
    if not path.exists():
        return data
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" in stripped:
            continue
        if ":" not in stripped:
            continue
        key, value = stripped.split(":", 1)
        value = value.strip().strip('"').strip("'")
        data[key.strip()] = value
    return data


def dump_scalar(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return '""'
    if isinstance(value, (int, float)):
        return str(value)
    text = str(value)
    if text == "" or re.search(r"[:#\[\]{}]|^\s|\s$", text) or text in {
        "true",
        "false",
        "null",
        "yes",
        "no",
        "on",
        "off",
    }:
        return json.dumps(text)
    return text


def dump_yaml(data: dict, indent: int = 0) -> str:
    """Minimal deterministic YAML emitter for the wizard's own structures."""
    lines: list[str] = []
    pad = " " * indent
    for key, value in data.items():
        if isinstance(value, dict):
            if not value:
                lines.append(f"{pad}{key}: {{}}")
            else:
                lines.append(f"{pad}{key}:")
                lines.append(dump_yaml(value, indent + 2))
        elif isinstance(value, list):
            if not value:
                lines.append(f"{pad}{key}: []")
            else:
                lines.append(f"{pad}{key}:")
                for item in value:
                    if isinstance(item, dict):
                        lines.append(f"{pad}  -")
                        lines.append(dump_yaml(item, indent + 4))
                    else:
                        lines.append(f"{pad}  - {dump_scalar(item)}")
        else:
            lines.append(f"{pad}{key}: {dump_scalar(value)}")
    return "\n".join(line for line in lines if line != "")


def dump_tfvars(data: dict, indent: int = 0) -> str:
    lines: list[str] = []
    pad = " " * indent
    for key, value in data.items():
        if isinstance(value, dict):
            lines.append(f"{pad}{key} = {{")
            lines.append(dump_tfvars(value, indent + 2))
            lines.append(f"{pad}}}")
        elif isinstance(value, list):
            rendered = ", ".join(json.dumps(str(item)) for item in value)
            lines.append(f"{pad}{key} = [{rendered}]")
        elif isinstance(value, bool):
            lines.append(f"{pad}{key} = {'true' if value else 'false'}")
        elif isinstance(value, (int, float)):
            lines.append(f"{pad}{key} = {value}")
        else:
            lines.append(f"{pad}{key} = {json.dumps(str(value))}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Interaction
# ---------------------------------------------------------------------------


class Prompter:
    def __init__(self, assume_yes: bool = False) -> None:
        self.assume_yes = assume_yes
        self.non_interactive = assume_yes or not sys.stdin.isatty()

    def ask(self, question: str, default: str, *, choices: list[str] | None = None) -> str:
        if self.non_interactive:
            return default
        suffix = f" [{default}]" if default else ""
        if choices:
            options = " / ".join(choices)
            suffix = f" ({options}) [{default}]"
        while True:
            try:
                answer = input(f"? {question}{suffix}: ").strip()
            except EOFError:
                return default
            if not answer:
                return default
            if choices and answer not in choices:
                print(f"  escolha inválida: {answer}")
                continue
            return answer

    def confirm(self, question: str, default: bool = False) -> bool:
        if self.non_interactive:
            return default
        answer = self.ask(question, "s" if default else "n", choices=["s", "n"])
        return answer == "s"


# ---------------------------------------------------------------------------
# Answers
# ---------------------------------------------------------------------------


def default_answers(name: str, target: str) -> dict[str, str]:
    spec = TARGETS[target]
    local = target == "local"
    domain = "localhost" if local else "openoju.example.com"
    return {
        "environment": name,
        "target": target,
        "domain": domain,
        "namespace": "openoju",
        "release": "openoju",
        "tls": "none" if local else "cert-manager",
        "database": "managed" if spec["managed_db"] else "bundled",
        "storage": "managed" if spec["managed_storage"] else "bundled",
        "api_replicas": "2" if spec["cloud"] else "1",
        "vaapi": "on" if spec["vaapi"] else "off",
        "oidc": "none",
        "registry": "ghcr",
        "cluster_mode": "create" if spec["cloud"] else "existing",
        "region": {
            "aws": "us-east-1",
            "gcp": "us-central1",
            "azure": "brazilsouth",
            "magalu": "br-se1",
        }.get(target, ""),
        "node_count": "2",
        "db_instance": {
            "aws": "db.t4g.medium",
            "gcp": "db-custom-2-4096",
            "azure": "GP_Standard_D2ds_v5",
            "magalu": "small",
        }.get(target, ""),
    }


def collect_answers(args: argparse.Namespace, prompter: Prompter) -> dict[str, str]:
    name = args.env
    answers_file = Path(args.answers) if args.answers else env_dir(name) / "answers.yaml"
    base = default_answers(name, args.target or "local")
    if answers_file.exists():
        base.update({k: v for k, v in read_yaml_like(answers_file).items() if v})

    target = args.target or prompter.ask(
        "Onde o OpenOju vai rodar?", base["target"], choices=list(TARGETS)
    )
    base["target"] = target
    spec = TARGETS[target]
    defaults = default_answers(name, target)

    domain = prompter.ask("Domínio público", base.get("domain") or defaults["domain"])
    base["domain"] = domain
    base["namespace"] = prompter.ask("Namespace do Kubernetes", base["namespace"])
    base["release"] = prompter.ask("Nome do release Helm", base["release"])
    base["tls"] = prompter.ask(
        "Como terminar o TLS?", base["tls"], choices=list(TLS_MODES)
    )
    base["database"] = prompter.ask(
        "Banco de dados", base["database"], choices=["managed", "bundled"]
    )
    if base["database"] == "managed" and not spec["managed_db"]:
        print("  aviso: este alvo não tem banco gerenciado no Terraform; usando bundled")
        base["database"] = "bundled"
    base["storage"] = prompter.ask(
        "Object storage", base["storage"], choices=["managed", "bundled"]
    )
    if base["storage"] == "managed" and not spec["managed_storage"]:
        print("  aviso: Azure Blob não fala S3; usando MinIO no cluster")
        base["storage"] = "bundled"
    base["api_replicas"] = prompter.ask(
        "Réplicas da API", base["api_replicas"], choices=["1", "2", "3"]
    )
    base["vaapi"] = prompter.ask(
        "Aceleração VAAPI (ffmpeg)?", base["vaapi"], choices=["on", "off"]
    )
    base["oidc"] = prompter.ask("SSO OIDC", base["oidc"], choices=list(OIDC_PROVIDERS))
    base["registry"] = prompter.ask(
        "Registry da imagem", base["registry"], choices=list(REGISTRIES)
    )
    if spec["cloud"]:
        base["cluster_mode"] = prompter.ask(
            "Cluster", base["cluster_mode"], choices=["create", "existing"]
        )
        base["region"] = prompter.ask("Região", base["region"])
        base["node_count"] = prompter.ask("Nós do pool de aplicação", base["node_count"])
        base["db_instance"] = prompter.ask("Classe da instância do banco", base["db_instance"])
    base["features"] = "provisioning"
    return base


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def values_for(answers: dict[str, str]) -> dict:
    target = answers["target"]
    spec = TARGETS[target]
    domain = answers["domain"]
    replicas = int(answers["api_replicas"])
    tls = answers["tls"]
    storage = answers["storage"]

    values: dict = {
        "replicaCount": {
            "api": replicas,
            "worker": max(1, replicas if spec["cloud"] else 1),
            "dispatcher": 1,
            "maintenance": 1,
        },
        "serviceAccount": {"create": True, "annotations": {}},
        "existingSecret": f'{answers["release"]}-secrets',
        "secrets": {"create": spec["secret"] == "create", "databaseUrl": ""},
        "config": {
            "OJU_PUBLIC_BASE_URL": f"https://{domain}" if tls != "none" else f"http://{domain}",
            "OJU_FRONTEND_BASE_URL": f"https://{domain}" if tls != "none" else f"http://{domain}",
            "OJU_CORS_ORIGINS": f"https://{domain}" if tls != "none" else f"http://{domain}",
            "OJU_COOKIE_SECURE": "true" if tls != "none" else "false",
            "OJU_STORAGE_BACKEND": "s3",
            "OJU_S3_BUCKET": f"openoju-{answers['environment']}",
            "OJU_S3_CREATE_BUCKET": "false",
            "OJU_RATE_LIMIT_BACKEND": "postgres" if replicas > 1 else "memory",
        },
        "media": {"mode": "emptyDir", "emptyDir": {"sizeLimit": "50Gi"}},
        "data": {"mode": "emptyDir"},
        "vaapi": {"enabled": answers["vaapi"] == "on", "groupAdd": [110]},
        "postgresql": {"enabled": answers["database"] == "bundled"},
        "minio": {"enabled": storage == "bundled"},
        "pdb": {"enabled": replicas > 1},
        "networkPolicy": {"enabled": bool(spec["cloud"])},
        "ingress": {
            "enabled": tls != "none",
            "className": spec["ingress_class"],
            "annotations": {},
            "hosts": [{"host": domain, "paths": [{"path": "/", "pathType": "Prefix"}]}],
            "tls": [],
        },
    }

    if answers["vaapi"] == "on":
        values["nodeSelector"] = {"openoju.io/pool": "app"}

    if spec["cloud"]:
        values["nodeSelector"] = {"openoju.io/pool": "app"}

    release = answers["release"]
    if tls == "cert-manager":
        values["ingress"]["annotations"] = {
            "cert-manager.io/cluster-issuer": "letsencrypt-prod",
            "nginx.ingress.kubernetes.io/proxy-body-size": "0",
            "nginx.ingress.kubernetes.io/proxy-read-timeout": "3600",
        }
        values["ingress"]["tls"] = [{"hosts": [domain], "secretName": f"{release}-tls"}]
    elif tls == "existing":
        values["ingress"]["tls"] = [{"hosts": [domain], "secretName": f"{release}-tls"}]

    if target == "aws":
        values["ingress"]["annotations"] = {
            "alb.ingress.kubernetes.io/scheme": "internet-facing",
            "alb.ingress.kubernetes.io/target-type": "ip",
            "alb.ingress.kubernetes.io/listen-ports": '[{"HTTPS":443}]',
            "alb.ingress.kubernetes.io/ssl-redirect": "443",
            "alb.ingress.kubernetes.io/load-balancer-attributes": "idle_timeout.timeout_seconds=3600",
        }
        values["config"]["OJU_S3_ENDPOINT"] = (
            f"https://s3.{answers['region']}.amazonaws.com"
        )
        values["config"]["OJU_S3_REGION"] = answers["region"]
    elif target == "gcp":
        values["config"]["OJU_S3_ENDPOINT"] = "https://storage.googleapis.com"
        values["config"]["OJU_S3_INTERNAL_ENDPOINT"] = "https://storage.googleapis.com"
        values["config"]["OJU_S3_REGION"] = "auto"
        values["ingress"]["annotations"] = {
            "kubernetes.io/ingress.allow-http": "false",
            "networking.gke.io/managed-certificates": f"{release}-cert",
        }
    elif target == "magalu":
        values["config"]["OJU_S3_ENDPOINT"] = "https://br-se1.magaluobjects.com"
        values["config"]["OJU_S3_INTERNAL_ENDPOINT"] = "https://br-se1.magaluobjects.com"
        values["config"]["OJU_S3_REGION"] = answers["region"]

    if storage == "bundled":
        values["config"]["OJU_S3_INTERNAL_ENDPOINT"] = (
            f"http://{release}-openoju-minio:9000"
        )
        if target == "local":
            values["config"]["OJU_S3_ENDPOINT"] = "http://localhost:9000"
            values["minio"]["public"] = {
                "enabled": False,
                "host": "",
                "className": "",
                "tlsSecret": "",
            }
        else:
            values["config"]["OJU_S3_ENDPOINT"] = f"https://s3.{domain}"
            values["minio"]["public"] = {
                "enabled": True,
                "host": f"s3.{domain}",
                "className": spec["ingress_class"],
                "tlsSecret": f"{release}-minio-tls",
            }

    if answers["oidc"] != "none":
        issuer = {
            "entra": "https://login.microsoftonline.com/<tenant>/v2.0",
            "google": "https://accounts.google.com",
            "keycloak": f"https://sso.{domain}/realms/openoju",
        }[answers["oidc"]]
        values["config"].update(
            {
                "OJU_OIDC_ENABLED": "true",
                "OJU_OIDC_ISSUER": issuer,
                "OJU_OIDC_CLIENT_ID": "<preencher>",
                "OJU_OIDC_REDIRECT_URI": f"https://{domain}/api/v1/auth/oidc/callback",
            }
        )

    return values


def tfvars_for(answers: dict[str, str]) -> dict:
    target = answers["target"]
    spec = TARGETS[target]
    if not spec["terraform"]:
        return {}
    data: dict = {
        "environment": answers["environment"],
        "region": answers["region"],
        "node_count": int(answers["node_count"]),
        "cluster_mode": answers["cluster_mode"],
        "domain": answers["domain"],
        "namespace": answers["namespace"],
        "release_name": answers["release"],
        "db_instance_class": answers["db_instance"],
        "create_database": answers["database"] == "managed",
        "create_bucket": answers["storage"] == "managed",
    }
    if target == "azure":
        data["create_bucket"] = False
    return data


def secrets_for(answers: dict[str, str], previous: dict[str, str] | None = None) -> dict[str, str]:
    previous = previous or {}
    values = {
        "OJU_SECRET_KEY": previous.get("OJU_SECRET_KEY") or generate_secret_key(),
        "OJU_FERNET_KEY": previous.get("OJU_FERNET_KEY") or generate_fernet_key(),
        "OJU_SETUP_TOKEN": previous.get("OJU_SETUP_TOKEN") or generate_password(24),
        "OJU_S3_ACCESS_KEY": previous.get("OJU_S3_ACCESS_KEY") or f"oju{secrets.token_hex(8)}",
        "OJU_S3_SECRET_KEY": previous.get("OJU_S3_SECRET_KEY") or generate_password(32),
    }
    if answers["database"] == "bundled":
        values["postgres-password"] = previous.get("postgres-password") or generate_password(
            24
        )
        values["OJU_DATABASE_URL"] = (
            "postgresql+psycopg://openoju:"
            f"{values['postgres-password']}@{answers['release']}-openoju-postgresql:5432/openoju"
        )
    return values


def render_environment(answers: dict[str, str], *, force: bool = False) -> Path:
    directory = env_dir(answers["environment"])
    directory.mkdir(parents=True, exist_ok=True)

    secrets_path = directory / "secrets.env"
    previous = read_env_file(secrets_path) if secrets_path.exists() else {}
    new_secrets = secrets_for(answers, previous)

    values = values_for(answers)
    (directory / "answers.yaml").write_text(
        "# Gerado por scripts/provision.py — não contém segredos.\n"
        + dump_yaml(answers)
        + "\n",
        encoding="utf-8",
    )
    (directory / "values.yaml").write_text(
        "# Gerado por scripts/provision.py a partir de answers.yaml.\n"
        + dump_yaml(values)
        + "\n",
        encoding="utf-8",
    )

    tfvars = tfvars_for(answers)
    if tfvars:
        (directory / "terraform.tfvars").write_text(
            "# Gerado por scripts/provision.py.\n" + dump_tfvars(tfvars) + "\n",
            encoding="utf-8",
        )

    lines = ["# Gerado por scripts/provision.py — NUNCA versionar."]
    lines += [f"{key}={value}" for key, value in new_secrets.items()]
    secrets_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    secrets_path.chmod(0o600)

    state = {
        "schema": STATE_SCHEMA,
        "environment": answers["environment"],
        "target": answers["target"],
        "rendered_at": utcnow(),
        "values_sha": hashlib_sha((directory / "values.yaml").read_bytes()),
        "answers": answers,
    }
    (directory / "state.json").write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    (directory / "runbook.md").write_text(runbook_for(answers), encoding="utf-8")
    return directory


def read_env_file(path: Path) -> dict[str, str]:
    data: dict[str, str] = {}
    if not path.exists():
        return data
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        data[key.strip()] = value.strip()
    return data


def hashlib_sha(data: bytes) -> str:
    import hashlib

    return hashlib.sha256(data).hexdigest()


def runbook_for(answers: dict[str, str]) -> str:
    target = answers["target"]
    directory = env_dir(answers["environment"])
    try:
        rel: object = directory.relative_to(ROOT)
    except ValueError:  # test or custom environment root
        rel = directory
    lines = [
        f"# Runbook — {answers['environment']} ({target})",
        "",
        f"Gerado em {utcnow()} por `scripts/provision.py`.",
        "",
        "## Caminhos",
        "",
        "```text",
        f"{rel}/answers.yaml       respostas (versionável)",
        f"{rel}/values.yaml        valores do Helm",
        f"{rel}/secrets.env        segredos (600, gitignored)",
        f"{rel}/terraform.tfvars   variáveis do Terraform",
        "```",
        "",
        "## Sequência",
        "",
        "```bash",
        f"python3 scripts/provision.py doctor --env {answers['environment']}",
        f"python3 scripts/provision.py plan   --env {answers['environment']}",
        f"python3 scripts/provision.py apply  --env {answers['environment']}",
        "```",
        "",
    ]
    if TARGETS[target]["terraform"]:
        lines += [
            "## Infraestrutura",
            "",
            f"Stack: `deploy/terraform/stacks/{TARGETS[target]['terraform']}`.",
            "O `plan` deve ser revisado antes do `apply`. O wizard lê os outputs",
            "(`database_url`, `bucket`, `service_account_annotations`) e injeta",
            "no Secret e nos values.",
            "",
        ]
    if answers["database"] == "bundled":
        lines += [
            "## Banco embutido",
            "",
            f"Postgres em `{answers['release']}-openoju-postgresql:5432`.",
            "Backup: `pg_dump` a partir do pod do Postgres.",
            "",
        ]
    if answers["storage"] == "bundled":
        lines += [
            "## Object storage embutido",
            "",
            f"MinIO interno em `{answers['release']}-openoju-minio:9000`.",
            f"Endpoint público: `https://s3.{answers['domain']}` (precisa de DNS).",
            "",
        ]
    lines += [
        "## Primeiro acesso",
        "",
        "```bash",
        f"kubectl -n {answers['namespace']} get secret {answers['release']}-secrets -o jsonpath='{{.data.OJU_SETUP_TOKEN}}' | base64 -d",
        "```",
        "",
        "Use o token em `POST /api/v1/auth/setup`.",
        "",
        "## Checklist pós-apply",
        "",
        "- [ ] DNS do host público aponta para o ingress/load balancer",
        "- [ ] CORS do bucket inclui a origem pública",
        "- [ ] `helm test` verde",
        "- [ ] setup inicial concluído",
        "- [ ] upload de vídeo e job de análise concluídos",
        "- [ ] `/api/v1/jobs/{id}/log` responde com a API em outra réplica",
        "",
    ]
    if target in {"aws", "gcp", "azure", "magalu"}:
        lines += [
            "## Verificação pendente",
            "",
            "Esta trilha não foi validada em ambiente real. Rode `plan`, revise o",
            "`terraform plan` e registre o resultado em",
            "`docs/provisioning/verification.md`.",
            "",
        ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Tooling
# ---------------------------------------------------------------------------


def which(binary: str) -> str | None:
    return shutil.which(binary)


def run(cmd: list[str], *, cwd: Path | None = None, capture: bool = False) -> str:
    print(f"$ {' '.join(cmd)}")
    try:
        result = subprocess.run(
            cmd,
            cwd=str(cwd or ROOT),
            text=True,
            capture_output=capture,
            check=True,
        )
    except FileNotFoundError as exc:
        raise ProvisionError(f"binário não encontrado: {cmd[0]}") from exc
    except subprocess.CalledProcessError as exc:
        raise ProvisionError(f"comando falhou ({exc.returncode}): {' '.join(cmd)}") from exc
    return result.stdout if capture else ""


def doctor(answers: dict[str, str]) -> list[str]:
    target = answers["target"]
    spec = TARGETS[target]
    problems: list[str] = []
    required = ["helm", "kubectl"]
    if spec["terraform"] and answers["cluster_mode"] == "create":
        required.append("terraform")
    cloud_cli = {"aws": "aws", "gcp": "gcloud", "azure": "az", "magalu": "mgc"}
    if target in cloud_cli:
        required.append(cloud_cli[target])

    print("Ferramentas")
    for binary in required:
        path = which(binary)
        print(f"  {'ok  ' if path else 'falta'} {binary}{f' ({path})' if path else ''}")
        if not path:
            problems.append(f"instale {binary}")

    print("\nContexto")
    if which("kubectl"):
        try:
            context = run(["kubectl", "config", "current-context"], capture=True).strip()
            print(f"  kubeconfig: {context or '<vazio>'}")
            if not context:
                problems.append("kubeconfig sem contexto atual")
        except ProvisionError:
            problems.append("kubectl não conseguiu ler o kubeconfig")
    if spec["terraform"] and answers["cluster_mode"] == "create":
        stack = TERRAFORM / str(spec["terraform"])
        if not stack.exists():
            problems.append(f"stack Terraform ausente: {stack.relative_to(ROOT)}")
        else:
            print(f"  stack Terraform: {stack.relative_to(ROOT)}")
    secrets_path = env_dir(answers["environment"]) / "secrets.env"
    if secrets_path.exists():
        mode = oct(secrets_path.stat().st_mode)[-3:]
        print(f"  secrets.env: permissão {mode}")
        if mode != "600":
            problems.append(f"chmod 600 {secrets_path.relative_to(ROOT)}")
        missing = [key for key in SECRET_KEYS if key not in read_env_file(secrets_path)]
        if missing and TARGETS[answers["target"]]["secret"] == "create":
            problems.append(f"faltam chaves em secrets.env: {', '.join(missing)}")
    else:
        problems.append("secrets.env ausente; rode init")

    return problems


# ---------------------------------------------------------------------------
# Actions
# ---------------------------------------------------------------------------


def load_answers(name: str) -> dict[str, str]:
    directory = env_dir(name)
    path = directory / "answers.yaml"
    if not path.exists():
        raise ProvisionError(
            f"ambiente {name!r} não existe; rode: python3 scripts/provision.py init --env {name}"
        )
    answers = read_yaml_like(path)
    if answers.get("target") not in TARGETS:
        raise ProvisionError("answers.yaml inválido: target desconhecido")
    return answers


def action_init(args: argparse.Namespace) -> int:
    prompter = Prompter(args.yes)
    directory = env_dir(args.env)
    if directory.exists() and (directory / "answers.yaml").exists() and not args.force:
        if not prompter.confirm(f"Ambiente {args.env} já existe. Sobrescrever?", False):
            print("nada a fazer")
            return 0
    answers = collect_answers(args, prompter)
    directory = render_environment(answers, force=True)
    print(f"\nambiente gerado em {directory.relative_to(ROOT)}")
    print("segredos em secrets.env (600, gitignored)")
    print(f"próximo passo: python3 scripts/provision.py doctor --env {args.env}")
    return 0


def action_doctor(args: argparse.Namespace) -> int:
    answers = load_answers(args.env)
    problems = doctor(answers)
    if problems:
        print("\nPendências:")
        for problem in problems:
            print(f"  - {problem}")
        return 1
    print("\ntudo pronto")
    return 0


def action_render(args: argparse.Namespace) -> int:
    answers = load_answers(args.env)
    render_environment(answers)
    print(f"values.yaml atualizado em {env_dir(args.env).relative_to(ROOT)}")
    return 0


def terraform_stack(answers: dict[str, str]) -> Path | None:
    spec = TARGETS[answers["target"]]
    if not spec["terraform"] or answers["cluster_mode"] == "existing":
        return None
    return TERRAFORM / str(spec["terraform"])


def action_plan(args: argparse.Namespace) -> int:
    answers = load_answers(args.env)
    directory = env_dir(args.env)
    stack = terraform_stack(answers)
    if stack is not None:
        if not stack.exists():
            raise ProvisionError(f"stack Terraform ausente: {stack.relative_to(ROOT)}")
        run(["terraform", "init", "-input=false"], cwd=stack)
        run(["terraform", "plan", f"-var-file={directory / 'terraform.tfvars'}"], cwd=stack)
    rendered = run(
        [
            "helm",
            "template",
            answers["release"],
            str(CHART),
            "-n",
            answers["namespace"],
            "-f",
            str(directory / "values.yaml"),
        ],
        capture=True,
    )
    (directory / "render.yaml").write_text(rendered, encoding="utf-8")
    print(f"helm template ok -> {(directory / 'render.yaml').relative_to(ROOT)}")
    return 0


def action_apply(args: argparse.Namespace) -> int:
    answers = load_answers(args.env)
    directory = env_dir(args.env)
    problems = doctor(answers)
    if problems:
        for problem in problems:
            print(f"  - {problem}")
        raise ProvisionError("doctor encontrou pendências")

    secrets_path = directory / "secrets.env"
    secret_values = read_env_file(secrets_path)

    values_path = directory / "values.yaml"
    values = values_for(answers)

    stack = terraform_stack(answers)
    if stack is not None:
        run(["terraform", "init", "-input=false"], cwd=stack)
        run(
            [
                "terraform",
                "apply",
                "-auto-approve",
                "-input=false",
                f"-var-file={directory / 'terraform.tfvars'}",
            ],
            cwd=stack,
        )
        raw = run(["terraform", "output", "-json"], cwd=stack, capture=True)
        outputs = json.loads(raw or "{}")
        database_url = outputs.get("database_url", {}).get("value")
        if database_url:
            secret_values["OJU_DATABASE_URL"] = database_url
        bucket = outputs.get("bucket", {}).get("value")
        if bucket:
            values["config"]["OJU_S3_BUCKET"] = bucket
        annotations = outputs.get("service_account_annotations", {}).get("value")
        if annotations:
            values.setdefault("serviceAccount", {})["annotations"] = annotations
        values_path.write_text(
            "# Gerado por scripts/provision.py a partir de answers.yaml.\n"
            + dump_yaml(values)
            + "\n",
            encoding="utf-8",
        )

    namespace = answers["namespace"]
    ensure_namespace(namespace)

    env_args: list[str] = []
    for key, value in secret_values.items():
        env_args += [f"--from-literal={key}={value}"]
    secret_manifest = run(
        [
            "kubectl",
            "-n",
            namespace,
            "create",
            "secret",
            "generic",
            f"{answers['release']}-secrets",
            *env_args,
            "--dry-run=client",
            "-o",
            "yaml",
        ],
        capture=True,
    )
    apply_stdin(secret_manifest)

    run(
        [
            "helm",
            "upgrade",
            "--install",
            answers["release"],
            str(CHART),
            "-n",
            namespace,
            "--create-namespace",
            "-f",
            str(directory / "values.yaml"),
        ]
    )
    run(
        [
            "kubectl",
            "-n",
            namespace,
            "rollout",
            "status",
            f"deployment/{answers['release']}-openoju-api",
            "--timeout=600s",
        ]
    )
    run(["helm", "test", answers["release"], "-n", namespace, "--timeout=300s"])
    print("\naplicado. runbook:", (directory / "runbook.md").relative_to(ROOT))
    return 0


def ensure_namespace(namespace: str) -> None:
    if not namespace_exists(namespace):
        run(["kubectl", "create", "namespace", namespace], capture=True)


def namespace_exists(namespace: str) -> bool:
    try:
        run(["kubectl", "get", "namespace", namespace], capture=True)
        return True
    except ProvisionError:
        return False


def apply_stdin(manifest: str) -> None:
    print("$ kubectl apply -f - (secret)")
    try:
        subprocess.run(
            ["kubectl", "apply", "-f", "-"],
            input=manifest,
            text=True,
            check=True,
            cwd=str(ROOT),
        )
    except subprocess.CalledProcessError as exc:
        raise ProvisionError("falha ao aplicar o Secret") from exc


def action_destroy(args: argparse.Namespace) -> int:
    answers = load_answers(args.env)
    prompter = Prompter(assume_yes=False)
    if not args.yes:
        typed = prompter.ask(
            f"Digite o nome do ambiente ({answers['environment']}) para destruir",
            "",
        )
        if typed != answers["environment"]:
            print("cancelado")
            return 1
    run(
        [
            "helm",
            "uninstall",
            answers["release"],
            "-n",
            answers["namespace"],
            "--ignore-not-found",
        ]
    )
    run(
        [
            "kubectl",
            "-n",
            answers["namespace"],
            "delete",
            "secret",
            f"{answers['release']}-secrets",
            "--ignore-not-found",
        ]
    )
    stack = terraform_stack(answers)
    if stack is not None:
        directory = env_dir(args.env)
        run(
            [
                "terraform",
                "destroy",
                "-auto-approve",
                f"-var-file={directory / 'terraform.tfvars'}",
            ],
            cwd=stack,
        )
    print("destruído")
    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="provision.py",
        description="Wizard de provisionamento do OpenOju (Kubernetes, on-prem e nuvem).",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    def add_env(p: argparse.ArgumentParser) -> None:
        p.add_argument("--env", "-e", default="dev", help="nome do ambiente")
        p.add_argument("--yes", "-y", action="store_true", help="não interativo")
        p.add_argument("--verbose", "-v", action="store_true", help="saída detalhada")

    p_init = sub.add_parser("init", help="perguntas e geração do ambiente")
    add_env(p_init)
    p_init.add_argument("--target", choices=list(TARGETS), help="alvo de provisionamento")
    p_init.add_argument("--answers", help="arquivo de respostas para modo não interativo")
    p_init.add_argument("--force", action="store_true", help="sobrescrever ambiente existente")
    p_init.set_defaults(func=action_init)

    for name, func, help_text in (
        ("doctor", action_doctor, "verifica ferramentas, credenciais e arquivos"),
        ("render", action_render, "regenera values.yaml a partir de answers.yaml"),
        ("plan", action_plan, "terraform plan + helm template"),
        ("apply", action_apply, "terraform apply + Secret + helm upgrade"),
        ("destroy", action_destroy, "helm uninstall + terraform destroy"),
    ):
        p = sub.add_parser(name, help=help_text)
        add_env(p)
        p.set_defaults(func=func)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except ProvisionError as exc:
        print(f"erro: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\ninterrompido", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
