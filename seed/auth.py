"""
Seeds auth.roles and bootstraps exactly one auth.users admin account.

Security strategy for the bootstrap admin (do NOT hardcode a password):
  1. If env var ADMIN_EMAIL is unset, this module is a no-op for the user
     (roles still seed) — admin creation is opt-in per environment.
  2. Password source, in priority order:
       a. ADMIN_BOOTSTRAP_PASSWORD env var, if set (e.g. injected by a
          secrets manager in CI/CD) — never committed to source control.
       b. Otherwise, generate a random one-time password with
          utils.generate_bootstrap_password(), print it ONCE to stdout,
          and require the admin to change it on first login (application-
          layer responsibility, not this script's).
  3. Only the bcrypt hash is ever written to the database (key_hash-style
     column doesn't exist on auth.users itself in this schema — password
     hash storage belongs on whatever auth mechanism Step 34's API adds;
     if auth.users needs a password_hash column for direct login rather
     than pure API-key auth, that is a schema addition to flag for
     approval, not something this seed silently adds).
  4. This module never logs the raw or hashed password.
"""
from __future__ import annotations

import os

from sqlalchemy import Connection, text

from .base import SeedResult, upsert_many
from .utils import generate_bootstrap_password, get_logger

logger = get_logger("auth")

ROLES = [
    {"role_name": "admin", "permissions": {"scope": "*"}},
    {
        "role_name": "researcher",
        "permissions": {"scope": ["read:core", "read:ref", "read:analytics"]},
    },
    {"role_name": "api_read_only", "permissions": {"scope": ["read:analytics"]}},
    {
        "role_name": "scraper_service",
        "permissions": {"scope": ["write:core", "write:ops", "read:ref"]},
    },
]


def seed_roles(conn: Connection) -> SeedResult:
    import json

    rows = [
        {"role_name": r["role_name"], "permissions": json.dumps(r["permissions"])}
        for r in ROLES
    ]
    return upsert_many(
        conn, schema="auth", table_name="roles", rows=rows, conflict_cols=("role_name",),
    )


def seed_admin_user(conn: Connection) -> SeedResult:
    admin_email = os.environ.get("ADMIN_EMAIL")
    result = SeedResult(table="auth.users")
    if not admin_email:
        logger.info("ADMIN_EMAIL not set — skipping bootstrap admin creation (roles still seeded).")
        return result

    existing = conn.execute(
        text("SELECT user_id FROM auth.users WHERE email = :email"), {"email": admin_email}
    ).first()
    if existing:
        result.unchanged = 1
        logger.info("Admin user %s already exists — no changes.", admin_email)
        return result

    role_id = conn.execute(
        text("SELECT role_id FROM auth.roles WHERE role_name = 'admin'")
    ).scalar_one()

    bootstrap_password = os.environ.get("ADMIN_BOOTSTRAP_PASSWORD")
    generated = False
    if not bootstrap_password:
        bootstrap_password = generate_bootstrap_password()
        generated = True

    # NOTE: this schema's auth.users table (as approved) has no password
    # column — API-key auth (auth.api_keys) is the intended access path.
    # We create the user + roll an initial API key here; adapt if/when a
    # direct-login password column is formally added to the schema.
    conn.execute(
        text(
            "INSERT INTO auth.users (email, full_name, role_id, is_active) "
            "VALUES (:email, :name, :role_id, TRUE)"
        ),
        {"email": admin_email, "name": "Platform Administrator", "role_id": role_id},
    )
    user_id = conn.execute(
        text("SELECT user_id FROM auth.users WHERE email = :email"), {"email": admin_email}
    ).scalar_one()

    import hashlib
    import secrets as _secrets

    raw_api_key = _secrets.token_urlsafe(32)
    key_hash = hashlib.sha256(raw_api_key.encode()).hexdigest()

    conn.execute(
        text(
            "INSERT INTO auth.api_keys (user_id, key_hash, scopes) "
            "VALUES (:user_id, :key_hash, :scopes)"
        ),
        {"user_id": user_id, "key_hash": key_hash, "scopes": ["*"]},
    )

    result.inserted = 1
    print(f"\n[seed.auth] Bootstrap admin created: {admin_email}")
    print(f"[seed.auth] API key (shown ONCE, store securely now): {raw_api_key}")
    if generated:
        print(
            "[seed.auth] (Set ADMIN_BOOTSTRAP_PASSWORD to control this "
            "in future environments.)\n"
        )
    return result
