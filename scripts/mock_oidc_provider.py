#!/usr/bin/env python3
"""A minimal OpenID Connect provider, for rehearsing single sign-on offline.

    python scripts/mock_oidc_provider.py --port 9100 \\
        --client-id consilium --client-secret-file /etc/consilium/secrets/oidc_client_secret \\
        --user sso.person@example.internal:Sso:Person

TEST TOOL ONLY — never run it in production. It signs in whoever the operator
names on the command line, with no password, so that the platform's side of the
flow (the redirect, the code exchange, the user-info call, the account match)
can be exercised on a network with no identity provider on it.

It implements the authorisation-code flow the platform's OpenID Connect client
(the framework's Social Login Key, "Custom" provider) uses, and checks it the
way a real provider would:

  GET  /authorize   response_type=code, client_id, redirect_uri, state, scope.
                    No login form: it issues a one-time code for the person
                    named with --user (or ?login_hint=<email> if that person is
                    one of those named) and redirects back with it and the state.
  POST /token       grant_type=authorization_code, code, redirect_uri, with the
                    client authenticated by HTTP Basic or in the form body. The
                    code must be unused, unexpired, and for the same client and
                    redirect_uri. Returns a bearer access token.
  GET  /userinfo    Bearer token. Returns sub, email, email_verified,
                    given_name, family_name, name.
  GET  /.well-known/openid-configuration   the discovery document.

Standard library only. Every request is logged to stderr with the outcome.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import secrets
import sys
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

CODE_TTL = 120
TOKEN_TTL = 600


class Provider:
    def __init__(self, issuer: str, client_id: str, client_secret: str, users: list[dict]):
        self.issuer = issuer
        self.client_id = client_id
        self.client_secret = client_secret
        self.users = {u["email"].lower(): u for u in users}
        self.default_user = users[0]["email"].lower()
        self.codes: dict = {}
        self.tokens: dict = {}

    @staticmethod
    def subject(email: str) -> str:
        # Stable and opaque, as a real provider's subject is: never the email.
        return "mock-" + hashlib.sha256(email.lower().encode()).hexdigest()[:24]


def make_handler(provider: Provider):
    class Handler(BaseHTTPRequestHandler):
        server_version = "MockOIDC/1.0"

        def log_message(self, fmt, *args):  # noqa: A003 -- stdlib signature
            sys.stderr.write("[mock-oidc] " + (fmt % args) + "\n")

        def _json(self, status: int, body: dict) -> None:
            data = json.dumps(body).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):  # noqa: N802 -- stdlib name
            url = urllib.parse.urlsplit(self.path)
            q = dict(urllib.parse.parse_qsl(url.query))
            if url.path == "/.well-known/openid-configuration":
                return self._json(200, {
                    "issuer": provider.issuer,
                    "authorization_endpoint": provider.issuer + "/authorize",
                    "token_endpoint": provider.issuer + "/token",
                    "userinfo_endpoint": provider.issuer + "/userinfo",
                    "response_types_supported": ["code"],
                    "grant_types_supported": ["authorization_code"],
                    "subject_types_supported": ["public"],
                    "token_endpoint_auth_methods_supported": ["client_secret_basic", "client_secret_post"],
                })
            if url.path == "/authorize":
                if q.get("response_type") != "code":
                    return self._json(400, {"error": "unsupported_response_type"})
                if q.get("client_id") != provider.client_id:
                    return self._json(400, {"error": "unauthorized_client"})
                if not q.get("redirect_uri"):
                    return self._json(400, {"error": "invalid_request", "error_description": "redirect_uri"})
                email = (q.get("login_hint") or provider.default_user).lower()
                if email not in provider.users:
                    return self._json(400, {"error": "access_denied", "error_description": "unknown person"})
                code = secrets.token_urlsafe(24)
                provider.codes[code] = {"email": email, "redirect_uri": q["redirect_uri"],
                                        "client_id": q["client_id"], "expires": time.time() + CODE_TTL}
                target = q["redirect_uri"] + ("&" if "?" in q["redirect_uri"] else "?") + urllib.parse.urlencode(
                    {"code": code, "state": q.get("state", "")})
                self.log_message("authorize: code issued for %s -> %s", email, q["redirect_uri"])
                self.send_response(302)
                self.send_header("Location", target)
                self.end_headers()
                return None
            if url.path == "/userinfo":
                auth = self.headers.get("Authorization", "")
                token = auth[7:] if auth.lower().startswith("bearer ") else q.get("access_token", "")
                grant = provider.tokens.get(token)
                if not grant or grant["expires"] < time.time():
                    return self._json(401, {"error": "invalid_token"})
                user = provider.users[grant["email"]]
                self.log_message("userinfo: %s", grant["email"])
                return self._json(200, {
                    "sub": Provider.subject(grant["email"]),
                    "email": grant["email"],
                    "email_verified": True,
                    "given_name": user.get("given_name", ""),
                    "family_name": user.get("family_name", ""),
                    "name": f"{user.get('given_name', '')} {user.get('family_name', '')}".strip(),
                })
            return self._json(404, {"error": "not_found"})

        def do_POST(self):  # noqa: N802 -- stdlib name
            url = urllib.parse.urlsplit(self.path)
            if url.path != "/token":
                return self._json(404, {"error": "not_found"})
            length = int(self.headers.get("Content-Length", "0"))
            form = dict(urllib.parse.parse_qsl(self.rfile.read(length).decode()))
            client_id, client_secret = form.get("client_id"), form.get("client_secret")
            auth = self.headers.get("Authorization", "")
            if auth.lower().startswith("basic "):
                client_id, _, client_secret = base64.b64decode(auth[6:]).decode().partition(":")
                client_id, client_secret = urllib.parse.unquote(client_id), urllib.parse.unquote(client_secret)
            if client_id != provider.client_id or client_secret != provider.client_secret:
                self.log_message("token: client authentication failed")
                return self._json(401, {"error": "invalid_client"})
            if form.get("grant_type") != "authorization_code":
                return self._json(400, {"error": "unsupported_grant_type"})
            grant = provider.codes.pop(form.get("code", ""), None)  # one use only
            if not grant or grant["expires"] < time.time():
                return self._json(400, {"error": "invalid_grant", "error_description": "unknown or used code"})
            if grant["redirect_uri"] != form.get("redirect_uri") or grant["client_id"] != client_id:
                return self._json(400, {"error": "invalid_grant", "error_description": "redirect_uri mismatch"})
            token = secrets.token_urlsafe(32)
            provider.tokens[token] = {"email": grant["email"], "expires": time.time() + TOKEN_TTL}
            self.log_message("token: access token issued for %s", grant["email"])
            return self._json(200, {"access_token": token, "token_type": "Bearer", "expires_in": TOKEN_TTL,
                                    "scope": "openid email profile"})

    return Handler


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=9100)
    parser.add_argument("--client-id", required=True)
    secret = parser.add_mutually_exclusive_group(required=True)
    secret.add_argument("--client-secret-file")
    secret.add_argument("--client-secret-env")
    parser.add_argument("--user", action="append", required=True,
                        help="email[:given name[:family name]]; the first is signed in by default")
    args = parser.parse_args()

    if args.client_secret_file:
        client_secret = Path(args.client_secret_file).read_text().strip()
    else:
        import os

        client_secret = os.environ[args.client_secret_env]
    users = []
    for spec in args.user:
        parts = spec.split(":")
        users.append({"email": parts[0], "given_name": parts[1] if len(parts) > 1 else "",
                      "family_name": parts[2] if len(parts) > 2 else ""})
    issuer = f"http://{args.host}:{args.port}"
    provider = Provider(issuer, args.client_id, client_secret, users)
    server = ThreadingHTTPServer((args.host, args.port), make_handler(provider))
    sys.stderr.write(f"[mock-oidc] TEST PROVIDER listening on {issuer} for client {args.client_id}; "
                     f"signs in {', '.join(u['email'] for u in users)} without a password\n")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
