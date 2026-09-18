#!/usr/bin/env python3
"""The Consilium deployment kit: one configuration file, one command per operation.

platform-rules: exempt — this file names CDN hosts in order to detect them.

    install.sh  --config <file> --bundle <bundle.tar.gz>   fresh install (idempotent)
    upgrade.sh  --config <file> --bundle <bundle.tar.gz>   back up, install, migrate, verify
    backup.sh   --config <file>                            database, files, site configuration
    restore.sh  --config <file> --from <backup dir>        into the site, or a new one
    verify.sh   --config <file>                            acceptance; writes a readiness report

Each shell script is a thin wrapper that finds a Python 3 and runs this file,
which needs nothing but the standard library: it runs before the installation's
own environment exists. Everything that needs the framework runs in that
environment, in a child process, through the scripts that travel next to this
one (healthcheck.py, seed.py, configure_site.py, acceptance.py, ...).

Nothing here reaches the network. pip runs with ``--no-index`` against the
bundle's wheelhouse, with every proxy variable pointed at a dead address, and
its log is kept and searched afterwards for any sign of a download; the result
is recorded in ``logs/install-evidence.json`` and checked by ``verify``.

The host needs Python 3.10 or newer of the version the bundle was built for
(the bundle's MANIFEST.json says which), the PostgreSQL client tools, a
reachable PostgreSQL and Redis, and — to run the services — systemd and a
reverse proxy (nginx or Caddy). Nothing else: no compiler, no package
manager for the front end, no container runtime.
"""

from __future__ import annotations

import argparse
import configparser
import datetime as _dt
import getpass
import hashlib
import json
import os
import platform
import re
import secrets
import shutil
import socket
import ssl
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

KIT_DIR = Path(__file__).resolve().parent
TRUE = {"yes", "true", "on", "1"}
FALSE = {"no", "false", "off", "0", ""}
# Every proxy variable is pointed here during install and upgrade: nothing
# listens on port 9 (discard), so a request that should never have been made
# fails at once instead of quietly succeeding through a corporate proxy.
DEAD_PROXY = "http://127.0.0.1:9"


class KitError(Exception):
    """A failure the operator can act on. The message says what to do."""


# =========================================================================
# Configuration
# =========================================================================

# section -> key -> (kind, required, default). Kinds: str, host, int, port,
# bool, path, email, url, tz, choice:a|b|c, secret (the *_file / *_env pair).
SCHEMA: dict = {
    "site": {
        "name": ("sitename", True, None),
        "hostname": ("host", True, None),
        "admin_email": ("email", True, None),
        "timezone": ("tz", True, None),
        "admin_password": ("secret", False, None),
    },
    "paths": {
        "install_dir": ("path", True, None),
    },
    "service": {
        "user": ("name", True, "consilium"),
        "group": ("name", True, "consilium"),
        "manage_services": ("choice:auto|yes|no", False, "auto"),
    },
    "database": {
        "host": ("host", True, None),
        "port": ("port", True, "5432"),
        "name": ("dbname", True, None),
        "password": ("secret", True, None),
        "provisioning": ("choice:superuser|provisioned", True, "superuser"),
        "root_user": ("name", False, "postgres"),
        "root_password": ("secret", False, None),
        "client_bin_dir": ("path?", False, ""),
    },
    "redis": {
        "cache_url": ("url:redis|rediss", True, None),
        "queue_url": ("url:redis|rediss", True, None),
    },
    "web": {
        "port": ("port", True, "8000"),
        "threads": ("int:1:64", False, "8"),
        "background_workers": ("int:1:32", False, "2"),
        "socketio": ("bool", False, "no"),
    },
    "tls": {
        "proxy": ("choice:nginx|caddy|none", True, "nginx"),
        "cert_file": ("path?", False, ""),
        "key_file": ("path?", False, ""),
        "https_port": ("port", False, "443"),
        "http_port": ("port", False, "80"),
    },
    "email": {
        "enabled": ("bool", False, "no"),
        "smtp_host": ("host?", False, ""),
        "smtp_port": ("port", False, "587"),
        "security": ("choice:starttls|ssl|none", False, "starttls"),
        "login": ("str", False, ""),
        "password": ("secret", False, None),
        "sender": ("email?", False, ""),
        "sender_name": ("str", False, "Governance Portal"),
        # Notification email through Microsoft Graph instead of SMTP, for an
        # organisation that allows no SMTP. Independent of `enabled`, which is
        # the SMTP account (still used by the framework's own mail).
        "graph_enabled": ("bool", False, "no"),
        "graph_tenant_id": ("graphid?", False, ""),
        "graph_client_id": ("graphid?", False, ""),
        "graph_client_secret": ("secret", False, None),
        "graph_sender": ("graphid?", False, ""),
        "graph_authority_url": ("url?:https", False, ""),
        "graph_api_url": ("url?:https", False, ""),
    },
    "sso": {
        "mode": ("choice:none|oidc|ldap", False, "none"),
        "allow_signup": ("bool", False, "no"),
        "oidc_provider_name": ("str", False, "Corporate SSO"),
        "oidc_base_url": ("url?:http|https", False, ""),
        "oidc_authorize_url": ("url?:http|https", False, ""),
        "oidc_token_url": ("url?:http|https", False, ""),
        "oidc_userinfo_url": ("url?:http|https", False, ""),
        "oidc_client_id": ("str", False, ""),
        "oidc_client_secret": ("secret", False, None),
        "oidc_scope": ("str", False, "openid email profile"),
        "oidc_user_id_claim": ("str", False, "sub"),
        "ldap_server_url": ("url?:ldap|ldaps", False, ""),
        "ldap_directory": ("choice:Active Directory|OpenLDAP", False, "Active Directory"),
        "ldap_bind_dn": ("str", False, ""),
        "ldap_bind_password": ("secret", False, None),
        "ldap_user_search_path": ("str", False, ""),
        "ldap_group_search_path": ("str", False, ""),
        "ldap_search_filter": ("str", False, ""),
        "ldap_email_attribute": ("str", False, "mail"),
        "ldap_username_attribute": ("str", False, ""),
        "ldap_first_name_attribute": ("str", False, "givenName"),
        "ldap_last_name_attribute": ("str", False, "sn"),
        "ldap_ca_file": ("path?", False, ""),
    },
    "assistant": {
        "ai_enabled": ("bool", False, "no"),
        "ai_provider": ("choice:anthropic|openai-compatible", False, "openai-compatible"),
        "ai_endpoint_url": ("url?:http|https", False, ""),
        "ai_model": ("str", False, ""),
    },
    "backup": {
        "dir": ("path", True, None),
        "retention_days": ("int:1:3650", False, "14"),
        "schedule": ("str", False, "*-*-* 02:30:00"),
    },
}

_RE_HOST = re.compile(r"^(?=.{1,253}$)([A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?)(\.[A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?)*$")
_RE_IP = re.compile(r"^\d{1,3}(\.\d{1,3}){3}$|^[0-9a-fA-F:]+$")
_RE_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_RE_NAME = re.compile(r"^[a-z_][a-z0-9_-]{0,31}$")
_RE_DBNAME = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")
_RE_SITENAME = re.compile(r"^[A-Za-z0-9]([A-Za-z0-9.-]{0,251}[A-Za-z0-9])?$")
# A directory (tenant) ID, application ID or mailbox: each is put into a
# request path, so nothing that could change the path is accepted.
_RE_GRAPHID = re.compile(r"^[A-Za-z0-9._@+-]+$")
# A value that looks like it names a secret but holds it literally.
_SECRET_WORDS = ("password", "secret", "api_key", "_token", "_key")


class Config:
    """A validated deployment configuration.

    ``Config.load(path)`` returns one or raises KitError listing *every*
    problem at once, each naming the section, the key and what is wrong, so an
    operator fixes the file in one pass rather than one error per run.
    """

    def __init__(self, path: Path, values: dict, secrets_spec: dict):
        self.path = path
        self.values = values
        self._secrets = secrets_spec  # (section, base) -> ("file"|"env", where)

    def __getitem__(self, section: str) -> dict:
        return self.values[section]

    # -------------------------------------------------------------- secrets
    def has_secret(self, section: str, base: str) -> bool:
        return (section, base) in self._secrets

    def secret(self, section: str, base: str, required: bool = True) -> str | None:
        spec = self._secrets.get((section, base))
        if not spec:
            if required:
                raise KitError(f"[{section}] needs {base}_file or {base}_env")
            return None
        kind, where = spec
        if kind == "env":
            value = os.environ.get(where)
            if not value:
                raise KitError(f"[{section}] {base}_env names ${where}, which is not set in this environment")
            return value
        path = Path(where)
        if not path.exists():
            raise KitError(f"[{section}] {base}_file: {path} does not exist")
        value = path.read_text().strip()
        if not value:
            raise KitError(f"[{section}] {base}_file: {path} is empty")
        return value

    def secret_spec(self, section: str, base: str) -> dict | None:
        spec = self._secrets.get((section, base))
        if not spec:
            return None
        return {"file": spec[1]} if spec[0] == "file" else {"env": spec[1]}

    # --------------------------------------------------------------- derived
    @property
    def install_dir(self) -> Path:
        return Path(self["paths"]["install_dir"])

    @property
    def site(self) -> str:
        return self["site"]["name"]

    def public_url(self) -> str:
        port = self["tls"]["https_port"]
        if self["tls"]["proxy"] == "none":
            return f"https://{self['site']['hostname']}"
        suffix = "" if port == 443 else f":{port}"
        return f"https://{self['site']['hostname']}{suffix}"

    # ------------------------------------------------------------------ load
    @classmethod
    def load(cls, path: str | Path, check_files: bool = True) -> "Config":
        path = Path(path)
        if not path.is_file():
            raise KitError(f"no configuration file at {path}. Start from consilium.conf.example.")
        parser = configparser.ConfigParser(interpolation=None, inline_comment_prefixes=None)
        parser.optionxform = str  # keys are case-sensitive and lower-case by convention
        try:
            parser.read(path)
        except configparser.Error as e:
            raise KitError(f"{path} is not a valid configuration file: {e}") from e

        errors: list[str] = []
        values: dict = {}
        secrets_spec: dict = {}

        for section in parser.sections():
            if section not in SCHEMA:
                errors.append(f"[{section}] is not a known section (known: {', '.join(SCHEMA)})")

        for section, keys in SCHEMA.items():
            given = dict(parser.items(section)) if parser.has_section(section) else {}
            out: dict = {}
            secret_bases = {k for k, (kind, *_rest) in keys.items() if kind == "secret"}
            allowed = set(keys) - secret_bases
            allowed |= {f"{b}_file" for b in secret_bases} | {f"{b}_env" for b in secret_bases}
            for key in given:
                if key not in allowed:
                    hint = ""
                    if key in secret_bases:
                        hint = (f" — a secret is never written here; use {key}_file (a file holding "
                                f"only the secret) or {key}_env (an environment variable)")
                    errors.append(f"[{section}] {key}: not a known setting{hint}")
                elif key.endswith(_SECRET_WORDS):
                    errors.append(f"[{section}] {key}: looks like a literal secret; use {key}_file or {key}_env")

            for key, (kind, required, default) in keys.items():
                if kind == "secret":
                    file_value = given.get(f"{key}_file", "").strip()
                    env_value = given.get(f"{key}_env", "").strip()
                    if file_value and env_value:
                        errors.append(f"[{section}] give {key}_file or {key}_env, not both")
                    elif file_value:
                        if not file_value.startswith("/"):
                            errors.append(f"[{section}] {key}_file: {file_value!r} must be an absolute path")
                        else:
                            secrets_spec[(section, key)] = ("file", file_value)
                    elif env_value:
                        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", env_value):
                            errors.append(f"[{section}] {key}_env: {env_value!r} is not an environment variable name")
                        else:
                            secrets_spec[(section, key)] = ("env", env_value)
                    elif required:
                        errors.append(f"[{section}] {key}_file or {key}_env is required")
                    continue

                raw = given.get(key)
                if raw is None or raw.strip() == "":
                    if default is None and required:
                        errors.append(f"[{section}] {key} is required")
                        continue
                    raw = default if default is not None else ""
                raw = raw.strip()
                try:
                    out[key] = _coerce(kind, raw)
                except ValueError as e:
                    errors.append(f"[{section}] {key} = {raw!r}: {e}")
            values[section] = out

        if not errors:
            errors.extend(_cross_checks(values, secrets_spec, check_files))
        if errors:
            raise KitError(f"{path} has {len(errors)} problem(s):\n  - " + "\n  - ".join(errors))
        return cls(path, values, secrets_spec)


