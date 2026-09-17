#!/usr/bin/env bash
#
# Install Consilium on a Linux server with no internet access.
#
# Everything this needs is inside the bundle. If any step here reaches the
# network, that is a defect — report it rather than opening a firewall hole,
# because the same step will fail on a stricter host.
#
#   tar xzf consilium-bundle.tar.gz
#   cd consilium-bundle
#   ./install/install.sh --target /opt/consilium --site consilium.local
#
# Prerequisites on the host, which this script checks and does not install:
#   - Python 3.10 or newer, with venv
#   - PostgreSQL 13 or newer, reachable, and either a superuser login or a
#     database and owner role provisioned in advance (see --no-setup-db)
#   - Redis, reachable
#
set -euo pipefail

BUNDLE_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

TARGET=/opt/consilium
SITE=consilium.local
DB_HOST=127.0.0.1
DB_PORT=5432
DB_NAME=consilium
DB_ROOT_USER=postgres
DB_ROOT_PASSWORD=""
DB_PASSWORD=""
ADMIN_PASSWORD=""
REDIS_URL="redis://127.0.0.1:6379"
SETUP_DB=1
SKIP_VERIFY=0

usage() {
    sed -n '2,20p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
    cat <<'USAGE'

Options:
  --target DIR            where to install               (default /opt/consilium)
  --site NAME             site name                      (default consilium.local)
  --db-host HOST          PostgreSQL host                (default 127.0.0.1)
  --db-port PORT          PostgreSQL port                (default 5432)
  --db-name NAME          database name                  (default consilium)
  --db-root-user USER     superuser login                (default postgres)
  --db-root-password PW   superuser password
  --db-password PW        password for the application's database role
  --admin-password PW     password for the initial administrator
  --redis-url URL         Redis URL                      (default redis://127.0.0.1:6379)
  --no-setup-db           do not create the database or role. Use this when a
                          database team has provisioned them for you and you do
                          not hold a superuser login, which is the usual case on
                          a managed instance.
  --skip-verify           skip bundle checksum verification (not recommended)
USAGE
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --target) TARGET="$2"; shift 2;;
        --site) SITE="$2"; shift 2;;
        --db-host) DB_HOST="$2"; shift 2;;
        --db-port) DB_PORT="$2"; shift 2;;
        --db-name) DB_NAME="$2"; shift 2;;
        --db-root-user) DB_ROOT_USER="$2"; shift 2;;
        --db-root-password) DB_ROOT_PASSWORD="$2"; shift 2;;
        --db-password) DB_PASSWORD="$2"; shift 2;;
        --admin-password) ADMIN_PASSWORD="$2"; shift 2;;
        --redis-url) REDIS_URL="$2"; shift 2;;
        --no-setup-db) SETUP_DB=0; shift;;
        --skip-verify) SKIP_VERIFY=1; shift;;
        -h|--help) usage; exit 0;;
        *) echo "unknown option: $1" >&2; usage; exit 2;;
    esac
done

say()  { printf '\n\033[1m==> %s\033[0m\n' "$*"; }
fail() { printf '\033[31mFAILED: %s\033[0m\n' "$*" >&2; exit 1; }

# ---------------------------------------------------------------- prerequisites
say "Checking prerequisites"

command -v python3 >/dev/null || fail "python3 is not on PATH"
PYV=$(python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])')
python3 -c 'import sys; raise SystemExit(0 if sys.version_info >= (3,10) else 1)' \
    || fail "Python 3.10 or newer is required; found $PYV"
python3 -c 'import venv' 2>/dev/null \
    || fail "the python3 venv module is missing (install python3-venv)"
echo "  Python $PYV"

command -v psql >/dev/null \
    || echo "  note: psql is not on PATH; the database check below will be skipped"

if command -v psql >/dev/null; then
    if PGPASSWORD="$DB_ROOT_PASSWORD" psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_ROOT_USER" \
            -tc 'select 1' >/dev/null 2>&1; then
        echo "  PostgreSQL reachable at $DB_HOST:$DB_PORT"
    else
        fail "cannot reach PostgreSQL at $DB_HOST:$DB_PORT as $DB_ROOT_USER.
  If the database is managed and you have no superuser login, provision the
  database and its owner role first and re-run with --no-setup-db."
    fi
fi

REDIS_HOST=$(echo "$REDIS_URL" | sed -E 's#redis://([^:/]+).*#\1#')
REDIS_PORT=$(echo "$REDIS_URL" | sed -E 's#redis://[^:]+:([0-9]+).*#\1#')
if command -v redis-cli >/dev/null; then
    redis-cli -h "$REDIS_HOST" -p "${REDIS_PORT:-6379}" ping >/dev/null 2>&1 \
        || fail "cannot reach Redis at $REDIS_URL"
    echo "  Redis reachable at $REDIS_URL"
fi

# ------------------------------------------------------------------ the bundle
if [[ "$SKIP_VERIFY" -eq 0 ]]; then
    say "Verifying the bundle"
    command -v sha256sum >/dev/null || fail "sha256sum is not available; re-run with --skip-verify if you have verified another way"
    ( cd "$BUNDLE_ROOT" && sha256sum -c SHA256SUMS --quiet ) \
        || fail "the bundle does not match its checksums — it is incomplete or was altered in transit"
    echo "  every file matches its recorded checksum"
