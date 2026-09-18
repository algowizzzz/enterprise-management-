#!/usr/bin/env bash
#
# Consilium deployment kit: install. See deploy/kit.py for what it does, and
# docs/RUNBOOK.md for when to run it.
#
#   ./install.sh --config /etc/consilium/consilium.conf --bundle consilium-bundle.tar.gz
#
# The work is done by kit.py beside this script, which needs only a Python 3
# (3.8 or newer) from the operating system; it creates the installation's own
# Python environment itself.
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
for py in python3 /usr/libexec/platform-python python3.12 python3.11; do
    if command -v "$py" >/dev/null 2>&1 && "$py" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 8) else 1)' 2>/dev/null; then
        exec "$py" "$here/kit.py" install "$@"
    fi
done
echo "FAILED: no Python 3.8 or newer found. Install the distribution's python3 package." >&2
exit 1