def _coerce(kind: str, raw: str):
    optional = "?" in kind.split(":", 1)[0]
    base = kind.split(":", 1)[0].rstrip("?")
    arg = kind.split(":", 1)[1] if ":" in kind else ""
    if optional and raw == "":
        return ""
    if base == "str":
        return raw
    if base == "name":
        if not _RE_NAME.match(raw):
            raise ValueError("use lower-case letters, digits, '_' and '-' (a system account name)")
        return raw
    if base == "dbname":
        if not _RE_DBNAME.match(raw):
            raise ValueError("use lower-case letters, digits and '_', starting with a letter")
        return raw
    if base == "graphid":
        if not _RE_GRAPHID.match(raw):
            raise ValueError("use letters, digits and . _ @ + - only (an ID, a domain or a mailbox address)")
        return raw
    if base == "sitename":
        if not _RE_SITENAME.match(raw):
            raise ValueError("use letters, digits, dots and hyphens")
        return raw
    if base == "host":
        if not (_RE_HOST.match(raw) or _RE_IP.match(raw)):
            raise ValueError("not a valid host name or address")
        return raw
    if base == "port":
        if not raw.isdigit() or not 1 <= int(raw) <= 65535:
            raise ValueError("a port is a number from 1 to 65535")
        return int(raw)
    if base == "int":
        lo, hi = (int(x) for x in arg.split(":"))
        if not re.fullmatch(r"\d+", raw) or not lo <= int(raw) <= hi:
            raise ValueError(f"must be a whole number from {lo} to {hi}")
        return int(raw)
    if base == "bool":
        if raw.lower() in TRUE:
            return True
        if raw.lower() in FALSE:
            return False
        raise ValueError("use yes or no")
    if base == "path":
        if not raw.startswith("/"):
            raise ValueError("must be an absolute path")
        if re.search(r"\s", raw):
            raise ValueError("must not contain spaces")
        return raw.rstrip("/") or "/"
    if base == "email":
        if not _RE_EMAIL.match(raw):
            raise ValueError("not an email address")
        return raw
    if base == "url":
        schemes = arg.split("|")
        parsed = urllib.parse.urlsplit(raw)
        if parsed.scheme not in schemes or not parsed.hostname:
            raise ValueError(f"must be a {' or '.join(s + '://' for s in schemes)} URL")
        return raw
    if base == "tz":
        if not _timezone_exists(raw):
            raise ValueError("not an IANA time zone name (for example Europe/London or America/New_York)")
        return raw
    if base == "choice":
        choices = arg.split("|")
        if raw not in choices:
            raise ValueError(f"must be one of: {', '.join(choices)}")
        return raw
    raise ValueError(f"unknown kind {kind}")


def _timezone_exists(name: str) -> bool:
    if not re.fullmatch(r"[A-Za-z0-9_+\-]+(/[A-Za-z0-9_+\-]+)*", name):
        return False
    try:
        import zoneinfo

        zoneinfo.ZoneInfo(name)
        return True
    except Exception:  # noqa: BLE001 -- no tz database on this host: accept the shape
        return name == "UTC" or not Path("/usr/share/zoneinfo").is_dir()


def _cross_checks(v: dict, secrets_spec: dict, check_files: bool) -> list[str]:
    errors = []
    if v["database"]["provisioning"] == "superuser" and ("database", "root_password") not in secrets_spec:
        errors.append("[database] provisioning = superuser needs root_password_file or root_password_env "
                      "(or use provisioning = provisioned if the database already exists)")
    if v["tls"]["proxy"] != "none":
        for key in ("cert_file", "key_file"):
            if not v["tls"][key]:
                errors.append(f"[tls] {key} is required when proxy = {v['tls']['proxy']}")
            elif check_files and not Path(v["tls"][key]).is_file():
                errors.append(f"[tls] {key}: {v['tls'][key]} does not exist")
        if v["tls"]["http_port"] == v["tls"]["https_port"]:
            errors.append("[tls] http_port and https_port must differ")
    ports = {"web.port": v["web"]["port"]}
    if v["tls"]["proxy"] != "none":
        ports.update({"tls.https_port": v["tls"]["https_port"], "tls.http_port": v["tls"]["http_port"]})
    seen: dict = {}
    for name, port in ports.items():
        if port in seen:
            errors.append(f"{name} and {seen[port]} are both {port}")
        seen[port] = name
    if v["redis"]["cache_url"] == v["redis"]["queue_url"]:
        errors.append("[redis] cache_url and queue_url must differ (a different database number is enough): "
                      "flushing the cache would otherwise drop queued jobs")
    if v["email"]["enabled"]:
        for key in ("smtp_host", "sender"):
            if not v["email"][key]:
                errors.append(f"[email] {key} is required when enabled = yes")
        if v["email"]["login"] and ("email", "password") not in secrets_spec:
            errors.append("[email] login is set, so password_file or password_env is required")
    if v["email"]["graph_enabled"]:
        for key in ("graph_tenant_id", "graph_client_id", "graph_sender"):
            if not v["email"][key]:
                errors.append(f"[email] {key} is required when graph_enabled = yes")
        if ("email", "graph_client_secret") not in secrets_spec:
            errors.append("[email] graph_client_secret_file or graph_client_secret_env is required "
                          "when graph_enabled = yes")
    mode = v["sso"]["mode"]
    if mode == "oidc":
        for key in ("oidc_authorize_url", "oidc_token_url", "oidc_userinfo_url", "oidc_client_id"):
            if not v["sso"][key]:
                errors.append(f"[sso] {key} is required when mode = oidc")
        if ("sso", "oidc_client_secret") not in secrets_spec:
            errors.append("[sso] oidc_client_secret_file or oidc_client_secret_env is required when mode = oidc")
    if mode == "ldap":
        for key in ("ldap_server_url", "ldap_bind_dn", "ldap_user_search_path", "ldap_group_search_path",
                    "ldap_search_filter", "ldap_username_attribute"):
            if not v["sso"][key]:
                errors.append(f"[sso] {key} is required when mode = ldap")
        if ("sso", "ldap_bind_password") not in secrets_spec:
            errors.append("[sso] ldap_bind_password_file or ldap_bind_password_env is required when mode = ldap")
        if v["sso"]["ldap_search_filter"] and "{0}" not in v["sso"]["ldap_search_filter"]:
            errors.append("[sso] ldap_search_filter must contain {0}, where the sign-in name goes")
    if v["assistant"]["ai_enabled"]:
        for key in ("ai_endpoint_url", "ai_model"):
            if not v["assistant"][key]:
                errors.append(f"[assistant] {key} is required when ai_enabled = yes")
    if not re.fullmatch(r"[0-9A-Za-z*,:.\-/ ~]+", v["backup"]["schedule"]):
        errors.append("[backup] schedule is not a systemd calendar expression (e.g. *-*-* 02:30:00)")
    install_dir = v["paths"]["install_dir"]
    if v["backup"]["dir"].startswith(install_dir + "/"):
        errors.append("[backup] dir must be outside [paths] install_dir, so a reinstall cannot remove the backups")
    if check_files:
        for (section, base), (kind, where) in secrets_spec.items():
            if kind == "file" and Path(where).exists():
                mode_bits = Path(where).stat().st_mode & 0o077
                if mode_bits & 0o007:
                    errors.append(f"[{section}] {base}_file: {where} is readable by every user on the host; "
                                  f"chmod 600 it")
    return errors


# =========================================================================
# Running things
# =========================================================================


class Runner:
    """Runs commands, logs them, and switches to the service account."""

    def __init__(self, cfg: Config, log_name: str):
        self.cfg = cfg
        self.is_root = hasattr(os, "geteuid") and os.geteuid() == 0
        self.me = getpass.getuser()
        stamp = _dt.datetime.now().strftime("%Y%m%d-%H%M%S")
        self.stamp = stamp
        logs = cfg.install_dir / "logs"
        try:
            logs.mkdir(parents=True, exist_ok=True)
            self.log_path = logs / f"kit-{log_name}-{stamp}.log"
            self.log = self.log_path.open("a")
        except OSError:
            self.log_path = Path(tempfile.gettempdir()) / f"consilium-kit-{log_name}-{stamp}.log"
            self.log = self.log_path.open("a")

    # ------------------------------------------------------------- output
    def say(self, message: str) -> None:
        print(f"\n\033[1m==> {message}\033[0m", flush=True)
        self.log.write(f"\n==> {message}\n")
        self.log.flush()

    def note(self, message: str) -> None:
        print(f"  {message}", flush=True)
        self.log.write(f"  {message}\n")
        self.log.flush()

    # ------------------------------------------------------------ running
    @property
    def service_user(self) -> str:
        return self.cfg["service"]["user"]

    def as_service(self, cmd: list[str]) -> list[str]:
        """Prefix a command so it runs as the service account."""
        if self.me == self.service_user:
            return cmd
        if not self.is_root:
            # Not root and not the service account: everything runs as whoever
            # this is (a non-system install for testing, or a restricted host).
            return cmd
        runuser = shutil.which("runuser") or shutil.which("setpriv")
        if runuser and runuser.endswith("runuser"):
            return [runuser, "-u", self.service_user, "--", *cmd]
        if runuser:
            import pwd  # POSIX only; imported here so this module loads anywhere

            pw = pwd.getpwnam(self.service_user)
            return [runuser, f"--reuid={pw.pw_uid}", f"--regid={pw.pw_gid}", "--init-groups", *cmd]
        raise KitError("neither runuser nor setpriv is available to run commands as the service account")

    def env(self, extra: dict | None = None, offline: bool = False) -> dict:
        env = dict(os.environ)
        env["FRAPPE_BENCH_ROOT"] = str(self.cfg.install_dir)
        path = [str(self.cfg.install_dir / "env" / "bin")]
        if self.cfg["database"]["client_bin_dir"]:
            path.append(self.cfg["database"]["client_bin_dir"])
        path.append(env.get("PATH", "/usr/local/bin:/usr/bin:/bin"))
        env["PATH"] = ":".join(path)
        # The service account's home is the (root-owned) installation directory;
        # give font and other caches somewhere writable, as the units do.
        env["XDG_CACHE_HOME"] = str(self.cfg.install_dir / "config" / "cache")
        if offline:
            for var in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
                env[var] = DEAD_PROXY
            env["NO_PROXY"] = env["no_proxy"] = ""
            env["PIP_NO_INDEX"] = "1"
            env["PIP_CONFIG_FILE"] = os.devnull  # ignore any index the host's pip.conf names
            env["PIP_DISABLE_PIP_VERSION_CHECK"] = "1"
        if extra:
            env.update(extra)
        return env

    def run(self, cmd: list[str], *, service: bool = False, cwd: Path | None = None,
            env: dict | None = None, check: bool = True, capture: bool = False,
            quiet: bool = False, input_text: str | None = None) -> subprocess.CompletedProcess:
        full = self.as_service(cmd) if service else cmd
        self.log.write(f"$ {' '.join(_redact(full))}  (cwd={cwd or os.getcwd()})\n")
        self.log.flush()
        result = subprocess.run(
            full, cwd=str(cwd) if cwd else None, env=env if env is not None else self.env(),
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, input=input_text)
        self.log.write(result.stdout or "")
        self.log.write(f"[exit {result.returncode}]\n")
        self.log.flush()
        if not quiet and not capture and result.stdout:
            for line in result.stdout.rstrip().splitlines()[-40:]:
                if "Updating DocTypes" in line:
                    continue
                print(f"    {line}")
        if check and result.returncode != 0:
            tail = "\n    ".join((result.stdout or "").rstrip().splitlines()[-15:])
            raise KitError(f"`{' '.join(_redact(cmd))[:160]}` failed (exit {result.returncode}).\n    {tail}\n"
                           f"  Full log: {self.log_path}")
        return result

    def frappe(self, args: list[str], site: str | None = None, **kw) -> subprocess.CompletedProcess:
        cmd = [str(self.cfg.install_dir / "env" / "bin" / "python"), "-m", "frappe.utils.bench_helper", "frappe"]
        if site:
            cmd += ["--site", site]
        return self.run(cmd + args, service=True, cwd=self.cfg.install_dir / "sites", **kw)

    def bench_python(self, script: Path, args: list[str], **kw) -> subprocess.CompletedProcess:
        cmd = [str(self.cfg.install_dir / "env" / "bin" / "python"), str(script), *args]
        return self.run(cmd, service=True, cwd=self.cfg.install_dir / "sites", **kw)


