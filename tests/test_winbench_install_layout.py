"""Tests for winbench on an installation made from the offline bundle.

A development bench keeps each app under ``apps/<app>/<app>``. An installation
made by the deployment kit installs every app as a wheel into the environment's
site-packages, and ``apps/`` holds nothing. These tests pin down the places
where winbench used to assume the first layout, and ``winbench doctor``'s
report on a platform that needs no compatibility patches. They need no
services and no framework.

Run with:  python -m pytest tests -q
"""

import json
import os
import sys
import tarfile
import types
from pathlib import Path

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "winbench"))

from winbench import cli, compat, services  # noqa: E402
from winbench.layout import Bench  # noqa: E402


@pytest.fixture
def wheel_install(tmp_path, monkeypatch):
	"""A bench whose apps are packages in a site-packages directory."""
	site_packages = tmp_path / "env" / "site-packages"
	for app in ("fakeframework", "fakeapp"):
		(site_packages / app / "public").mkdir(parents=True)
		(site_packages / app / "__init__.py").write_text("")
	monkeypatch.syspath_prepend(str(site_packages))
	for app in ("fakeframework", "fakeapp"):
		sys.modules.pop(app, None)
	bench = Bench(tmp_path / "bench")
	bench.ensure_dirs()
	bench.apps_txt.write_text("fakeframework\nfakeapp\n")
	return bench, site_packages


def test_app_paths_follow_the_installed_package(wheel_install):
	bench, site_packages = wheel_install
	assert cli._app_module_dir(bench, "fakeapp") == (site_packages / "fakeapp").resolve()
	assert cli._app_public_dir(bench, "fakeapp") == (site_packages / "fakeapp" / "public").resolve()
	# The framework serves /assets/<app>/node_modules from <package>/../node_modules.
	assert cli._app_node_modules_dir(bench, "fakeapp") == site_packages.resolve() / "node_modules"


def test_app_paths_fall_back_to_the_bench_layout(tmp_path):
	bench = Bench(tmp_path)
	assert cli._app_public_dir(bench, "no_such_app_anywhere") == tmp_path.resolve() / "apps" / \
		"no_such_app_anywhere" / "no_such_app_anywhere" / "public"


def test_asset_import_lands_where_the_framework_serves_from(wheel_install, tmp_path):
	"""Before: 'skipping fakeframework: not installed in this bench', and a blank desk."""
	bench, site_packages = wheel_install
	staging = tmp_path / "stage"
	(staging / "apps" / "fakeframework" / "dist" / "js").mkdir(parents=True)
	(staging / "apps" / "fakeframework" / "dist" / "js" / "desk.bundle.js").write_text("// desk")
	(staging / "apps" / "fakeframework" / "node_modules" / "ace-builds" / "src-min-noconflict").mkdir(parents=True)
	(staging / "apps" / "fakeframework" / "node_modules" / "ace-builds" / "src-min-noconflict" / "ace.js").write_text("//")
	(staging / "sites").mkdir()
	(staging / "sites" / "assets.json").write_text("{}")
	archive = tmp_path / "assets.tar.gz"
	with tarfile.open(archive, "w:gz") as tar:
		tar.add(staging / "apps", arcname="apps")
		tar.add(staging / "sites", arcname="sites")

	cli._import_assets(bench, archive)

	assert (site_packages / "fakeframework" / "public" / "dist" / "js" / "desk.bundle.js").is_file()
	node_modules = site_packages / "node_modules" / "ace-builds"
	assert (node_modules / "src-min-noconflict" / "ace.js").is_file()
	# the unminified name the desk asks for in developer mode
	assert (node_modules / "src-noconflict" / "ace.js").is_file()
	assert (bench.sites_dir / "assets" / "assets.json").is_file()


