#!/usr/bin/env bash
#
# Set up a local development environment on macOS or Linux.
#
#   ./scripts/dev_setup.sh
#
# This is for development on a workstation. It is not the deployment path —
# that is deploy/install.sh, which installs from an offline bundle. This script
# does use the network, because a development machine has one.
#
# macOS works because it is Unix: every platform adaptation in this codebase is
# written to no-op on POSIX, so macOS takes the same path Linux does. It is not
# a supported deployment target and is not tested in CI; it is here because
# people develop on Macs.
#
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BENCH="${BENCH:-$REPO/.bench}"
SITE="${SITE:-consilium.localhost}"
DB_PORT="${DB_PORT:-5432}"
REDIS_PORT="${REDIS_PORT:-6379}"
DB_NAME="${DB_NAME:-consilium_dev}"
FRAPPE_VERSION="v15.121.0"

say()  { printf '\n\033[1m==> %s\033[0m\n' "$*"; }
warn() { printf '\033[33m    %s\033[0m\n' "$*"; }
fail() { printf '\033[31mFAILED: %s\033[0m\n' "$*" >&2; exit 1; }

OS="$(uname -s)"
say "Setting up a development environment on $OS"

# --------------------------------------------------------------- prerequisites
case "$OS" in
    Darwin)
        command -v brew >/dev/null || fail "Homebrew is required. See https://brew.sh"
        for formula in postgresql@16 redis; do
            if brew list --versions "$formula" >/dev/null 2>&1; then
                echo "  $formula already installed"
            else
                say "Installing $formula"
                brew install "$formula"
            fi
        done
        brew services start postgresql@16 >/dev/null 2>&1 || true
        brew services start redis >/dev/null 2>&1 || true
        # Homebrew keeps versioned formulae off the default PATH.
        export PATH="$(brew --prefix)/opt/postgresql@16/bin:$PATH"
        # Homebrew's initdb makes the login user the superuser and creates no
        # "postgres" role, so the Linux default would fail to authenticate.
        DB_ROOT_USER="${PGUSER:-$(id -un)}"
        ;;
    Linux)
        command -v psql >/dev/null || warn "psql not found. Install postgresql-16 and redis, then re-run."
        command -v redis-cli >/dev/null || warn "redis-cli not found. Install redis, then re-run."
        ;;
    *)
        fail "unsupported system: $OS. Use Linux, macOS, or deploy/install.ps1 on Windows."
        ;;
esac

# winbench pins Python 3.11-3.12 to match the deployment targets, and a current
# Homebrew or distribution python3 is often newer than that. Look for a
# versioned interpreter rather than trusting whatever python3 happens to be.
in_range() { "$1" -c 'import sys; raise SystemExit(0 if (3,11) <= sys.version_info[:2] <= (3,12) else 1)' 2>/dev/null; }
PYTHON=""
for candidate in "${PYTHON_BIN:-}" python3.11 python3.12 python3; do
    [[ -n "$candidate" ]] && command -v "$candidate" >/dev/null && in_range "$candidate" \
        && { PYTHON="$(command -v "$candidate")"; break; }
done
if [[ -z "$PYTHON" && "$OS" == "Darwin" ]]; then
    say "Installing python@3.11"
    brew install python@3.11
    PYTHON="$(brew --prefix)/opt/python@3.11/bin/python3.11"
fi
[[ -n "$PYTHON" ]] || fail "Python 3.11 or 3.12 is required (set PYTHON_BIN to point at one)"
echo "  using $PYTHON ($("$PYTHON" -V 2>&1))"

say "Checking services"
DB_ROOT_USER="${DB_ROOT_USER:-${PGUSER:-postgres}}"
pg_isready -h 127.0.0.1 -p "$DB_PORT" -q || fail "PostgreSQL is not accepting connections on port $DB_PORT"
# A machine with an older PostgreSQL already on the port answers pg_isready just
# as well, and `brew services start` fails quietly when the port is taken. Check
# the version that actually answered rather than the one we meant to start.
PG_MAJOR="$(PGPASSWORD="${PGPASSWORD:-postgres}" psql -h 127.0.0.1 -p "$DB_PORT" -U "$DB_ROOT_USER" \
    -d postgres -Atc 'show server_version_num' 2>/dev/null | cut -c1-2)" \
    || fail "cannot sign in to PostgreSQL on port $DB_PORT as $DB_ROOT_USER (set PGUSER/PGPASSWORD)"
[[ "$PG_MAJOR" == "16" ]] || fail "PostgreSQL on port $DB_PORT is version $PG_MAJOR, not 16. \
Run PostgreSQL 16 on a free port and re-run with DB_PORT=<port>."
echo "  PostgreSQL 16 responding on $DB_PORT"
# The framework's root connection opens a database named after the root user
# (cur_db_name=root_login). Linux's "postgres" user has one; Homebrew's login
# user does not, so create an empty one rather than patching the framework.
if ! PGPASSWORD="${PGPASSWORD:-postgres}" psql -h 127.0.0.1 -p "$DB_PORT" -U "$DB_ROOT_USER" -d postgres \
        -Atc "select 1 from pg_database where datname = '$DB_ROOT_USER'" | grep -q 1; then
    PGPASSWORD="${PGPASSWORD:-postgres}" createdb -h 127.0.0.1 -p "$DB_PORT" -U "$DB_ROOT_USER" "$DB_ROOT_USER" \
        || fail "could not create database $DB_ROOT_USER for the root connection"
    echo "  created database $DB_ROOT_USER for the root connection"