def _redact(cmd: list[str]) -> list[str]:
    out, hide = [], False
    for part in cmd:
        if hide:
            out.append("********")
            hide = False
            continue
        out.append(part)
        if part.startswith("--") and any(w in part for w in ("password", "secret")):
            hide = True
    return out


# =========================================================================
# The bundle
# =========================================================================


class Bundle:
    def __init__(self, root: Path, archive: Path | None):
        self.root = root
        self.archive = archive
        self.manifest = json.loads((root / "MANIFEST.json").read_text())

    @property
    def release_id(self) -> str:
        return hashlib.sha256((self.root / "MANIFEST.json").read_bytes()).hexdigest()[:12]

    @property
    def wheelhouse(self) -> Path:
        return self.root / "wheelhouse"

    @property
    def install(self) -> Path:
        return self.root / "install"

    def describe(self) -> str:
        m = self.manifest
        v = m.get("versions", {})
        return (f"release {self.release_id}: consilium {v.get('consilium', '?')} "
                f"(source {m.get('source_commit') or '?'}), frappe {v.get('frappe', '?')}, "
                f"for {m.get('platform')}/{m.get('machine', '?')} Python {m.get('python')}, built {m.get('built_at')}")

    def verify(self, runner: Runner) -> None:
        sums = self.root / "SHA256SUMS"
        if not sums.exists():
            raise KitError(f"no SHA256SUMS in {self.root}; the bundle is incomplete")
        bad = []
        count = 0
        for line in sums.read_text().splitlines():
            if not line.strip():
                continue
            digest, _, rel = line.partition("  ")
            path = self.root / rel
            count += 1
            if not path.is_file():
                bad.append(f"{rel} is missing")
                continue
            h = hashlib.sha256()
            with path.open("rb") as fh:
                for chunk in iter(lambda: fh.read(1 << 20), b""):
                    h.update(chunk)
            if h.hexdigest() != digest:
                bad.append(f"{rel} does not match its checksum")
        if bad:
            raise KitError("the bundle does not match its checksums — it is incomplete or was altered in "
                           "transit:\n  " + "\n  ".join(bad[:10]))
        runner.note(f"all {count} files match their recorded checksums")

    def check_host(self) -> None:
        m = self.manifest
        host_platform = sys.platform
        host_machine = _normalise_machine(platform.machine())
        want_machine = _normalise_machine(m.get("machine", host_machine))
        if m.get("platform") != host_platform or want_machine != host_machine:
            raise KitError(
                f"this bundle was built for {m.get('platform')}/{m.get('machine')} and this host is "
                f"{host_platform}/{platform.machine()}. Build one for this host with "
                f"make_bundle.py --target-platform {'linux_' + host_machine if host_platform == 'linux' else '...'}.")


def _normalise_machine(m: str) -> str:
    m = m.lower()
    return {"amd64": "x86_64", "arm64": "aarch64"}.get(m, m)


def open_bundle(path: str, runner: Runner, staging: Path) -> Bundle:
    p = Path(path).resolve()
    if p.is_dir():
        root = p if (p / "MANIFEST.json").exists() else p / "consilium-bundle"
        if not (root / "MANIFEST.json").exists():
            raise KitError(f"{p} is not an unpacked bundle (no MANIFEST.json)")
        return Bundle(root, None)
    if not p.is_file():
        raise KitError(f"no bundle at {p}")
    runner.note(f"unpacking {p.name} ({p.stat().st_size / 2**20:.0f} MB)")
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)
    with tarfile.open(p, "r:gz") as tar:
        for member in tar.getmembers():
            if member.name.startswith("/") or ".." in Path(member.name).parts:
                raise KitError(f"refusing unsafe path in bundle: {member.name!r}")
            if member.issym() or member.islnk():
                raise KitError(f"refusing link in bundle: {member.name!r}")
        if hasattr(tarfile, "data_filter"):
            tar.extractall(staging, filter="data")
        else:
            tar.extractall(staging)
    return Bundle(staging / "consilium-bundle", p)


def find_python(version: str) -> str:
    """An interpreter of exactly the version the bundle's wheels are for."""
    override = os.environ.get("CONSILIUM_PYTHON")
    candidates = [override] if override else []
    candidates += [f"python{version}", "python3", "python"]
    tried = []
    for c in candidates:
        exe = shutil.which(c) if c and not c.startswith("/") else c
        if not exe:
            continue
        out = subprocess.run([exe, "-c", "import sys, venv; print('%d.%d' % sys.version_info[:2])"],
                             capture_output=True, text=True)
        got = out.stdout.strip()
        tried.append(f"{exe} ({got or 'no venv module'})")
        if out.returncode == 0 and got == version:
            return exe
    raise KitError(
        f"the bundle's wheels are for Python {version}, and no python{version} with the venv module was "
        f"found (tried: {', '.join(tried) or 'nothing on PATH'}). Install python{version} and its venv "
        f"package from the distribution, or set CONSILIUM_PYTHON to its path.")


# =========================================================================
# Steps
# =========================================================================


def ensure_account(runner: Runner) -> None:
    import grp  # POSIX only; imported here so this module loads anywhere
    import pwd

    user, group = runner.cfg["service"]["user"], runner.cfg["service"]["group"]
    if not runner.is_root:
        runner.note(f"not root: running as {runner.me}; the service account is not created")
        return
    try:
        grp.getgrnam(group)
    except KeyError:
        runner.run(["groupadd", "--system", group])
        runner.note(f"created group {group}")
    try:
        pwd.getpwnam(user)
        runner.note(f"service account {user} exists")
    except KeyError:
        nologin = shutil.which("nologin") or "/usr/sbin/nologin"
        runner.run(["useradd", "--system", "--gid", group, "--home-dir", str(runner.cfg.install_dir),
                    "--no-create-home", "--shell", nologin, "--comment", "Consilium services", user])
        runner.note(f"created system account {user} (no login shell, no password)")


def lay_out(runner: Runner) -> None:
    cfg = runner.cfg
    base = cfg.install_dir
    owned = [base / "sites", base / "logs", base / "config", base / "config" / "cache"]
    for d in [base, base / "releases", base / "apps", base / "deploy", *owned]:
        d.mkdir(parents=True, exist_ok=True)
    backup_dir = Path(cfg["backup"]["dir"])
    backup_dir.mkdir(parents=True, exist_ok=True)
    if runner.is_root:
        user, group = cfg["service"]["user"], cfg["service"]["group"]
        os.chmod(base, 0o755)
        for d in owned + [backup_dir]:
            _chown_tree(d, user, group)
        os.chmod(backup_dir, 0o700)
    runner.note(f"{base} (code root-owned, sites/ logs/ config/ owned by {cfg['service']['user']}); "
                f"backups in {backup_dir}")


def _chown_tree(path: Path, user: str, group: str) -> None:
    shutil.chown(path, user, group)
    for root, dirs, files in os.walk(path):
        for name in dirs + files:
            try:
                shutil.chown(os.path.join(root, name), user, group)
            except (FileNotFoundError, PermissionError):
                pass


def install_python_env(runner: Runner, bundle: Bundle, release_dir: Path, force: bool) -> Path:
    """A fresh virtual environment for this release, from the bundle only."""
    python = find_python(bundle.manifest["python"])
    env_dir = release_dir / "env"
    marker = env_dir / ".consilium-release"
    if env_dir.exists() and marker.exists() and not force:
        runner.note(f"environment for release {bundle.release_id} already installed")
        return env_dir
    if env_dir.exists():
        shutil.rmtree(env_dir)
    runner.run([python, "-m", "venv", str(env_dir)])
    py = str(env_dir / "bin" / "python")
    pip_log = runner.cfg.install_dir / "logs" / f"pip-{runner.stamp}.log"
    offline = runner.env({"PIP_LOG": str(pip_log)}, offline=True)
    wheels = str(bundle.wheelhouse)
    base = [py, "-m", "pip", "install", "--no-index", "--find-links", wheels, "--no-cache-dir"]

    runner.run(base + ["--upgrade", "pip", "setuptools", "wheel"], env=offline, quiet=True)
    # Step one: the pinned dependency set, dependencies followed, plus the
    # framework's fork of PyPika from the wheelhouse.
    runner.run(base + ["-r", str(bundle.install / "requirements.txt"), "PyPika==0.48.9"], env=offline, quiet=True)
    # Step two: the framework, the application and the launcher, WITHOUT their
    # declared dependencies. The framework's metadata names two dependencies by
    # git URL, and pip honours those even under --no-index: following them would
    # reach for the network. Step one has already installed everything they need.
    runner.run(base + ["--no-deps", "--force-reinstall", "frappe", "consilium", "winbench"], env=offline, quiet=True)
    count = len(runner.run([py, "-m", "pip", "list", "--format=freeze"], env=offline, capture=True).stdout.split())
    marker.write_text(bundle.describe() + "\n")
    runner.note(f"{count} packages installed from the bundle's wheelhouse; pip log {pip_log.name}")
    record_network_evidence(runner, pip_log)
    return env_dir


# Lines in a pip log that would mean it reached for the network.
_NETWORK_SIGNS = re.compile(
    r"(https?://(?!127\.0\.0\.1:9)[^\s'\"]+|git clone|Cloning |Downloading |Looking in indexes|"
    r"Starting new HTTPS? connection)", re.I)


def network_lines(pip_log: Path) -> list[str]:
    hits = []
    if pip_log.exists():
        for line in pip_log.read_text(errors="replace").splitlines():
            # pip's own statement that it is NOT using the index names it.
            if "Ignoring indexes:" in line:
                continue
            if _NETWORK_SIGNS.search(line) and "file://" not in line:
                hits.append(line.strip()[:200])
    return hits