def test_shared_node_modules_are_served_for_every_app(wheel_install, monkeypatch):
	"""The framework's map is keyed by source, so apps sharing site-packages
	overwrite each other and only the last app's libraries are served."""
	bench, site_packages = wheel_install
	(site_packages / "node_modules" / "ace-builds").mkdir(parents=True)
	(site_packages / "node_modules" / "ace-builds" / "ace.js").write_text("//")
	for app in ("fakeframework", "fakeapp"):
		(bench.sites_dir / "assets" / app).mkdir(parents=True)
	# as frappe.build.make_asset_dirs leaves it: only the last app got them
	(bench.sites_dir / "assets" / "fakeapp" / "node_modules").mkdir()

	copied = []

	def link_assets_dir(source, target, hard_link=False):
		copied.append((source, target, hard_link))
		Path(target).mkdir(parents=True)

	fake_build = types.ModuleType("frappe.build")
	fake_build.link_assets_dir = link_assets_dir
	monkeypatch.setitem(sys.modules, "frappe", types.ModuleType("frappe"))
	monkeypatch.setitem(sys.modules, "frappe.build", fake_build)

	cli._serve_shared_node_modules(bench, use_copy=True)

	assert copied == [(str(site_packages.resolve() / "node_modules"),
	                   str(bench.sites_dir / "assets" / "fakeframework" / "node_modules"), True)]


# ---------------------------------------------------------------------------
# doctor
# ---------------------------------------------------------------------------


def test_doctor_checks_the_database_as_the_site_role_when_no_superuser_is_kept(monkeypatch):
	seen = {}

	def fake_check_postgres(host, port, user, password, dbname="postgres"):
		seen.update(host=host, port=port, user=user, password=password, dbname=dbname)
		return services.Check("postgres", True, "PostgreSQL 16")

	monkeypatch.setattr(services, "check_postgres", fake_check_postgres)
	monkeypatch.setattr(services, "check_redis", lambda url, label: services.Check(label, True, url))
	checks = services.run_all({"db_host": "db", "db_port": 5432},
	                          {"db_name": "consilium", "db_password": "pw"})
	assert seen == {"host": "db", "port": 5432, "user": "consilium", "password": "pw", "dbname": "consilium"}
	assert "(as the site's own role)" in checks[0].detail

	services.run_all({"db_host": "db", "root_login": "postgres", "root_password": "root"},
	                 {"db_name": "consilium", "db_password": "pw"})
	assert seen["user"] == "postgres" and seen["dbname"] == "postgres"


def test_doctor_on_posix_reports_no_patches_needed(tmp_path, monkeypatch):
	"""HANDOVER §6 Phase 3's criterion, which force-installing the patches for
	the report used to hide: every patch was listed as 'applied'."""
	from click.testing import CliRunner

	bench = Bench(tmp_path)
	bench.ensure_dirs()
	bench.apps_txt.write_text("frappe\n")
	bench.write_common_config({"db_host": "127.0.0.1"})
	(bench.sites_dir / "site.test").mkdir()
	(bench.sites_dir / "site.test" / "site_config.json").write_text(json.dumps({"db_name": "x"}))
	monkeypatch.setenv("FRAPPE_BENCH_ROOT", str(tmp_path))
	monkeypatch.setattr(compat, "IS_WINDOWS", False)
	monkeypatch.setattr(services, "run_all", lambda common, site=None: [services.Check("postgres", True, "ok")])

	def fake_install(force=False):
		if force:
			compat.APPLIED[:] = ["frappe._register_fault_handler", "frappe.build.symlink"]
		return compat.APPLIED

	monkeypatch.setattr(compat, "install", fake_install)
	monkeypatch.setattr(compat, "APPLIED", [])
	monkeypatch.setattr(compat, "SKIPPED", [])

	result = CliRunner().invoke(cli.main, ["doctor"])
	assert result.exit_code == 0, result.output
	assert "(none needed on this platform)" in result.output
	assert "applied  frappe" not in result.output
	assert "2 Windows patches install cleanly" in result.output
