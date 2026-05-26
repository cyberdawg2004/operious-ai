#!/usr/bin/env python3
"""
Operious AI Secret Rotation Guide

Interactive guide for rotating production secrets.
This script never reads, prints, or rotates secrets
automatically. It guides the operator through each step.

Usage:
    python scripts/rotate_secret.py
    python scripts/rotate_secret.py DATABASE_URL
    python scripts/rotate_secret.py ANTHROPIC_API_KEY
"""

from __future__ import annotations

import sys
from dataclasses import dataclass

APP_NAME = "operious-ai-imad"
BACKEND_URL = "https://operious-ai-imad.fly.dev"
COMMAND_CENTER_URL = "https://app.operious.com"
TENANT_ID = "anker-pilot"

PRE_ROTATION_HEALTH = (
    f"curl {BACKEND_URL}/api/v1/health"
)


@dataclass(frozen=True, slots=True)
class SecretGuide:
    description: str
    impact: str
    generate: str
    rotate_cmd: str
    verify_cmd: str
    rollback: str
    zero_downtime: bool
    notes: tuple[str, ...] = ()


SECRETS: dict[str, SecretGuide] = {
    "DATABASE_URL": SecretGuide(
        description="Neon Postgres app connection using the operious_app role",
        impact="All FastAPI database reads and writes under tenant RLS",
        generate=(
            "Neon console -> Settings -> Roles -> operious_app -> "
            "Reset password; copy the new postgresql+asyncpg URL"
        ),
        rotate_cmd=(
            "read -rsp \"New DATABASE_URL: \" NEW_DATABASE_URL; echo\n"
            f"fly secrets set DATABASE_URL=\"$NEW_DATABASE_URL\" --app {APP_NAME}\n"
            "unset NEW_DATABASE_URL"
        ),
        verify_cmd=(
            f"curl {BACKEND_URL}/api/v1/health\n"
            f"curl {BACKEND_URL}/api/v1/session/sessions "
            f"-H \"X-Tenant-ID: {TENANT_ID}\" | python3 -m json.tool | "
            "grep '\"total\"'"
        ),
        rollback=(
            f"fly secrets set DATABASE_URL=\"$PREVIOUS_DATABASE_URL\" --app {APP_NAME}"
        ),
        zero_downtime=True,
        notes=("Update local .env if local development uses the rotated URL.",),
    ),
    "ALEMBIC_DATABASE_URL": SecretGuide(
        description="Neon Postgres migration connection using the neondb_owner role",
        impact="Alembic migration commands only; running app traffic is unaffected",
        generate=(
            "Neon console -> Settings -> Roles -> neondb_owner -> "
            "Reset password; copy the new postgresql+asyncpg URL"
        ),
        rotate_cmd=(
            "read -rsp \"New ALEMBIC_DATABASE_URL: \" NEW_ALEMBIC_DATABASE_URL; echo\n"
            f"fly secrets set ALEMBIC_DATABASE_URL=\"$NEW_ALEMBIC_DATABASE_URL\" "
            f"--app {APP_NAME}\n"
            "unset NEW_ALEMBIC_DATABASE_URL"
        ),
        verify_cmd=(
            f"fly ssh console --app {APP_NAME} "
            "--command \"sh -lc 'cd /app && "
            "ALEMBIC_DATABASE_URL=\\$ALEMBIC_DATABASE_URL alembic current'\""
        ),
        rollback=(
            "fly secrets set ALEMBIC_DATABASE_URL="
            f"\"$PREVIOUS_ALEMBIC_DATABASE_URL\" --app {APP_NAME}"
        ),
        zero_downtime=True,
    ),
    "ANTHROPIC_API_KEY": SecretGuide(
        description="Anthropic API key for Diagnostic Agent LLM calls",
        impact="Cognition and diagnostic agent tasks that call Anthropic",
        generate="Anthropic console -> API Keys -> Create key",
        rotate_cmd=(
            "read -rsp \"New ANTHROPIC_API_KEY: \" NEW_ANTHROPIC_API_KEY; echo\n"
            f"fly secrets set ANTHROPIC_API_KEY=\"$NEW_ANTHROPIC_API_KEY\" "
            f"--app {APP_NAME}\n"
            "unset NEW_ANTHROPIC_API_KEY"
        ),
        verify_cmd=(
            f"curl {BACKEND_URL}/api/v1/health\n"
            "Monitor Sentry for 5 minutes; success means no new "
            "CognitionLLMConfigurationError events"
        ),
        rollback=(
            "fly secrets set ANTHROPIC_API_KEY="
            f"\"$PREVIOUS_ANTHROPIC_API_KEY\" --app {APP_NAME}"
        ),
        zero_downtime=True,
        notes=("Revoke the old key in Anthropic console after verification.",),
    ),
    "AUTH0_CLIENT_SECRET": SecretGuide(
        description="Auth0 client secret for the operious-dev application",
        impact="Auth0 machine-to-machine authentication and login-adjacent flows",
        generate=(
            "Auth0 dashboard -> Applications -> operious-dev -> "
            "Settings -> Rotate Secret"
        ),
        rotate_cmd=(
            "read -rsp \"New AUTH0_CLIENT_SECRET: \" NEW_AUTH0_CLIENT_SECRET; echo\n"
            f"fly secrets set AUTH0_CLIENT_SECRET=\"$NEW_AUTH0_CLIENT_SECRET\" "
            f"--app {APP_NAME}\n"
            "unset NEW_AUTH0_CLIENT_SECRET"
        ),
        verify_cmd=(
            f"curl {BACKEND_URL}/api/v1/health\n"
            f"Open {COMMAND_CENTER_URL} and confirm Auth0 login succeeds"
        ),
        rollback=(
            "fly secrets set AUTH0_CLIENT_SECRET="
            f"\"$PREVIOUS_AUTH0_CLIENT_SECRET\" --app {APP_NAME}"
        ),
        zero_downtime=True,
    ),
    "UPSTASH_REDIS_URL": SecretGuide(
        description="Upstash Redis URL when production uses the Upstash-named secret",
        impact=(
            "Celery broker behavior, queue depth checks, webhook nonce ledger, "
            "admission gate checks, and quota runtime coordination"
        ),
        generate=(
            "Upstash console -> Database -> Details -> Reset password; "
            "do not flush the database"
        ),
        rotate_cmd=(
            "read -rsp \"New UPSTASH_REDIS_URL: \" NEW_UPSTASH_REDIS_URL; echo\n"
            f"fly secrets set UPSTASH_REDIS_URL=\"$NEW_UPSTASH_REDIS_URL\" "
            f"--app {APP_NAME}\n"
            "unset NEW_UPSTASH_REDIS_URL"
        ),
        verify_cmd=(
            f"curl {BACKEND_URL}/api/v1/health | python3 -m json.tool | "
            "grep '\"status\"'"
        ),
        rollback=(
            "fly secrets set UPSTASH_REDIS_URL="
            f"\"$PREVIOUS_UPSTASH_REDIS_URL\" --app {APP_NAME}"
        ),
        zero_downtime=True,
        notes=("Only reset the password; do not flush Redis.",),
    ),
    "REDIS_URL": SecretGuide(
        description="Redis URL when production uses the generic Redis secret",
        impact=(
            "Celery broker behavior, queue depth checks, webhook nonce ledger, "
            "admission gate checks, and quota runtime coordination"
        ),
        generate=(
            "Upstash console -> Database -> Details -> Reset password; "
            "copy the Redis URL using the current production TLS mode"
        ),
        rotate_cmd=(
            "read -rsp \"New REDIS_URL: \" NEW_REDIS_URL; echo\n"
            f"fly secrets set REDIS_URL=\"$NEW_REDIS_URL\" --app {APP_NAME}\n"
            "unset NEW_REDIS_URL"
        ),
        verify_cmd=(
            f"curl {BACKEND_URL}/api/v1/health | python3 -m json.tool | "
            "grep '\"status\"'"
        ),
        rollback=(
            f"fly secrets set REDIS_URL=\"$PREVIOUS_REDIS_URL\" --app {APP_NAME}"
        ),
        zero_downtime=True,
        notes=(
            "If both REDIS_URL and UPSTASH_REDIS_URL are configured, rotate "
            "the secret currently used by production settings first.",
        ),
    ),
    "SENTRY_DSN": SecretGuide(
        description="Sentry DSN for backend and worker error reporting",
        impact="Error reporting, tracing, and alerting",
        generate="Sentry -> Project Settings -> Client Keys -> Add DSN",
        rotate_cmd=(
            "read -rsp \"New SENTRY_DSN: \" NEW_SENTRY_DSN; echo\n"
            f"fly secrets set SENTRY_DSN=\"$NEW_SENTRY_DSN\" --app {APP_NAME}\n"
            "unset NEW_SENTRY_DSN"
        ),
        verify_cmd=(
            f"curl {BACKEND_URL}/api/v1/health\n"
            "Trigger a controlled test error through the approved operator path "
            "and confirm it appears in Sentry"
        ),
        rollback=(
            f"fly secrets set SENTRY_DSN=\"$PREVIOUS_SENTRY_DSN\" --app {APP_NAME}"
        ),
        zero_downtime=True,
    ),
    "AUDIT_EXPORT_HMAC_SECRET": SecretGuide(
        description="HMAC-SHA256 key for signed tenant audit exports",
        impact=(
            "Audit export signatures and /api/v1/audit/verify results for "
            "exports signed with the active key"
        ),
        generate="openssl rand -hex 32",
        rotate_cmd=(
            "fly secrets set AUDIT_EXPORT_HMAC_SECRET=\"$(openssl rand -hex 32)\" "
            f"--app {APP_NAME}"
        ),
        verify_cmd=(
            f"curl {BACKEND_URL}/api/v1/audit/export "
            f"-H \"X-Tenant-ID: {TENANT_ID}\" | python3 -m json.tool | "
            "grep '\"algorithm\"'"
        ),
        rollback=(
            "fly secrets set AUDIT_EXPORT_HMAC_SECRET="
            f"\"$PREVIOUS_AUDIT_EXPORT_HMAC_SECRET\" --app {APP_NAME}"
        ),
        zero_downtime=True,
        notes=(
            "Previously exported audit files will not verify with the new key.",
            "Archive old exports before rotation and compare key_hint values.",
        ),
    ),
}