def record_network_evidence(runner: Runner, pip_log: Path) -> None:
    hits = network_lines(pip_log)
    reachable = _internet_reachable()
    evidence_path = runner.cfg.install_dir / "logs" / "install-evidence.json"
    evidence = {}
    if evidence_path.exists():
        try:
            evidence = json.loads(evidence_path.read_text())
        except ValueError:
            evidence = {}
    evidence.setdefault("runs", []).append({
        "at": _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds"),
        "pip_log": str(pip_log),
        "pip_index": "none (--no-index, PIP_NO_INDEX=1, PIP_CONFIG_FILE=/dev/null)",
        "proxies": DEAD_PROXY,
        "network_lines_in_pip_log": hits[:20],
        "network_line_count": len(hits),
        "internet_reachable_from_host": reachable,
    })
    evidence_path.write_text(json.dumps(evidence, indent=1))
    if hits:
        raise KitError(f"the pip log shows {len(hits)} sign(s) of network access, for example:\n  "
                       + "\n  ".join(hits[:3]) + f"\n  Full log: {pip_log}")
    runner.note(f"pip log: no index, no download, no git ({pip_log.name}); "
                f"internet from this host: {'REACHABLE' if reachable else 'unreachable'}")


def _internet_reachable() -> bool:
    """Whether this host can open a TCP connection outwards — context, not a check."""
    for host in ("1.1.1.1", "8.8.8.8"):
        try:
            with socket.create_connection((host, 443), timeout=3):
                return True
        except OSError:
            continue
    return False


def switch_release(runner: Runner, release_dir: Path) -> Path | None:
    """Point <install_dir>/env at this release's environment; return the previous one."""
    link = runner.cfg.install_dir / "env"
    previous = None
    if link.is_symlink():
        previous = Path(os.readlink(link))
        if not previous.is_absolute():
            previous = (link.parent / previous).resolve()
    elif link.exists():
        raise KitError(f"{link} exists and is not a link to a release; move it aside first")
    tmp = link.with_name("env.new-link")
    if tmp.is_symlink() or tmp.exists():
        tmp.unlink()
    tmp.symlink_to(release_dir / "env")
    os.replace(tmp, link)
    return previous.parent if previous else None


def copy_kit(runner: Runner, bundle: Bundle, release_dir: Path) -> None:
    """Docs and tooling that later operations need, independent of the bundle."""
    docs_src = bundle.root / "docs"
    docs_dst = release_dir / "docs"
    if docs_dst.exists():
        shutil.rmtree(docs_dst)
    shutil.copytree(docs_src, docs_dst)
    link = runner.cfg.install_dir / "docs"
    if link.is_symlink() or link.exists():
        if link.is_dir() and not link.is_symlink():
            shutil.rmtree(link)
        else:
            link.unlink()
    link.symlink_to(docs_dst)

    deploy = runner.cfg.install_dir / "deploy"
    for item in bundle.install.iterdir():
        target = deploy / item.name
        if target.is_dir() and not target.is_symlink():
            shutil.rmtree(target)
        if item.is_dir():
            shutil.copytree(item, target)
        else:
            shutil.copy2(item, target)
    # Keep the asset archive with the release, so a rollback can put it back.
    assets_dst = release_dir / "assets"
    if not assets_dst.exists():
        shutil.copytree(bundle.root / "assets", assets_dst)
    (release_dir / "MANIFEST.json").write_text((bundle.root / "MANIFEST.json").read_text())
    runner.note(f"help-assistant documents -> {link}; kit -> {deploy}")


def write_bench_config(runner: Runner) -> None:
    cfg = runner.cfg
    sites = cfg.install_dir / "sites"
    apps_txt = sites / "apps.txt"
    apps_txt.write_text("frappe\nconsilium\n")
    common_path = sites / "common_site_config.json"
    common = json.loads(common_path.read_text()) if common_path.exists() else {}
    common.update({
        "db_type": "postgres",
        "db_host": cfg["database"]["host"],
        "db_port": cfg["database"]["port"],
        "redis_cache": cfg["redis"]["cache_url"],
        "redis_queue": cfg["redis"]["queue_url"],
        "redis_socketio": cfg["redis"]["queue_url"],
        "socketio_port": 9000,
        "webserver_port": cfg["web"]["port"],
        "developer_mode": 0,
        # On the installation, not the site: a site restored from a backup
        # brings its own site_config.json, which would not carry this.
        "assistant_docs_path": str(cfg.install_dir / "docs"),
        "default_site": cfg.site,
        # Without this the framework appends webserver_port to host_name when
        # it builds an absolute URL, so every link in a notification — and every
        # stylesheet the PDF engine fetches — points at https://<host>:8000,
        # which nothing serves. The flag is the framework's own marker for "a
        # service manager runs this installation"; nothing else reads it.
        "restart_systemd_on_update": 1,
    })
    common_path.write_text(json.dumps(common, indent=1, sort_keys=True))
    (cfg.install_dir / "winbench.json").write_text(json.dumps(
        {"version": "kit", "web_workers": 1, "background_workers": cfg["web"]["background_workers"]}, indent=2))
    if runner.is_root:
        for p in (apps_txt, common_path):
            shutil.chown(p, cfg["service"]["user"], cfg["service"]["group"])
            os.chmod(p, 0o640)
    runner.note(f"{common_path.name}: database {cfg['database']['host']}:{cfg['database']['port']}, "
                f"assistant documents at {cfg.install_dir / 'docs'}")


def admin_password(runner: Runner) -> str:
    cfg = runner.cfg
    spec = cfg.secret_spec("site", "admin_password")
    if spec and "env" in spec:
        return cfg.secret("site", "admin_password")
    path = Path(spec["file"]) if spec else cfg.install_dir / "config" / "admin_password"
    if path.exists() and path.read_text().strip():
        return path.read_text().strip()
    value = secrets.token_urlsafe(18)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as fh:
        fh.write(value + "\n")
    runner.note(f"generated an administrator password in {path} (mode 0600); change it after first sign-in")
    return value


def database_exists(runner: Runner) -> bool:
    db = runner.cfg["database"]
    env = runner.env({"PGPASSWORD": runner.cfg.secret("database", "root_password"), "PGCONNECT_TIMEOUT": "10"})
    result = runner.run(["psql", "-h", db["host"], "-p", str(db["port"]), "-U", db["root_user"], "-d", "postgres",
                         "-Atc", f"select 1 from pg_database where datname = '{db['name']}'"],
                        env=env, capture=True, check=False)
    if result.returncode != 0:
        raise KitError(f"cannot sign in to PostgreSQL as {db['root_user']}: {result.stdout.strip()[-300:]}")
    return result.stdout.strip() == "1"


def create_site(runner: Runner, recreate_database: bool = False) -> None:
    cfg = runner.cfg
    site_config = cfg.install_dir / "sites" / cfg.site / "site_config.json"
    db = cfg["database"]
    if site_config.exists():
        runner.note(f"site {cfg.site} exists; not recreated")
    else:
        if db["provisioning"] == "superuser" and database_exists(runner) and not recreate_database:
            # The framework drops an existing database of the same name when it
            # creates a site. A missing site directory with its database still
            # present is exactly the situation where that would destroy data.
            raise KitError(
                f"the database {db['name']} already exists on {db['host']}, but this installation has no "
                f"site for it. Refusing to create the site, which would drop that database. If it holds a "
                f"previous installation's data, restore the site directory (or use restore.sh). If it is "
                f"disposable, re-run with --recreate-database.")
        args = ["new-site", cfg.site, "--db-type", "postgres", "--db-host", db["host"],
                "--db-port", str(db["port"]), "--db-name", db["name"],
                "--db-password", cfg.secret("database", "password"),
                "--admin-password", admin_password(runner)]
        if db["provisioning"] == "superuser":
            args += ["--db-root-username", db["root_user"],
                     "--db-root-password", cfg.secret("database", "root_password")]
        else:
            # The database and its owner role already exist and we hold no
            # superuser login, so the framework must not try to create them.
            args += ["--no-setup-db"]
        runner.frappe(args)
        runner.note(f"created site {cfg.site} on database {db['name']}")

    installed = runner.frappe(["list-apps"], site=cfg.site, capture=True).stdout
    if "consilium" not in installed:
        runner.frappe(["install-app", "consilium"], site=cfg.site)
        runner.note("installed the application into the site")
    # Always migrate: it is idempotent, and the application's after-migrate
    # steps (branding defaults, scope trimming, constraints the framework's
    # schema sync does not keep) run only here.
    runner.frappe(["migrate"], site=cfg.site)
    runner.note("migrated; branding defaults and scope trimming applied")


def import_assets(runner: Runner, release_dir: Path) -> None:
    archives = sorted((release_dir / "assets").glob("frappe-assets-*.tar.gz"))
    if not archives:
        raise KitError("no prebuilt asset bundle in the release; the interface would render blank")
    py = str(runner.cfg.install_dir / "env" / "bin" / "python")
    # As root: the framework's compiled bundles go into the release's own
    # (root-owned) environment. sites/assets is then handed to the service account.
    runner.run([py, "-m", "winbench.cli", "assets", "--import", str(archives[-1]), "--copy"],
               cwd=runner.cfg.install_dir, quiet=True)
    if runner.is_root:
        _chown_tree(runner.cfg.install_dir / "sites" / "assets", runner.service_user, runner.cfg["service"]["group"])
    runner.note(f"front-end assets from {archives[-1].name}, copied (not linked)")


def seed_and_configure(runner: Runner) -> dict:
    cfg = runner.cfg
    deploy = cfg.install_dir / "deploy"
    runner.bench_python(deploy / "seed.py", ["--site", cfg.site], quiet=True)
    runner.note("reference data loaded (idempotent)")
    # Secret files are readable by root only. They are read here and handed to
    # the child process in its environment — which, unlike its command line, no
    # other account on the host can read — never written anywhere else.
    child_env: dict = {}

    def handoff(section: str, base: str) -> dict | None:
        spec = cfg.secret_spec(section, base)
        if not spec:
            return None
        name = f"CONSILIUM_SECRET_{section.upper()}_{base.upper()}"
        child_env[name] = cfg.secret(section, base)
        return {"env": name}

    settings = {
        "site": cfg.site,
        "hostname": cfg["site"]["hostname"],
        "public_url": cfg.public_url(),
        "admin_email": cfg["site"]["admin_email"],
        "timezone": cfg["site"]["timezone"],
        "email": dict(cfg["email"], password=handoff("email", "password") if cfg["email"]["enabled"] else None,
                      graph_client_secret=handoff("email", "graph_client_secret")
                      if cfg["email"]["graph_enabled"] else None),
        "sso": dict(cfg["sso"],
                    oidc_client_secret=handoff("sso", "oidc_client_secret") if cfg["sso"]["mode"] == "oidc" else None,
                    ldap_bind_password=handoff("sso", "ldap_bind_password") if cfg["sso"]["mode"] == "ldap" else None),
        "assistant": cfg["assistant"],
    }
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, dir=str(cfg.install_dir / "config")) as fh:
        json.dump(settings, fh)
        settings_path = Path(fh.name)
    try:
        if runner.is_root:
            shutil.chown(settings_path, runner.service_user, cfg["service"]["group"])
        result = runner.bench_python(deploy / "configure_site.py", ["--settings", str(settings_path)],
                                     capture=True, env=runner.env(child_env))
    finally:
        settings_path.unlink(missing_ok=True)
    summary = _last_json(result.stdout)
    for key, value in summary.items():
        runner.note(f"{key:<18} {value}")
    return summary


