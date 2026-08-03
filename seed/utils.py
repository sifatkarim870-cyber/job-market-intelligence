"""Small shared utilities: logging setup and secure password hashing."""
from __future__ import annotations

import logging
import os
import secrets

from passlib.hash import bcrypt

LOG_FORMAT = "%(asctime)s | %(levelname)-8s | seed.%(name)s | %(message)s"


def get_logger(name: str) -> logging.Logger:
    logging.basicConfig(level=logging.INFO, format=LOG_FORMAT)
    return logging.getLogger(name)


def hash_password(raw_password: str) -> str:
    """bcrypt hash — never store or log the raw password."""
    return bcrypt.hash(raw_password)


def generate_bootstrap_password() -> str:
    """
    Generates a one-time, cryptographically random bootstrap password for
    the initial admin account when ADMIN_BOOTSTRAP_PASSWORD is not set via
    environment variable. Printed once to stdout at seed time, never stored
    in plaintext anywhere, never logged to a file-based log handler.
    """
    return secrets.token_urlsafe(18)


def normalize_name(raw: str) -> str:
    """Lower-case, strip, collapse internal whitespace — used for any
    `normalized_*` dedup column (skills, companies, etc.)."""
    return " ".join(raw.strip().lower().split())