def main(argv: list[str]) -> int:
    if len(argv) <= 1:
        print_inventory()
        return 0
    name = argv[1].strip().upper()
    guide = SECRETS.get(name)
    if guide is None:
        print(f"Unknown secret: {argv[1]}")
        print()
        print_inventory()
        return 0
    print_guide(name, guide)
    return 0


def print_inventory() -> None:
    print("Operious AI production secrets")
    print("=" * 34)
    print(f"Fly app: {APP_NAME}")
    print(f"Backend: {BACKEND_URL}")
    print()
    print("Pre-rotation health check:")
    print_command(PRE_ROTATION_HEALTH)
    print()
    print("Secrets:")
    for name, guide in SECRETS.items():
        downtime = "YES" if guide.zero_downtime else "NO"
        print(f"- {name}: {guide.description} (zero-downtime: {downtime})")
    print()
    print("Run a focused guide with:")
    print("  python scripts/rotate_secret.py SECRET_NAME")


def print_guide(name: str, guide: SecretGuide) -> None:
    print(f"Secret: {name}")
    print("=" * (len(name) + 8))
    print(f"Description: {guide.description}")
    print(f"Impact: {guide.impact}")
    print(f"Zero-downtime: {'YES' if guide.zero_downtime else 'NO'}")
    print()
    print("1. Pre-rotation health check")
    print_command(PRE_ROTATION_HEALTH)
    print()
    print("2. Generate the new value")
    print(f"   {guide.generate}")
    print()
    print("3. Rotate in Fly")
    print_command(guide.rotate_cmd)
    print()
    print("4. Post-rotation verification")
    print_command(guide.verify_cmd)
    print()
    print("5. Rollback instruction")
    print_command(guide.rollback)
    if guide.notes:
        print()
        print("Notes:")
        for note in guide.notes:
            print(f"- {note}")
    print()
    print("This guide did not run any command or read any secret value.")


def print_command(command: str) -> None:
    print("```bash")
    print(command)
    print("```")


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