def _last_json(text: str) -> dict:
    for line in reversed((text or "").strip().splitlines()):
        line = line.strip()
        if line.startswith("{") and line.endswith("}"):
            try:
                return json.loads(line)
            except ValueError:
                continue
    return {}


# ------------------------------------------------------------- PDF engine

WKHTMLTOPDF_VERSION = "0.12.6"


def pdf_engine_version() -> str | None:
    exe = shutil.which("wkhtmltopdf") or ("/usr/local/bin/wkhtmltopdf" if Path("/usr/local/bin/wkhtmltopdf").exists() else None)
    if not exe:
        return None
    out = subprocess.run([exe, "--version"], capture_output=True, text=True)
    return out.stdout.strip() or None


def os_release() -> dict:
    data = {}
    path = Path("/etc/os-release")
    if path.exists():
        for line in path.read_text().splitlines():
            if "=" in line:
                k, _, v = line.partition("=")
                data[k] = v.strip().strip('"')
    return data


def install_pdf_engine(runner: Runner, bundle: Bundle) -> None:
    current = pdf_engine_version()
    if current and WKHTMLTOPDF_VERSION in current and "patched qt" in current.lower():
        runner.note(f"already present: {current}")
        return
    osr = os_release()
    family = " ".join([osr.get("ID", ""), osr.get("ID_LIKE", "")]).lower()
    major = osr.get("VERSION_ID", "").split(".")[0]
    machine = _normalise_machine(platform.machine())
    vendor = bundle.root / "vendor" / "wkhtmltopdf"
    if "debian" in family or "ubuntu" in family:
        arch = {"x86_64": "amd64", "aarch64": "arm64"}.get(machine, machine)
        package = next(iter(sorted(vendor.glob(f"wkhtmltox_*.jammy_{arch}.deb"))), None)
        install = ["apt-get", "install", "-y", "--no-install-recommends", "--no-download"]
    elif any(x in family for x in ("rhel", "fedora", "centos", "rocky", "almalinux")):
        release = "almalinux9" if major not in ("8",) else "almalinux8"
        package = next(iter(sorted(vendor.glob(f"wkhtmltox-*.{release}.{machine}.rpm"))), None)
        install = ["dnf", "install", "-y", "--disablerepo=*", "--setopt=install_weak_deps=False"]
    else:
        package, install = None, []
    if not package:
        runner.note(f"WARNING: no bundled PDF engine package for {osr.get('PRETTY_NAME', 'this system')} on "
                    f"{machine}; PDF download will fail until wkhtmltopdf {WKHTMLTOPDF_VERSION} (with patched "
                    f"Qt) is installed")
        return
    if not runner.is_root:
        runner.note(f"WARNING: not root, so the bundled PDF engine is not installed. As root: "
                    f"{' '.join(install)} {package}")
        return
    # Offline by construction: apt-get --no-download and dnf --disablerepo=*
    # install only the local package, and fail cleanly — before changing
    # anything — if a library it needs is not already on the host.
    result = runner.run(install + [str(package)], check=False, env=runner.env(offline=True))
    if result.returncode != 0:
        raise KitError(
            f"the PDF engine ({package.name}) needs system libraries that are not installed. "
            f"Install them from the distribution's own repository and re-run. See the host "
            f"prerequisites in docs/RUNBOOK.md. Output:\n    "
            + "\n    ".join((result.stdout or "").strip().splitlines()[-8:]))
    runner.note(f"installed {package.name}: {pdf_engine_version()}")


# ------------------------------------------------------------ services

TEMPLATES = KIT_DIR / "service"


def render_templates(cfg: Config, out_dir: Path) -> list[Path]:
    """Fill in the service and proxy templates. Returns the files written."""
    https_port = cfg["tls"]["https_port"]
    extra_path = cfg["database"]["client_bin_dir"]
    values = {
        "INSTALL_DIR": str(cfg.install_dir),
        "USER": cfg["service"]["user"],
        "GROUP": cfg["service"]["group"],
        "SITE": cfg.site,
        "HOSTNAME": cfg["site"]["hostname"],
        "WEB_PORT": str(cfg["web"]["port"]),
        "THREADS": str(cfg["web"]["threads"]),
        "SOCKETIO_PORT": "9000",
        "HTTPS_PORT": str(https_port),
        "HTTP_PORT": str(cfg["tls"]["http_port"]),
        "HTTPS_PORT_SUFFIX": "" if https_port == 443 else f":{https_port}",
        "CERT_FILE": cfg["tls"]["cert_file"],
        "KEY_FILE": cfg["tls"]["key_file"],
        "CONFIG": str(cfg.path.resolve()),
        "BACKUP_DIR": cfg["backup"]["dir"],
        "BACKUP_SCHEDULE": cfg["backup"]["schedule"],
        "EXTRA_PATH": (extra_path + ":") if extra_path else "",
    }
    written = []
    groups = {"systemd": TEMPLATES / "systemd"}
    if cfg["tls"]["proxy"] in ("nginx", "caddy"):
        groups[cfg["tls"]["proxy"]] = TEMPLATES / cfg["tls"]["proxy"]
    for group, src_dir in groups.items():
        if not src_dir.is_dir():
            raise KitError(f"missing templates: {src_dir}")
        for src in sorted(src_dir.iterdir()):
            if not src.is_file():
                continue
            text = render_text(src.read_text(), values, socketio=cfg["web"]["socketio"])
            dst = out_dir / group / src.name
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_text(text)
            written.append(dst)
    return written


def render_text(text: str, values: dict, socketio: bool = False) -> str:
    lines = []
    for line in text.splitlines():
        if line.startswith("@IF_SOCKETIO@"):
            if not socketio:
                continue
            line = line[len("@IF_SOCKETIO@"):]
        lines.append(line)
    text = "\n".join(lines) + "\n"
    for key, value in values.items():
        text = text.replace(f"@{key}@", value)
    left = sorted(set(re.findall(r"@[A-Z_]+@", text)))
    if left:
        raise KitError(f"template placeholders with no value: {', '.join(left)}")
    return text


def manage_services_wanted(runner: Runner) -> bool:
    mode = runner.cfg["service"]["manage_services"]
    has_systemd = Path("/run/systemd/system").is_dir() and shutil.which("systemctl") is not None
    if mode == "no":
        return False
    if mode == "yes":
        if not runner.is_root:
            raise KitError("[service] manage_services = yes needs root")
        if not has_systemd:
            raise KitError("[service] manage_services = yes, but systemd is not running on this host")
        return True
    return runner.is_root and has_systemd


def install_services(runner: Runner, start: bool = True) -> None:
    cfg = runner.cfg
    rendered_dir = cfg.install_dir / "config"
    files = render_templates(cfg, rendered_dir)
    runner.note(f"rendered {len(files)} files into {rendered_dir}/(systemd|{cfg['tls']['proxy']})")
    if shutil.which("systemd-analyze"):
        result = runner.run(["systemd-analyze", "verify", *[str(f) for f in files if f.parent.name == "systemd"]],
                            check=False, capture=True)
        problems = [l for l in (result.stdout or "").splitlines() if l.strip() and "consilium" in l]
        runner.note("systemd-analyze verify: " + ("no problems" if not problems else "; ".join(problems[:5])))
    if not manage_services_wanted(runner):
        runner.note("services not installed (manage_services, root or systemd). To install them as root:")
        runner.note(f"  cp {rendered_dir}/systemd/* /etc/systemd/system/ && systemctl daemon-reload")
        runner.note(f"  systemctl enable --now consilium.target consilium-backup.timer "
                    + " ".join(f"consilium-worker@{i}" for i in range(1, cfg['web']['background_workers'] + 1)))
        return
    unit_dir = Path("/etc/systemd/system")
    for f in files:
        if f.parent.name == "systemd":
            shutil.copy2(f, unit_dir / f.name)
            os.chmod(unit_dir / f.name, 0o644)
    runner.run(["systemctl", "daemon-reload"])
    workers = [f"consilium-worker@{i}.service" for i in range(1, cfg["web"]["background_workers"] + 1)]
    # Remove workers beyond the configured count (after a reduction).
    listed = runner.run(["systemctl", "list-units", "--all", "--plain", "--no-legend", "consilium-worker@*"],
                        capture=True, check=False).stdout
    for line in listed.splitlines():
        unit = line.split()[0] if line.split() else ""
        if unit and unit not in workers:
            runner.run(["systemctl", "disable", "--now", unit], check=False)
    units = ["consilium.target", "consilium-web.service", "consilium-scheduler.service",
             "consilium-backup.timer", *workers]
    runner.run(["systemctl", "enable", *units], quiet=True)
    if start:
        runner.run(["systemctl", "restart", "consilium.target", *workers])
        runner.run(["systemctl", "start", "consilium-backup.timer"])
    runner.note("systemd: " + ", ".join(units) + (" enabled and started" if start else " enabled"))
    install_proxy(runner)


def install_proxy(runner: Runner) -> None:
    cfg = runner.cfg
    proxy = cfg["tls"]["proxy"]
    if proxy == "none":
        runner.note("no reverse proxy configured ([tls] proxy = none)")
        return
    rendered = cfg.install_dir / "config" / proxy
    if proxy == "nginx":
        nginx = shutil.which("nginx")
        if not nginx:
            runner.note(f"nginx is not installed; its configuration is in {rendered}/consilium.conf")
            return
        conf_dir = Path("/etc/nginx/conf.d")
        conf_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(rendered / "consilium.conf", conf_dir / "consilium.conf")
        runner.run([nginx, "-t"])
        if Path("/run/systemd/system").is_dir():
            runner.run(["systemctl", "enable", "nginx"], check=False, quiet=True)
            runner.run(["systemctl", "reload-or-restart", "nginx"])
        else:
            runner.run([nginx, "-s", "reload"], check=False) if Path("/run/nginx.pid").exists() else runner.run([nginx])
        runner.note(f"nginx: {conf_dir / 'consilium.conf'} installed, configuration test passed, reloaded")
    else:
        caddy = shutil.which("caddy")
        target = Path("/etc/caddy/consilium.caddy")
        if not caddy:
            runner.note(f"caddy is not installed; its configuration is in {rendered}/consilium.caddy")
            return
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(rendered / "consilium.caddy", target)
        runner.run([caddy, "validate", "--adapter", "caddyfile", "--config", str(target)])
        runner.note(f"caddy: {target} installed and validated; import it from /etc/caddy/Caddyfile and reload")


def services_control(runner: Runner, action: str) -> bool:
    """start/stop the application's processes when systemd manages them."""
    if not (runner.is_root and Path("/run/systemd/system").is_dir() and
            Path("/etc/systemd/system/consilium.target").exists()):
        return False
    workers = [f"consilium-worker@{i}.service" for i in range(1, runner.cfg["web"]["background_workers"] + 1)]
    runner.run(["systemctl", action, "consilium.target", "consilium-web.service",
                "consilium-scheduler.service", *workers], check=(action == "start"))
    return True


def wait_for_web(runner: Runner, timeout: float = 90) -> bool:
    url = f"http://127.0.0.1:{runner.cfg['web']['port']}/api/method/ping"
    deadline = time.time() + timeout
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    while time.time() < deadline:
        try:
            with opener.open(url, timeout=5) as r:
                if r.status == 200:
                    return True
        except Exception:  # noqa: BLE001
            time.sleep(2)
    return False