fi

WHEELHOUSE="$BUNDLE_ROOT/wheelhouse"
[[ -d "$WHEELHOUSE" ]] || fail "no wheelhouse in the bundle at $WHEELHOUSE"
echo "  $(find "$WHEELHOUSE" -name '*.whl' | wc -l) wheels available"

# ----------------------------------------------------------------- environment
say "Creating the Python environment at $TARGET"
mkdir -p "$TARGET"
python3 -m venv "$TARGET/env"
PY="$TARGET/env/bin/python"

# --no-index is the point of this whole exercise: pip must not reach out.
"$PY" -m pip install --quiet --no-index --find-links "$WHEELHOUSE" --upgrade pip setuptools wheel \
    || fail "could not install packaging tools from the bundle"
"$PY" -m pip install --quiet --no-index --find-links "$WHEELHOUSE" frappe consilium \
    || fail "could not install the application from the bundle"
echo "  installed $("$PY" -m pip list --format=freeze 2>/dev/null | wc -l) packages, none from the network"

# ---------------------------------------------------------------- bench layout
say "Laying out the site directory"
mkdir -p "$TARGET/sites" "$TARGET/logs"
FRAPPE_PATH=$("$PY" -c 'import frappe, os; print(os.path.dirname(os.path.dirname(frappe.__file__)))')
mkdir -p "$TARGET/apps"
ln -sfn "$FRAPPE_PATH/frappe" "$TARGET/apps/frappe" 2>/dev/null || true

cat > "$TARGET/sites/common_site_config.json" <<JSON
{
  "db_type": "postgres",
  "db_host": "$DB_HOST",
  "db_port": $DB_PORT,
  "redis_cache": "$REDIS_URL",
  "redis_queue": "$REDIS_URL",
  "redis_socketio": "$REDIS_URL",
  "socketio_port": 9000,
  "webserver_port": 8000,
  "developer_mode": 0
}
JSON
printf 'frappe\nconsilium\n' > "$TARGET/sites/apps.txt"
echo "  $TARGET/sites"

# ------------------------------------------------------------------- the site
say "Creating the site"
FRAPPE_CLI=( "$PY" -m frappe.utils.bench_helper frappe )
export FRAPPE_BENCH_ROOT="$TARGET"

NEW_SITE_ARGS=( new-site "$SITE" --db-type postgres --db-host "$DB_HOST"
                --db-port "$DB_PORT" --db-name "$DB_NAME" )
[[ -n "$DB_PASSWORD"    ]] && NEW_SITE_ARGS+=( --db-password "$DB_PASSWORD" )
[[ -n "$ADMIN_PASSWORD" ]] && NEW_SITE_ARGS+=( --admin-password "$ADMIN_PASSWORD" )
if [[ "$SETUP_DB" -eq 1 ]]; then
    NEW_SITE_ARGS+=( --db-root-username "$DB_ROOT_USER" --db-root-password "$DB_ROOT_PASSWORD" )
else
    # The database and its owner role already exist and we hold no superuser
    # login, so the framework must not try to create them.
    NEW_SITE_ARGS+=( --no-setup-db )
fi

( cd "$TARGET/sites" && "${FRAPPE_CLI[@]}" "${NEW_SITE_ARGS[@]}" 2>&1 | grep -v 'Updating DocTypes' ) \
    || fail "site creation failed"

say "Installing the application"
( cd "$TARGET/sites" && "${FRAPPE_CLI[@]}" --site "$SITE" install-app consilium 2>&1 | grep -v 'Updating DocTypes' ) \
    || fail "could not install the application into the site"

# ---------------------------------------------------------------------- assets
say "Installing front-end assets"
ASSET_BUNDLE=$(find "$BUNDLE_ROOT/assets" -name 'frappe-assets-*.tar.gz' 2>/dev/null | head -1)
if [[ -n "$ASSET_BUNDLE" ]]; then
    mkdir -p "$TARGET/sites/assets"
    tar xzf "$ASSET_BUNDLE" -C "$TARGET/sites/assets" --strip-components=1
    echo "  unpacked $(basename "$ASSET_BUNDLE")"
else
    echo "  no prebuilt asset bundle found; the interface will not render correctly"
fi

# ------------------------------------------------------------------- reference
say "Loading reference data"
( cd "$TARGET/sites" && "$PY" "$BUNDLE_ROOT/install/seed.py" --site "$SITE" ) \
    || echo "  reference data did not load; the system is installed but empty"

# ----------------------------------------------------------------------- check
say "Checking the installation"
( cd "$TARGET/sites" && "$PY" "$BUNDLE_ROOT/install/healthcheck.py" --site "$SITE" ) \
    || fail "the installation is not healthy — see the failures above"

say "Done"
cat <<DONE

  Installed at : $TARGET
  Site         : $SITE

  Start it with:

    cd $TARGET/sites
    FRAPPE_BENCH_ROOT=$TARGET $PY -m frappe.utils.bench_helper frappe \\
        --site $SITE serve --port 8000

  Then open http://localhost:8000 and sign in as Administrator.

  For a long-running service, see docs/DEPLOYMENT.md.
DONE
