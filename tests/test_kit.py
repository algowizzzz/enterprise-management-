"""Tests for the deployment kit's configuration handling and templates.

The kit (deploy/kit.py) is what an operator runs on the server, with one
configuration file. These tests pin down the part that must never regress
quietly: that a bad configuration is refused with a message naming the section
and key, that no secret can be written into the file, and that the service and
proxy templates render completely. They need no services and run anywhere.

Run with:  python -m pytest tests -q
"""

import configparser
import os
import re
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "deploy"))

import kit  # noqa: E402

EXAMPLE = REPO / "deploy" / "consilium.conf.example"


def write(tmp_path, text: str) -> Path:
	path = tmp_path / "consilium.conf"
	path.write_text(text)
	return path


def example_with(tmp_path, **changes) -> Path:
	"""The shipped example, with section.key=value changes applied."""
	parser = configparser.ConfigParser(interpolation=None)
	parser.optionxform = str
	parser.read(EXAMPLE)
	for dotted, value in changes.items():
		section, key = dotted.split("__")
		if value is None:
			parser.remove_option(section, key)
		else:
			parser.set(section, key, value)
	path = tmp_path / "consilium.conf"
	with path.open("w") as fh:
		parser.write(fh)
	return path


# ---------------------------------------------------------------------------
# the example configuration
# ---------------------------------------------------------------------------


def test_the_shipped_example_is_valid(tmp_path):
	cfg = kit.Config.load(EXAMPLE, check_files=False)
	assert cfg.site == "governance.example.internal"
	assert cfg["database"]["port"] == 5432
	assert cfg["web"]["socketio"] is False
	assert cfg.public_url() == "https://governance.example.internal"


def test_sso_and_ai_are_off_by_default():
	cfg = kit.Config.load(EXAMPLE, check_files=False)
	assert cfg["sso"]["mode"] == "none"
	assert cfg["assistant"]["ai_enabled"] is False
	assert cfg["email"]["enabled"] is False


# ---------------------------------------------------------------------------
# refusals
# ---------------------------------------------------------------------------


def test_a_literal_password_is_refused(tmp_path):
	path = example_with(tmp_path, database__password="hunter2")
	with pytest.raises(kit.KitError) as e:
		kit.Config.load(path, check_files=False)
	assert "[database] password" in str(e.value)
	assert "password_file" in str(e.value)


def test_a_url_key_that_mentions_token_is_not_mistaken_for_a_secret(tmp_path):
	path = example_with(tmp_path, sso__mode="oidc")
	kit.Config.load(path, check_files=False)  # oidc_token_url must be accepted


def test_unknown_keys_and_sections_are_refused(tmp_path):
	path = example_with(tmp_path, web__thread="8")
	with pytest.raises(kit.KitError) as e:
		kit.Config.load(path, check_files=False)
	assert "[web] thread: not a known setting" in str(e.value)

	text = EXAMPLE.read_text() + "\n[extras]\nfoo = 1\n"
	with pytest.raises(kit.KitError) as e:
		kit.Config.load(write(tmp_path, text), check_files=False)
	assert "[extras] is not a known section" in str(e.value)


def test_every_problem_is_reported_at_once(tmp_path):
	path = example_with(tmp_path, web__port="eighty", database__port="70000", site__timezone="Mars/Olympus",
	                    site__admin_email="not-an-email")
	with pytest.raises(kit.KitError) as e:
		kit.Config.load(path, check_files=False)
	message = str(e.value)
	assert "4 problem(s)" in message
	for fragment in ("[web] port", "[database] port", "[site] timezone", "[site] admin_email"):
		assert fragment in message


def test_superuser_provisioning_needs_a_root_password_source(tmp_path):
	path = example_with(tmp_path, database__root_password_file=None)
	with pytest.raises(kit.KitError) as e:
		kit.Config.load(path, check_files=False)
	assert "provisioning = superuser needs root_password_file" in str(e.value)

	path = example_with(tmp_path, database__root_password_file=None, database__provisioning="provisioned")
	kit.Config.load(path, check_files=False)


def test_one_redis_for_cache_and_queue_is_refused(tmp_path):
	path = example_with(tmp_path, redis__queue_url="redis://127.0.0.1:6379/0")
	with pytest.raises(kit.KitError) as e:
		kit.Config.load(path, check_files=False)
	assert "cache_url and queue_url must differ" in str(e.value)


def test_backups_inside_the_install_directory_are_refused(tmp_path):
	path = example_with(tmp_path, backup__dir="/opt/consilium/backups")
	with pytest.raises(kit.KitError) as e:
		kit.Config.load(path, check_files=False)
	assert "[backup] dir must be outside" in str(e.value)


def test_oidc_needs_its_endpoints_and_a_secret(tmp_path):
	path = example_with(tmp_path, sso__mode="oidc", sso__oidc_token_url="", sso__oidc_client_secret_file=None)
	with pytest.raises(kit.KitError) as e:
		kit.Config.load(path, check_files=False)
	assert "oidc_token_url is required when mode = oidc" in str(e.value)
	assert "oidc_client_secret_file or oidc_client_secret_env is required" in str(e.value)


def test_ldap_search_filter_must_take_the_sign_in_name(tmp_path):
	path = example_with(tmp_path, sso__mode="ldap", sso__ldap_search_filter="(uid=someone)")
	with pytest.raises(kit.KitError) as e:
		kit.Config.load(path, check_files=False)
	assert "must contain {0}" in str(e.value)