def healthcheck(runner: Runner, check: bool = True) -> subprocess.CompletedProcess:
    return runner.bench_python(runner.cfg.install_dir / "deploy" / "healthcheck.py",
                               ["--site", runner.cfg.site], check=check)


def record_release(runner: Runner, bundle: Bundle, action: str) -> None:
    path = runner.cfg.install_dir / "deploy" / "installed.json"
    history = json.loads(path.read_text()) if path.exists() else {"history": []}
    entry = {"at": _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds"), "action": action,
             "release": bundle.release_id, "bundle": bundle.describe(),
             "archive_sha256": _sha256(bundle.archive) if bundle.archive else None}
    history["current"] = entry
    history["history"].append(entry)
    path.write_text(json.dumps(history, indent=1))


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def prune_releases(runner: Runner, keep: int = 2) -> None:
    releases = runner.cfg.install_dir / "releases"
    current = (runner.cfg.install_dir / "env").resolve().parent
    # Only real releases (never the unpacking area), newest first; the current
    # one and the one before it are kept, so a rollback has somewhere to go.
    dirs = sorted((d for d in releases.iterdir() if d.is_dir() and not d.name.startswith(".")),
                  key=lambda d: d.stat().st_mtime, reverse=True)
    for d in dirs[keep:]:
        if d.resolve() != current:
            shutil.rmtree(d, ignore_errors=True)
            runner.note(f"removed old release {d.name}")


def check_services_reachable(runner: Runner) -> None:
    cfg = runner.cfg
    db = cfg["database"]
    if not _port_open(db["host"], db["port"]):
        raise KitError(f"nothing is listening on {db['host']}:{db['port']}. Is PostgreSQL running and reachable "
                       f"from this host (firewall, pg_hba.conf, listen_addresses)?")
    runner.note(f"PostgreSQL port open at {db['host']}:{db['port']}")
    for key in ("cache_url", "queue_url"):
        u = urllib.parse.urlsplit(cfg["redis"][key])
        if not _port_open(u.hostname, u.port or 6379):
            raise KitError(f"nothing is listening on {u.hostname}:{u.port or 6379} ([redis] {key}). Is Redis running?")
    runner.note("Redis reachable")
    # The framework's PDF library finds the PDF engine by running `which`,
    # which a minimal RHEL-family install does not have.
    if not shutil.which("which"):
        raise KitError("the `which` command is missing (package `which` on RHEL-family systems). The PDF "
                       "library the framework uses runs it to find the PDF engine, and every PDF fails without it.")
    # The framework's restore runs `file` to tell a compressed dump from a
    # plain one; without it every restore fails before it starts.
    if not shutil.which("file"):
        raise KitError("the `file` command is missing (package `file`). The framework's restore uses it, so "
                       "no backup could be restored on this host.")
    for tool in ("psql", "pg_dump"):
        if not shutil.which(tool, path=runner.env()["PATH"]):
            raise KitError(f"{tool} is not on PATH. Install the PostgreSQL client tools (same major version as the "
                           f"server, or newer), or set [database] client_bin_dir.")
    version = subprocess.run([shutil.which("pg_dump", path=runner.env()["PATH"]), "--version"],
                             capture_output=True, text=True).stdout.strip()
    runner.note(f"client tools: {version}")


def _port_open(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=5):
            return True
    except OSError:
        return False


# =========================================================================
# Commands
# =========================================================================


def cmd_check_config(args) -> int:
    cfg = Config.load(args.config, check_files=not args.no_file_checks)
    print(f"{cfg.path}: valid")
    print(f"  site {cfg.site} at {cfg.public_url()}, installed in {cfg.install_dir}")
    print(f"  database {cfg['database']['name']} on {cfg['database']['host']}:{cfg['database']['port']} "
          f"({cfg['database']['provisioning']})")
    print(f"  proxy {cfg['tls']['proxy']}, SSO {cfg['sso']['mode']}, email {'on' if cfg['email']['enabled'] else 'off'}"
          f"{' (notifications through Microsoft Graph)' if cfg['email']['graph_enabled'] else ''}, "
          f"AI {'on' if cfg['assistant']['ai_enabled'] else 'off'}")
    return 0


def cmd_render(args) -> int:
    cfg = Config.load(args.config, check_files=False)
    out = Path(args.out)
    for f in render_templates(cfg, out):
        print(f)
    return 0


def _preflight(runner: Runner, bundle_path: str) -> tuple[Bundle, Path]:
    cfg = runner.cfg
    runner.say("Checking the host")
    runner.note(f"{platform.platform()}; running as {runner.me}{' (root)' if runner.is_root else ''}")
    check_services_reachable(runner)
    runner.say("Verifying the bundle")
    staging = cfg.install_dir / "releases" / ".incoming"
    bundle = open_bundle(bundle_path, runner, staging)
    bundle.check_host()
    runner.note(bundle.describe())
    bundle.verify(runner)
    find_python(bundle.manifest["python"])
    release_dir = cfg.install_dir / "releases" / bundle.release_id
    return bundle, release_dir


def cmd_install(args) -> int:
    cfg = Config.load(args.config)
    runner = Runner(cfg, "install")
    runner.say(f"Installing Consilium at {cfg.install_dir} for {cfg.public_url()}")
    runner.note(f"log: {runner.log_path}")
    ensure_account(runner)
    lay_out(runner)
    bundle, release_dir = _preflight(runner, args.bundle)

    runner.say("Installing the Python environment from the bundle (no network)")
    release_dir.mkdir(parents=True, exist_ok=True)
    install_python_env(runner, bundle, release_dir, force=False)
    copy_kit(runner, bundle, release_dir)
    switch_release(runner, release_dir)

    runner.say("PDF engine")
    install_pdf_engine(runner, bundle)

    runner.say("Site")
    write_bench_config(runner)
    create_site(runner, recreate_database=args.recreate_database)

    runner.say("Front-end assets")
    import_assets(runner, release_dir)

    runner.say("Reference data and site settings")
    seed_and_configure(runner)

    runner.say("Services and reverse proxy")
    install_services(runner, start=not args.no_start)

    runner.say("Health check")
    healthcheck(runner)
    record_release(runner, bundle, "install")
    release_id = bundle.release_id
    if bundle.archive:
        shutil.rmtree(cfg.install_dir / "releases" / ".incoming", ignore_errors=True)

    runner.say("Installed")
    print(f"""
  Site        : {cfg.site}
  Address     : {cfg.public_url()}
  Installed at: {cfg.install_dir}  (release {release_id})
  Log         : {runner.log_path}

  Next: {cfg.install_dir}/deploy/verify.sh --config {cfg.path}
""")
    return 0


def cmd_upgrade(args) -> int:
    cfg = Config.load(args.config)
    runner = Runner(cfg, "upgrade")
    runner.say(f"Upgrading {cfg.site} at {cfg.install_dir}")
    runner.note(f"log: {runner.log_path}")
    if not (cfg.install_dir / "env").is_symlink():
        raise KitError(f"{cfg.install_dir} has no installed release; run install.sh first")
    current = (cfg.install_dir / "env").resolve().parent
    bundle, release_dir = _preflight(runner, args.bundle)
    if release_dir.resolve() == current.resolve() and not args.force:
        runner.note(f"release {bundle.release_id} is already the installed release; nothing to do "
                    f"(--force to reinstall it)")
        return 0

    runner.say("1/7 Backup before anything changes")
    backup_dir = do_backup(runner, label="pre-upgrade")

    rollback = f"""
  ROLLBACK — the database and the code both go back:

    sudo systemctl stop consilium.target 'consilium-worker@*'
    sudo ln -sfn {current}/env {cfg.install_dir}/env
    sudo {cfg.install_dir}/deploy/restore.sh --config {cfg.path} --from {backup_dir} --yes
    sudo systemctl start consilium.target

  restore.sh re-imports the release's assets and runs the health check.
"""
    try:
        runner.say("2/7 Installing the new release beside the current one (no network)")
        release_dir.mkdir(parents=True, exist_ok=True)
        install_python_env(runner, bundle, release_dir, force=args.force)

        runner.say("3/7 Stopping the application")
        runner.frappe(["set-maintenance-mode", "on"], site=cfg.site, quiet=True)
        if services_control(runner, "stop"):
            runner.note("services stopped")
        else:
            runner.note("services are not managed by systemd here; make sure the web server, workers and "
                        "scheduler are stopped")

        runner.say("4/7 Switching to the new release")
        copy_kit(runner, bundle, release_dir)
        previous = switch_release(runner, release_dir)
        runner.note(f"env -> {release_dir.name} (was {previous.name if previous else 'none'})")
        write_bench_config(runner)

        runner.say("5/7 Migrating the database")
        started = time.time()
        runner.frappe(["migrate"], site=cfg.site)
        runner.note(f"migrated in {time.time() - started:.0f}s")
        import_assets(runner, release_dir)
        seed_and_configure(runner)
        runner.frappe(["set-maintenance-mode", "off"], site=cfg.site, quiet=True)

        runner.say("6/7 Starting the application")
        install_services(runner, start=True)
        if manage_services_wanted(runner) and not wait_for_web(runner):
            raise KitError("the web server did not answer within 90 seconds after the upgrade")

        runner.say("7/7 Health check")
        healthcheck(runner)
    except (KitError, subprocess.SubprocessError, OSError) as e:
        print(f"\n\033[31mUPGRADE FAILED: {e}\033[0m")
        print(rollback)
        runner.log.write(f"UPGRADE FAILED: {e}\n{rollback}\n")
        return 1

    record_release(runner, bundle, "upgrade")
    release_line = f"{bundle.release_id}  ({bundle.describe()})"
    shutil.rmtree(cfg.install_dir / "releases" / ".incoming", ignore_errors=True)
    prune_releases(runner)
    runner.say("Upgraded")
    print(f"""
  Release     : {release_line}
  Backup      : {backup_dir}
  Log         : {runner.log_path}

  Next: {cfg.install_dir}/deploy/verify.sh --config {cfg.path}
{rollback}""")
    return 0


def do_backup(runner: Runner, label: str = "scheduled") -> Path:
    cfg = runner.cfg
    stamp = _dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    target = Path(cfg["backup"]["dir"]) / f"{stamp}-{label}"
    target.mkdir(parents=True)
    if runner.is_root:
        shutil.chown(target, runner.service_user, cfg["service"]["group"])
    os.chmod(target, 0o700)
    started = time.time()
    runner.frappe(["backup", "--with-files", "--backup-path", str(target)], site=cfg.site, quiet=True)
    files = sorted(p for p in target.iterdir() if p.is_file())
    db = [p for p in files if p.name.endswith("-database.sql.gz")]
    conf = [p for p in files if p.name.endswith("site_config_backup.json")]
    if not db or db[0].stat().st_size < 1024:
        raise KitError(f"the backup in {target} has no database dump, or an empty one")
    if not conf:
        raise KitError(f"the backup in {target} has no copy of the site configuration (the encryption key)")
    for p in files:
        os.chmod(p, 0o600)
    manifest = {
        "site": cfg.site, "taken_at": _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds"),
        "label": label, "seconds": round(time.time() - started, 1),
        "release": (cfg.install_dir / "env").resolve().parent.name,
        "files": [{"name": p.name, "bytes": p.stat().st_size, "sha256": _sha256(p)} for p in files],
    }
    (target / "BACKUP.json").write_text(json.dumps(manifest, indent=1))
    total = sum(p.stat().st_size for p in files)
    runner.note(f"{target}: {len(files)} files, {total / 2**20:.1f} MB, {manifest['seconds']}s")
    prune_backups(runner)
    return target


