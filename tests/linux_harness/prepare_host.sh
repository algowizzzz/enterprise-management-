#!/usr/bin/env bash
# Runs INSIDE the harness container, as root, before install.sh. It does what
# the server's administrators do before handing over: put the configuration
# file and the secrets in place, and issue a certificate. Here the certificate
# is self-signed by a throwaway CA; on the real server it comes from the
# organisation's certificate authority.
set -euo pipefail
install -d -m 0750 /etc/consilium /etc/consilium/secrets
install -m 0640 /media/harness/consilium.conf /etc/consilium/consilium.conf
umask 077
[[ -s /etc/consilium/secrets/db_root_password ]] || printf '%s\n' "$DB_ROOT_PASSWORD" > /etc/consilium/secrets/db_root_password
[[ -s /etc/consilium/secrets/db_password ]] || openssl rand -hex 16 > /etc/consilium/secrets/db_password

host=governance.example.internal
if [[ ! -s /etc/pki/tls/certs/$host.crt ]]; then
    d=$(mktemp -d)
    openssl req -x509 -newkey rsa:2048 -nodes -days 30 -subj "/CN=Rehearsal CA" \
        -keyout "$d/ca.key" -out /etc/pki/tls/certs/rehearsal-ca.crt 2>/dev/null
    openssl req -newkey rsa:2048 -nodes -subj "/CN=$host" -keyout /etc/pki/tls/private/$host.key \
        -out "$d/req.csr" 2>/dev/null
    printf 'subjectAltName=DNS:%s\nextendedKeyUsage=serverAuth\n' "$host" > "$d/ext"
    openssl x509 -req -in "$d/req.csr" -CA /etc/pki/tls/certs/rehearsal-ca.crt -CAkey "$d/ca.key" \
        -CAcreateserial -days 30 -extfile "$d/ext" -out /etc/pki/tls/certs/$host.crt 2>/dev/null
    chmod 600 /etc/pki/tls/private/$host.key
    # Trust the throwaway CA system-wide, as a corporate CA would be.
    cp /etc/pki/tls/certs/rehearsal-ca.crt /etc/pki/ca-trust/source/anchors/ 2>/dev/null \
        && update-ca-trust 2>/dev/null || true
    rm -rf "$d"
fi
grep -q "$host" /etc/hosts || echo "127.0.0.1 $host" >> /etc/hosts
echo "configuration, secrets and certificate in place"