fi
redis-cli -p "$REDIS_PORT" ping >/dev/null || fail "Redis is not responding on port $REDIS_PORT"
echo "  Redis responding on $REDIS_PORT"

# ----------------------------------------------------------------- environment
say "Creating the Python environment"
if [[ -x "$REPO/.venv/bin/python" ]] && ! in_range "$REPO/.venv/bin/python"; then
    warn "existing .venv was built with an unsupported Python; rebuilding it"
    rm -rf "$REPO/.venv"
fi
"$PYTHON" -m venv "$REPO/.venv"
PY="$REPO/.venv/bin/python"
"$PY" -m pip install --quiet --upgrade pip wheel

say "Installing the framework"
if [[ ! -d "$BENCH/frappe-src" ]]; then
    mkdir -p "$BENCH"
    git clone --depth 1 --branch "$FRAPPE_VERSION" https://github.com/frappe/frappe.git "$BENCH/frappe-src"
fi
"$PY" -m pip install --quiet -e "$BENCH/frappe-src"
"$PY" -m pip install --quiet -e "$REPO/apps/consilium" -e "$REPO/winbench"
"$PY" -m pip install --quiet pytest playwright

# ---------------------------------------------------------------------- layout
say "Laying out the bench"
mkdir -p "$BENCH/sites" "$BENCH/apps" "$BENCH/logs"
ln -sfn "$BENCH/frappe-src" "$BENCH/apps/frappe"
ln -sfn "$REPO/apps/consilium" "$BENCH/apps/consilium"

cat > "$BENCH/sites/common_site_config.json" <<JSON
{
  "db_type": "postgres",
  "db_host": "127.0.0.1",
  "db_port": $DB_PORT,
  "redis_cache": "redis://127.0.0.1:$REDIS_PORT",
  "redis_queue": "redis://127.0.0.1:$REDIS_PORT",
  "redis_socketio": "redis://127.0.0.1:$REDIS_PORT",
  "socketio_port": 9000,
  "webserver_port": 8000,
  "developer_mode": 1
}
JSON
printf 'frappe\nconsilium\n' > "$BENCH/sites/apps.txt"

# ------------------------------------------------------------------- the site
export FRAPPE_BENCH_ROOT="$BENCH"
# A failed new-site can leave the site directory behind with no database, and
# the next run would then try to migrate something that was never created.
if [[ -d "$BENCH/sites/$SITE" ]] && ! PGPASSWORD="${PGPASSWORD:-postgres}" psql -h 127.0.0.1 -p "$DB_PORT" \
        -U "$DB_ROOT_USER" -d postgres -Atc "select 1 from pg_database where datname = '$DB_NAME'" | grep -q 1; then
    warn "site $SITE exists but database $DB_NAME does not; removing the partial site"
    rm -rf "$BENCH/sites/$SITE"
fi
if [[ -d "$BENCH/sites/$SITE" ]]; then
    say "Site $SITE already exists; migrating it"
    ( cd "$BENCH/sites" && "$PY" -m frappe.utils.bench_helper frappe --site "$SITE" migrate 2>&1 \
        | grep -v 'Updating DocTypes' ) || fail "migration failed"
else
    say "Creating the site"
    ( cd "$BENCH/sites" && "$PY" -m frappe.utils.bench_helper frappe new-site "$SITE" \
        --db-type postgres --db-host 127.0.0.1 --db-port "$DB_PORT" --db-name "$DB_NAME" \
        --db-root-username "$DB_ROOT_USER" --db-root-password "${PGPASSWORD:-postgres}" \
        --admin-password admin 2>&1 | grep -v 'Updating DocTypes' ) || fail "site creation failed"
    ( cd "$BENCH/sites" && "$PY" -m frappe.utils.bench_helper frappe --site "$SITE" \
        install-app consilium 2>&1 | grep -v 'Updating DocTypes' ) || fail "app install failed"
fi

say "Installing front-end assets"
( cd "$BENCH" && "$REPO/.venv/bin/winbench" assets --import "$REPO/assets/"frappe-assets-*.tar.gz ) \
    || warn "asset import failed; the interface will not render correctly"

say "Loading reference data"
( cd "$BENCH/sites" && "$PY" "$REPO/deploy/seed.py" --site "$SITE" ) || warn "reference data did not load"

say "Checking the result"
( cd "$BENCH/sites" && "$PY" "$REPO/deploy/healthcheck.py" --site "$SITE" ) \
    || fail "the environment is not healthy — see above"

say "Ready"
cat <<DONE

  Start it with:

    cd $BENCH && $REPO/.venv/bin/winbench serve --site $SITE --port 8000

  Then open http://localhost:8000 and sign in as Administrator / admin.

  Run the tests with:

    cd $BENCH/sites && FRAPPE_BENCH_ROOT=$BENCH $PY \\
        -m frappe.utils.bench_helper frappe --site $SITE run-tests --app consilium

DONE