def prune_backups(runner: Runner) -> None:
    root = Path(runner.cfg["backup"]["dir"])
    keep_days = runner.cfg["backup"]["retention_days"]
    cutoff = time.time() - keep_days * 86400
    sets = sorted((d for d in root.iterdir() if d.is_dir() and (d / "BACKUP.json").exists()),
                  key=lambda d: d.name)
    # Never remove the newest set, whatever its age.
    for d in sets[:-1]:
        if d.stat().st_mtime < cutoff:
            shutil.rmtree(d)
            runner.note(f"removed backup older than {keep_days} days: {d.name}")


def cmd_backup(args) -> int:
    cfg = Config.load(args.config)
    runner = Runner(cfg, "backup")
    runner.say(f"Backing up {cfg.site}")
    do_backup(runner, label=args.label)
    return 0


def cmd_restore(args) -> int:
    cfg = Config.load(args.config)
    runner = Runner(cfg, "restore")
    source = Path(args.source).resolve()
    manifest_path = source / "BACKUP.json"
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text())
        runner.say(f"Restoring {source.name} (taken {manifest['taken_at']} from {manifest['site']})")
        bad = [f["name"] for f in manifest["files"] if _sha256(source / f["name"]) != f["sha256"]]
        if bad:
            raise KitError(f"these backup files do not match their checksums: {bad}")
        runner.note(f"{len(manifest['files'])} files match their checksums")
    else:
        # A backup the framework took itself (`backup --with-files`), for
        # example from another installation or a development machine: the same
        # files, without this kit's manifest, so nothing to check them against.
        files = sorted(p for p in source.iterdir() if p.is_file())
        if not any(p.name.endswith("-database.sql.gz") for p in files):
            raise KitError(f"{source} holds no *-database.sql.gz; it is not a backup")
        manifest = {"site": "unknown", "taken_at": "unknown",
                    "files": [{"name": p.name} for p in files]}
        runner.say(f"Restoring {source.name}: a framework backup without this kit's manifest, so there are "
                   f"no recorded checksums to verify against")
    by_suffix = {}
    for f in manifest["files"]:
        for suffix in ("-database.sql.gz", "-private-files.tar", "-files.tar", "site_config_backup.json"):
            if f["name"].endswith(suffix) and suffix not in by_suffix:
                by_suffix[suffix] = source / f["name"]
                break
    sql = by_suffix.get("-database.sql.gz")
    if "site_config_backup.json" not in by_suffix:
        raise KitError(f"{source} has no *site_config_backup.json: without the encryption key it holds, every "
                       f"stored password and secret in the restored data would be unreadable")
    conf = json.loads(by_suffix["site_config_backup.json"].read_text())

    site = args.as_site or cfg.site
    in_place = site == cfg.site
    if in_place and not args.yes:
        raise KitError(f"this replaces the database of {site} with the backup. Re-run with --yes to confirm, "
                       f"or --as-site <name> --db-name <db> to restore into a new site beside it.")
    db = cfg["database"]
    if db["provisioning"] != "superuser":
        raise KitError("restoring needs the database superuser login ([database] provisioning = superuser): "
                       "the framework drops and recreates the database. With a provisioned database, ask the "
                       "database team to restore the dump into an empty database, then run migrate.")
    site_dir = cfg.install_dir / "sites" / site
    started = time.time()
    if in_place:
        runner.frappe(["set-maintenance-mode", "on"], site=site, quiet=True, check=False)
        services_control(runner, "stop")
    else:
        if site_dir.exists():
            raise KitError(f"site {site} already exists; choose another --as-site name")
        db_name = args.db_name or re.sub(r"[^a-z0-9_]", "_", site.lower())[:60]
        # An empty site to restore into, with its own database and role.
        runner.frappe(["new-site", site, "--db-type", "postgres", "--db-host", db["host"],
                       "--db-port", str(db["port"]), "--db-name", db_name,
                       "--db-root-username", db["root_user"],
                       "--db-root-password", cfg.secret("database", "root_password"),
                       "--admin-password", secrets.token_urlsafe(18)], quiet=True)
    # The encryption key must be the one the data was encrypted with, or every
    # stored password and secret in the restored data is unreadable.
    site_config_path = site_dir / "site_config.json"
    site_config = json.loads(site_config_path.read_text())
    if conf.get("encryption_key") and site_config.get("encryption_key") != conf["encryption_key"]:
        site_config["encryption_key"] = conf["encryption_key"]
        site_config_path.write_text(json.dumps(site_config, indent=1))
        runner.note("site encryption key set to the backup's")
    restore_args = ["restore", str(sql), "--db-root-username", db["root_user"],
                    "--db-root-password", cfg.secret("database", "root_password"), "--force"]
    if "-files.tar" in by_suffix:
        restore_args += ["--with-public-files", str(by_suffix["-files.tar"])]
    if "-private-files.tar" in by_suffix:
        restore_args += ["--with-private-files", str(by_suffix["-private-files.tar"])]
    runner.frappe(restore_args, site=site, quiet=True)
    restored_at = time.time()
    runner.note(f"database and files restored in {restored_at - started:.0f}s")
    # A backup from an older release is brought up to this release's schema.
    runner.frappe(["migrate"], site=site, quiet=True)
    runner.note(f"migrated in {time.time() - restored_at:.0f}s")
    runner.frappe(["set-maintenance-mode", "off"], site=site, quiet=True, check=False)
    release = (cfg.install_dir / "env").resolve().parent
    import_assets(runner, release)
    if in_place:
        services_control(runner, "start")
    runner.bench_python(cfg.install_dir / "deploy" / "healthcheck.py", ["--site", site])
    runner.say(f"Restored into {site} in {time.time() - started:.0f}s")
    return 0


# ------------------------------------------------------------------ verify


class Report:
    def __init__(self):
        self.items: list[dict] = []

    def add(self, phase: str, name: str, ok: bool | None, evidence: str, required: bool = True) -> None:
        self.items.append({"phase": phase, "check": name, "ok": ok, "required": required,
                           "evidence": evidence.strip()})
        mark = {True: "\033[32mpass\033[0m", False: "\033[31mFAIL\033[0m", None: "\033[33mskip\033[0m"}[ok]
        first = evidence.strip().splitlines()[0][:110] if evidence.strip() else ""
        print(f"  {mark}  [{phase}] {name}  \033[2m{first}\033[0m", flush=True)

    @property
    def failed(self) -> list[dict]:
        return [i for i in self.items if i["ok"] is False and i["required"]]


def cmd_verify(args) -> int:
    cfg = Config.load(args.config)
    runner = Runner(cfg, "verify")
    report = Report()
    started = _dt.datetime.now(_dt.timezone.utc)
    deploy = cfg.install_dir / "deploy"
    base = f"http://127.0.0.1:{cfg['web']['port']}"
    runner.say(f"Acceptance checks for {cfg.site}")

    # ------------------------------------------------------------ services
    if Path("/run/systemd/system").is_dir() and Path("/etc/systemd/system/consilium.target").exists():
        units = ["consilium-web.service", "consilium-scheduler.service",
                 *[f"consilium-worker@{i}.service" for i in range(1, cfg["web"]["background_workers"] + 1)]]
        states = {u: subprocess.run(["systemctl", "is-active", u], capture_output=True, text=True).stdout.strip()
                  for u in units}
        report.add("Services", "every unit is active", all(s == "active" for s in states.values()),
                   ", ".join(f"{u}={s}" for u, s in states.items()))
    else:
        report.add("Services", "systemd units active", None, "systemd does not manage the services on this host",
                   required=False)
    schedulers = _count_processes("winbench.cli scheduler")
    report.add("Services", "exactly one scheduler process on this host", schedulers == 1,
               f"{schedulers} process(es) running 'winbench.cli scheduler'")
    report.add("Services", "web server answers", wait_for_web(runner, timeout=60), f"{base}/api/method/ping")

    # ------------------------------------------------------------- health
    r = healthcheck(runner, check=False)
    tail = "\n".join(l for l in (r.stdout or "").splitlines() if "checks passed" in l or "FAIL" in l)
    report.add("Health", "deploy/healthcheck.py", r.returncode == 0, tail or r.stdout[-400:])

    # ------------------------------------------------------ Phase 1: desk
    mint = runner.bench_python(deploy / "acceptance.py", ["--site", cfg.site, "mint"], capture=True, check=False)
    sid = _last_json(mint.stdout).get("sid")
    report.add("Phase 1", "sign-in by a server-created session (no password)", bool(sid),
               f"session for Administrator created: {'yes' if sid else mint.stdout[-300:]}")
    if sid:
        r = runner.run([str(cfg.install_dir / "env" / "bin" / "python"), str(deploy / "smoke_test.py"),
                        "--site", cfg.site, "--port", str(cfg["web"]["port"]), "--sid", sid],
                       check=False, capture=True, env=runner.env({"NO_PROXY": "*"}))
        summary = next((l for l in r.stdout.splitlines() if " passed, " in l), "")
        report.add("Phase 1", "smoke test 8/8, desk loads with every asset", r.returncode == 0 and summary.startswith("8 passed"),
                   summary + "\n" + "\n".join(l for l in r.stdout.splitlines() if l.strip().startswith("[")))

    # ------------------------------------------ Phase 2: workflow machinery
    r = runner.bench_python(deploy / "acceptance.py", ["--site", cfg.site, "workflow"], capture=True, check=False)
    wf = _last_json(r.stdout)
    report.add("Phase 2", "a document moves through a workflow; Workflow Action and Version rows are written",
               wf.get("ok") is True, json.dumps(wf) if wf else r.stdout[-400:])

    # --------------------------------------------------------------- PDF
    r = runner.bench_python(deploy / "acceptance.py", ["--site", cfg.site, "pdf"], capture=True, check=False)
    pdf = _last_json(r.stdout)
    report.add("PDF", "a governing document renders to a valid PDF", pdf.get("ok") is True,
               json.dumps(pdf) if pdf else r.stdout[-400:])

    # ------------------------------------------------ Phase 3: air-gapped
    r = runner.run([str(cfg.install_dir / "env" / "bin" / "python"), "-m", "winbench.cli", "doctor"],
                   cwd=cfg.install_dir, check=False, capture=True, service=True)
    report.add("Phase 3", "winbench doctor: no compatibility patches needed on this platform",
               "(none needed on this platform)" in (r.stdout or ""),
               "\n".join(l for l in (r.stdout or "").splitlines() if l.strip())[-600:])
    evidence_path = cfg.install_dir / "logs" / "install-evidence.json"
    if evidence_path.exists():
        runs = json.loads(evidence_path.read_text()).get("runs", [])
        lines = []
        clean = bool(runs)
        for run in runs:
            # Re-read each pip log with the current rules rather than trusting
            # the count recorded at the time.
            hits = network_lines(Path(run["pip_log"]))
            clean &= not hits and Path(run["pip_log"]).exists()
            lines.append(f"{run['at']}: {len(hits)} network lines in {Path(run['pip_log']).name}; internet "
                         f"from the host {'REACHABLE' if run['internet_reachable_from_host'] else 'unreachable'}")
        report.add("Phase 3", "every install and upgrade made no network access", clean, "\n".join(lines))
    else:
        report.add("Phase 3", "install network evidence recorded", False, f"{evidence_path} is missing")

    # ------------------------------------------------------ interface sweep
    r = runner.run([str(cfg.install_dir / "env" / "bin" / "python"), str(deploy / "ui_regression.py"),
                    "--site", cfg.site, "--url", base], cwd=cfg.install_dir / "sites", check=False,
                   capture=True, service=True, env=runner.env({"NO_PROXY": "*"}))
    summary = next((l for l in reversed(r.stdout.splitlines()) if " passed, " in l), r.stdout[-300:])
    fails = "\n".join(l for l in r.stdout.splitlines() if l.startswith("FAIL") or l.startswith("      "))
    report.add("Interface", "UI regression sweep", r.returncode == 0, summary + ("\n" + fails if fails else ""))

    if sid:
        ok, detail = no_cdn_check(base, cfg.site, sid)
        report.add("Offline", "no served page or asset references an external host", ok, detail)

    # ------------------------------------------------------------- TLS
    if cfg["tls"]["proxy"] != "none":
        ok, detail = tls_check(cfg)
        report.add("TLS", f"{cfg['tls']['proxy']} terminates TLS for {cfg['site']['hostname']}", ok, detail)
    else:
        report.add("TLS", "reverse proxy", None, "[tls] proxy = none; TLS is terminated elsewhere", required=False)

    # -------------------------------------------------------- scheduler
    r = runner.bench_python(deploy / "acceptance.py", ["--site", cfg.site, "scheduler"], capture=True, check=False)
    sched = _last_json(r.stdout)
    report.add("Scheduler", "scheduler enabled for the site", sched.get("enabled") is True,
               json.dumps({k: sched.get(k) for k in ("enabled", "consilium_jobs", "recent_runs", "last_run")}))

    if sid:
        runner.bench_python(deploy / "acceptance.py", ["--site", cfg.site, "logout", "--sid", sid],
                            capture=True, check=False)

    path = write_report(cfg, report, started, args.report)
    print(f"\n  Readiness report: {path}")
    if report.failed:
        print(f"  \033[31m{len(report.failed)} required check(s) failed.\033[0m\n")
        return 1
    print(f"  \033[32mAll {sum(1 for i in report.items if i['ok'])} checks passed.\033[0m\n")
    return 0


