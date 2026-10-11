#!/usr/bin/env bash
# Provision a PostgreSQL database on an Oracle Cloud Always Free VM.
#
# Why Oracle and not a managed free tier
# --------------------------------------
# Measured on 2026-10-11, this corpus is 1,325 MB (113,469 rows), of which
# core.job_descriptions alone is 1,058 MB at 4,721 bytes per row. CI adds about
# 6,400 rows a day across four scheduled runs, so the database grows ~28.8 MB
# per day.
#
# Every managed free Postgres tier stops between 500 MB and 1 GB:
#
#   Supabase Free   500 MB, 2 projects -- goes READ-ONLY at the cap, then
#                   pauses after a week of inactivity. This is the same wall
#                   Neon hit; it would fail again in about 8 days.
#   Aiven Free      1 GB, one service -- powered off when unused.
#   Neon Free       500 MB -- already exhausted.
#   Render Free     1 GB -- expires after 30 days.
#   Koyeb Free      1 GB -- sleeps after 5 minutes idle.
#
# Oracle Always Free gives a real VM with 200 GB of block volume: 150x the
# corpus, and no inactivity pause, because there is no managed-scheduler to
# pause it. It is self-hosted, so the operator cost -- a restart after an OS
# update, a pg_dump into Hugging Face -- is real, and this script plus
# scripts/restore_state_snapshot.py is that cost.
#
# Known risks, stated rather than discovered later:
#   * Oracle halved the Always Free allowance in June 2026 (4 -> 2 OCPU,
#     24 -> 12 GB). 12 GB is ample here; the 200 GB of block volume did NOT
#     change, and storage is the binding constraint for this workload.
#   * Idle reclamation: an instance under 20% CPU, network and memory for
#     7 days is reclaimed. The daily scrapes keep it well above that.
#   * "Out of host capacity" is common in popular regions at signup. Pick a
#     quieter region; the home region cannot be changed later.
#   * A credit card is required to sign up. Nothing is charged while usage
#     stays inside the Always Free allowance.
#
# What this script does, in order:
#   1. install PostgreSQL 18
#   2. create the database, role and schema
#   3. open the port to the world (CI runs from GitHub runners; there is no
#      static egress IP to allowlist)
#   4. print the DSN to paste into the CI_DATABASE_URL secret
#
# It does NOT move data. That is scripts/restore_state_snapshot.py --source hf,
# which is the same code path CI already uses to seed its container, so the
# target database is built from exactly the snapshot that is proven to work.
#
# Usage (run on the Oracle VM, as a user with sudo):
#   bash scripts/provision_ci_database.sh
#   bash scripts/provision_ci_database.sh --password 'a-strong-password'

set -euo pipefail

DB_NAME="${DB_NAME:-jmi_ci}"
DB_USER="${DB_USER:-jmi}"
DB_PASSWORD="${DB_PASSWORD:-}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --password) DB_PASSWORD="$2"; shift 2 ;;
    --name)     DB_NAME="$2";     shift 2 ;;
    --user)     DB_USER="$2";     shift 2 ;;
    -h|--help)  sed -n '2,50p' "$0"; exit 0 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done

if [[ -z "$DB_PASSWORD" ]]; then
  DB_PASSWORD="$(head -c 24 /dev/urandom | base64 | tr -d '/+=' | head -c 28)"
  echo "generated password: $DB_PASSWORD"
  echo "(store it now; it is not written to disk by this script)"
fi

echo "==> installing PostgreSQL 18"
# The PGDG apt repository, because the distro default on Oracle Linux / Ubuntu
# is older than 18 and pg_dump refuses to cross a major version.
if [[ ! -f /usr/share/postgresql-common/pgdg/apt.postgresql.org.asc ]]; then
  sudo install -d /usr/share/postgresql-common/pgdg
  sudo curl -fsSL -o /usr/share/postgresql-common/pgdg/apt.postgresql.org.asc \
    https://www.postgresql.org/media/keys/ACCC4CF8.asc
  . /etc/os-release
  echo "deb [signed-by=/usr/share/postgresql-common/pgdg/apt.postgresql.org.asc] https://apt.postgresql.org/pub/repos/apt ${VERSION_CODENAME}-pgdg main" \
    | sudo tee /etc/apt/sources.list.d/pgdg.list > /dev/null
  sudo apt-get update -qq
fi
sudo apt-get install -y -qq "postgresql-18" "postgresql-client-18"

echo "==> starting the cluster"
sudo systemctl enable --now postgresql

echo "==> creating role and database"
sudo -u postgres psql -v ON_ERROR_STOP=1 <<SQL
DO \$\$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '${DB_USER}') THEN
    CREATE ROLE ${DB_USER} LOGIN PASSWORD '${DB_PASSWORD}';
  ELSE
    ALTER ROLE ${DB_USER} LOGIN PASSWORD '${DB_PASSWORD}';
  END IF;
END
\$\$;
SQL

sudo -u postgres psql -v ON_ERROR_STOP=1 -c "SELECT 1 FROM pg_database WHERE datname='${DB_NAME}'" \
  | grep -q 1 \
  || sudo -u postgres createdb -O "${DB_USER}" "${DB_NAME}"

echo "==> granting CREATE so the ledger table and schema load can run"
sudo -u postgres psql -v ON_ERROR_STOP=1 -d "${DB_NAME}" <<SQL
GRANT ALL ON SCHEMA public TO ${DB_USER};
ALTER SCHEMA public OWNER TO ${DB_USER};
SQL

echo "==> opening the port (CI runners have no fixed egress IP)"
sudo -u postgres psql -v ON_ERROR_STOP=1 <<SQL
ALTER SYSTEM SET listen_addresses = '*';
ALTER SYSTEM SET password_encryption = 'scram-sha-256';
SQL
sudo systemctl restart postgresql

PGVER=$(sudo -u postgres psql -tAc "SHOW server_version_num" | cut -d. -f1)
RULE="host all ${DB_USER} 0.0.0.0/0 scram-sha-256"
sudo tee "/etc/postgresql/${PGVER}/main/pg_hba.conf" > /dev/null <<< "$RULE"
sudo systemctl reload postgresql

# The corpus partition is declared for months through 2029; without these the
# schema load fails on the first row it tries to insert.
sudo -u postgres psql -v ON_ERROR_STOP=1 -d "${DB_NAME}" <<SQL
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE EXTENSION IF NOT EXISTS btree_gin;
SQL

IP=$(curl -s --max-time 10 https://api.ipify.org || hostname -I | awk '{print $1}')
echo
echo "================================================================"
echo " PostgreSQL is up."
echo
echo "   host     : ${IP}"
echo "   port     : 5432"
echo "   database : ${DB_NAME}"
echo "   user     : ${DB_USER}"
echo "   password : ${DB_PASSWORD}"
echo
echo " Paste this into the repository secret CI_DATABASE_URL:"
echo
echo "   postgresql+psycopg://${DB_USER}:${DB_PASSWORD}@${IP}:5432/${DB_NAME}"
echo
echo " Then load the schema and reference data from Hugging Face:"
echo
echo "   DATABASE_URL='<that DSN>' uv run python scripts/restore_state_snapshot.py --source hf --dsn '<that DSN>'"
echo "================================================================"