def test_a_world_readable_secret_file_is_refused(tmp_path):
	secret = tmp_path / "db_password"
	secret.write_text("s3cret\n")
	os.chmod(secret, 0o644)
	cert, key = tmp_path / "c.crt", tmp_path / "c.key"
	cert.write_text("x")
	key.write_text("x")
	path = example_with(tmp_path, database__password_file=str(secret), tls__cert_file=str(cert),
	                    tls__key_file=str(key), database__provisioning="provisioned",
	                    database__root_password_file=None, site__admin_password_file=None)
	with pytest.raises(kit.KitError) as e:
		kit.Config.load(path, check_files=True)
	assert "readable by every user" in str(e.value)
	os.chmod(secret, 0o600)
	cfg = kit.Config.load(path, check_files=True)
	assert cfg.secret("database", "password") == "s3cret"


def test_a_secret_can_come_from_the_environment(tmp_path, monkeypatch):
	path = example_with(tmp_path, database__password_file=None, database__password_env="CONSILIUM_TEST_DBPW")
	cfg = kit.Config.load(path, check_files=False)
	monkeypatch.delenv("CONSILIUM_TEST_DBPW", raising=False)
	with pytest.raises(kit.KitError):
		cfg.secret("database", "password")
	monkeypatch.setenv("CONSILIUM_TEST_DBPW", "from-env")
	assert cfg.secret("database", "password") == "from-env"


# ---------------------------------------------------------------------------
# templates
# ---------------------------------------------------------------------------


def render(tmp_path, **changes):
	cfg = kit.Config.load(example_with(tmp_path, **changes), check_files=False)
	out = tmp_path / "rendered"
	return cfg, {p.relative_to(out).as_posix(): p.read_text() for p in kit.render_templates(cfg, out)}


def test_templates_render_completely(tmp_path):
	cfg, files = render(tmp_path)
	assert "nginx/consilium.conf" in files
	assert {"systemd/consilium-web.service", "systemd/consilium-worker@.service",
	        "systemd/consilium-scheduler.service", "systemd/consilium.target",
	        "systemd/consilium-backup.timer"} <= set(files)
	for name, text in files.items():
		assert not re.search(r"@[A-Z_]+@", text), f"{name} has an unfilled placeholder"
	assert "--site governance.example.internal" in files["systemd/consilium-web.service"]
	assert "OnCalendar=*-*-* 02:30:00" in files["systemd/consilium-backup.timer"]


def _unit(text: str) -> configparser.ConfigParser:
	parser = configparser.ConfigParser(strict=False, interpolation=None)
	parser.optionxform = str
	parser.read_string(text)
	return parser


def test_units_run_as_the_service_account_with_least_privilege(tmp_path):
	_, files = render(tmp_path)
	for name in ("consilium-web.service", "consilium-worker@.service", "consilium-scheduler.service"):
		unit = _unit(files[f"systemd/{name}"])
		service = unit["Service"]
		assert service["User"] == "consilium"
		assert service["NoNewPrivileges"] == "yes"
		assert service["ProtectSystem"] == "full"
		assert service["ReadWritePaths"] == "/opt/consilium"
		assert service["ExecStart"].startswith("/opt/consilium/env/bin/python -m winbench.cli ")
		assert service["Restart"] == "always"
		assert unit["Install"]["WantedBy"] == "consilium.target"


def test_the_web_server_listens_on_loopback_behind_the_proxy(tmp_path):
	_, files = render(tmp_path)
	exec_start = _unit(files["systemd/consilium-web.service"])["Service"]["ExecStart"]
	assert "--host 127.0.0.1" in exec_start and "--proxy" in exec_start
	nginx = files["nginx/consilium.conf"]
	assert "server 127.0.0.1:8000;" in nginx
	assert "ssl_protocols TLSv1.2 TLSv1.3;" in nginx
	assert "Strict-Transport-Security" in nginx
	assert "return 301 https://$host$request_uri;" in nginx


def test_the_scheduler_is_a_single_unit_not_a_template(tmp_path):
	_, files = render(tmp_path)
	assert not any("scheduler@" in name for name in files)


def test_socketio_blocks_appear_only_when_enabled(tmp_path):
	_, off = render(tmp_path)
	assert "/socket.io" not in off["nginx/consilium.conf"]
	_, on = render(tmp_path, web__socketio="yes")
	assert "location /socket.io" in on["nginx/consilium.conf"]


def test_a_non_standard_https_port_is_kept_in_redirects(tmp_path):
	_, files = render(tmp_path, tls__https_port="8443")
	assert "return 301 https://$host:8443$request_uri;" in files["nginx/consilium.conf"]


def test_caddy_template_never_asks_a_public_ca(tmp_path):
	_, files = render(tmp_path, tls__proxy="caddy")
	caddy = files["caddy/consilium.caddy"]
	assert "tls /etc/pki/tls/certs/governance.example.internal.crt" in caddy
	assert "acme" not in caddy.lower().replace("# ", "")


# ---------------------------------------------------------------------------
# small pieces
# ---------------------------------------------------------------------------


def test_pip_network_evidence_ignores_pips_own_ignoring_indexes_line(tmp_path):
	log = tmp_path / "pip.log"
	log.write_text("2026 Ignoring indexes: https://pypi.org/simple\n"
	               "2026 Looking in links: /opt/b/wheelhouse\n")
	assert kit.network_lines(log) == []
	log.write_text(log.read_text() + "2026 Downloading https://files.example/x.whl\n")
	assert len(kit.network_lines(log)) == 1


def test_commands_redact_secrets_in_logs():
	assert kit._redact(["new-site", "--db-password", "p", "--admin-password", "a", "--db-name", "x"]) == [
		"new-site", "--db-password", "********", "--admin-password", "********", "--db-name", "x"]


def test_machine_names_are_normalised():
	assert kit._normalise_machine("AMD64") == "x86_64"
	assert kit._normalise_machine("arm64") == "aarch64"