def _count_processes(needle: str) -> int:
    count = 0
    for proc in Path("/proc").glob("[0-9]*"):
        try:
            cmdline = (proc / "cmdline").read_bytes().replace(b"\0", b" ").decode(errors="replace")
        except OSError:
            continue
        if needle in cmdline and "python" in cmdline:
            count += 1
    if not Path("/proc").is_dir():
        out = subprocess.run(["ps", "-axo", "command"], capture_output=True, text=True).stdout
        count = sum(1 for l in out.splitlines() if needle in l and "python" in l)
    return count


# References that make a browser fetch something: script, style, image, frame
# and font sources. A plain link a person may click is navigation, not a fetch.
_FETCH_ATTRS = re.compile(r"<(script|link|img|iframe|source|video|audio)\b[^>]*?\b(src|href)\s*=\s*[\"']([^\"']+)[\"']", re.I)
_CSS_URL = re.compile(r"(?:url\(\s*[\"']?|@import\s+[\"'])(https?:)?//([^/\"')\s]+)", re.I)
_CDN_MARKERS = ("//cdn.", "cdnjs.cloudflare", "jsdelivr.net", "unpkg.com", "fonts.googleapis.com",
                "fonts.gstatic.com", "ajax.googleapis.com", "code.jquery.com", "bootstrapcdn")


def no_cdn_check(base: str, site: str, sid: str) -> tuple[bool, str]:
    """Fetch the pages a signed-in user sees, and every script and stylesheet
    they load, and look for anything that would make the browser fetch from
    another host."""
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def get(path: str) -> str:
        req = urllib.request.Request(base + path, headers={"Host": site, "Cookie": f"sid={sid}"})
        try:
            with opener.open(req, timeout=60) as r:
                return r.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            return e.read().decode("utf-8", "replace")

    pages = ["/login", "/app", "/", "/forums", "/policies", "/escalations", "/tasks", "/reports", "/me"]
    offenders, assets = [], set()
    for page in pages:
        html = get(page)
        for tag, _attr, url in _FETCH_ATTRS.findall(html):
            if tag.lower() == "link" and not re.search(r"\.(css|woff2?|ttf|ico|png|svg)(\?|$)", url):
                continue
            host = urllib.parse.urlsplit(url).netloc
            if url.startswith("//") or (host and host.split(":")[0] not in (site, "127.0.0.1", "localhost")):
                offenders.append(f"{page}: <{tag}> loads {url}")
            elif url.startswith("/") and re.search(r"\.(js|css)(\?|$)", url):
                assets.add(url)
        for marker in _CDN_MARKERS:
            if marker in html:
                offenders.append(f"{page}: mentions {marker}")
    for asset in sorted(assets):
        body = get(asset)
        if asset.split("?")[0].endswith(".css"):
            for _scheme, host in _CSS_URL.findall(body):
                if host.split(":")[0] not in (site, "127.0.0.1", "localhost"):
                    offenders.append(f"{asset}: CSS loads from {host}")
        for marker in _CDN_MARKERS:
            if marker in body:
                offenders.append(f"{asset}: contains {marker}")
    detail = f"{len(pages)} pages and {len(assets)} scripts/stylesheets fetched"
    if offenders:
        return False, detail + "\n" + "\n".join(sorted(set(offenders))[:20])
    return True, detail + "; no external fetch found"


def tls_check(cfg: Config) -> tuple[bool, str]:
    host = cfg["site"]["hostname"]
    https_port, http_port = cfg["tls"]["https_port"], cfg["tls"]["http_port"]
    notes, ok = [], True
    ctx = ssl.create_default_context()
    try:
        ctx.load_verify_locations(cafile=cfg["tls"]["cert_file"])
    except (OSError, ssl.SSLError):
        pass
    try:
        with socket.create_connection(("127.0.0.1", https_port), timeout=10) as raw:
            with ctx.wrap_socket(raw, server_hostname=host) as tls:
                cert = tls.getpeercert()
                notes.append(f"{tls.version()} handshake verified for {host}; certificate expires {cert.get('notAfter')}")
                request = (f"GET /api/method/ping HTTP/1.1\r\nHost: {host}\r\nConnection: close\r\n\r\n").encode()
                tls.sendall(request)
                data = b""
                while True:
                    chunk = tls.recv(65536)
                    if not chunk:
                        break
                    data += chunk
        head = data.split(b"\r\n\r\n", 1)[0].decode(errors="replace")
        status = head.splitlines()[0] if head else ""
        hsts = "strict-transport-security" in head.lower()
        ok &= " 200 " in status and b"pong" in data and hsts
        notes.append(f"https://{host}:{https_port}/api/method/ping -> {status}; HSTS {'present' if hsts else 'MISSING'}")
    except (OSError, ssl.SSLError) as e:
        return False, f"TLS connection to 127.0.0.1:{https_port} as {host} failed: {e}"
    try:
        with socket.create_connection(("127.0.0.1", http_port), timeout=10) as raw:
            raw.sendall(f"GET /app HTTP/1.1\r\nHost: {host}\r\nConnection: close\r\n\r\n".encode())
            head = raw.recv(4096).decode(errors="replace")
        status = head.splitlines()[0] if head else ""
        location = next((l for l in head.splitlines() if l.lower().startswith("location:")), "")
        redirect_ok = (" 301 " in status or " 308 " in status) and "https://" in location
        ok &= redirect_ok
        notes.append(f"http://{host}:{http_port}/app -> {status} {location.strip()}")
    except OSError as e:
        ok = False
        notes.append(f"plain HTTP on {http_port}: {e}")
    return ok, "\n".join(notes)


def write_report(cfg: Config, report: Report, started, explicit: str | None) -> Path:
    stamp = started.strftime("%Y%m%d-%H%M%S")
    path = Path(explicit) if explicit else cfg.install_dir / "logs" / f"readiness-{stamp}.md"
    installed = cfg.install_dir / "deploy" / "installed.json"
    release = json.loads(installed.read_text()).get("current", {}) if installed.exists() else {}
    osr = os_release()
    lines = [
        f"# Readiness report — {cfg.site}",
        "",
        f"- Generated: {started.isoformat(timespec='seconds')}",
        f"- Host: {socket.gethostname()} — {osr.get('PRETTY_NAME', platform.platform())}, {platform.machine()}, "
        f"{os.cpu_count()} CPUs",
        f"- Installed release: {release.get('bundle', 'unknown')}",
        f"- Public address: {cfg.public_url()}",
        f"- Result: **{'NOT READY' if report.failed else 'READY'}** — "
        f"{sum(1 for i in report.items if i['ok'])} passed, {len(report.failed)} failed, "
        f"{sum(1 for i in report.items if i['ok'] is None)} not applicable",
        "",
        "| | Phase | Check |",
        "|---|---|---|",
    ]
    for i in report.items:
        mark = {True: "pass", False: "**FAIL**", None: "n/a"}[i["ok"]]
        lines.append(f"| {mark} | {i['phase']} | {i['check']} |")
    lines += ["", "## Evidence", ""]
    for i in report.items:
        lines += [f"### {i['phase']}: {i['check']}", "", "```", i["evidence"] or "(none)", "```", ""]
    path.write_text("\n".join(lines))
    path.with_suffix(".json").write_text(json.dumps({"site": cfg.site, "started": started.isoformat(),
                                                     "release": release, "items": report.items}, indent=1))
    return path


# =========================================================================


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="kit.py", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("check-config", help="validate a configuration file and change nothing")
    p.add_argument("--config", required=True)
    p.add_argument("--no-file-checks", action="store_true", help="do not require certificate/secret files to exist")
    p.set_defaults(fn=cmd_check_config)

    p = sub.add_parser("render", help="write the service and proxy files for review; change nothing else")
    p.add_argument("--config", required=True)
    p.add_argument("--out", required=True)
    p.set_defaults(fn=cmd_render)

    p = sub.add_parser("install", help="fresh install from a bundle (idempotent)")
    p.add_argument("--config", required=True)
    p.add_argument("--bundle", required=True)
    p.add_argument("--no-start", action="store_true", help="install the services but do not start them")
    p.add_argument("--recreate-database", action="store_true",
                   help="allow creating the site when its database already exists (DROPS that database)")
    p.set_defaults(fn=cmd_install)

    p = sub.add_parser("upgrade", help="back up, install a new bundle, migrate, verify")
    p.add_argument("--config", required=True)
    p.add_argument("--bundle", required=True)
    p.add_argument("--force", action="store_true", help="reinstall even if this release is already installed")
    p.set_defaults(fn=cmd_upgrade)

    p = sub.add_parser("backup", help="back up the database, files and site configuration")
    p.add_argument("--config", required=True)
    p.add_argument("--label", default="manual")
    p.set_defaults(fn=cmd_backup)

    p = sub.add_parser("restore", help="restore a backup set")
    p.add_argument("--config", required=True)
    p.add_argument("--from", dest="source", required=True, help="a backup directory written by backup")
    p.add_argument("--as-site", default=None, help="restore into a new site of this name instead")
    p.add_argument("--db-name", default=None, help="with --as-site: the new site's database name")
    p.add_argument("--yes", action="store_true", help="confirm replacing the configured site's data")
    p.set_defaults(fn=cmd_restore)

    p = sub.add_parser("verify", help="acceptance checks; writes a readiness report")
    p.add_argument("--config", required=True)
    p.add_argument("--report", default=None, help="where to write the report (default: <install_dir>/logs/)")
    p.set_defaults(fn=cmd_verify)

    args = parser.parse_args(argv)
    try:
        return args.fn(args)
    except KitError as e:
        print(f"\n\033[31mFAILED: {e}\033[0m\n", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
