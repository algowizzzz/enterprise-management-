"""The `winbench` command line.

Command mapping against upstream `bench`:

    bench init                   -> winbench init
    bench new-site               -> winbench new-site      (Postgres only)
    bench --site X migrate       -> winbench migrate
    bench build                  -> winbench build
    bench start                  -> winbench start         (no Procfile/supervisor)
    bench serve                  -> winbench serve         (waitress, not gunicorn)
    bench worker                 -> winbench worker        (SimpleWorker, no fork)
    bench schedule               -> winbench scheduler
    bench --site X console       -> winbench console
    bench --site X backup        -> winbench backup
    bench setup supervisor/nginx -> (deleted; see deploy/service/ and deploy/kit.py)
    bench doctor                 -> winbench doctor        (checks + compat report)
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import click

from winbench import __version__
from winbench.layout import Bench, BenchNotFound, find_bench

DEFAULT_COMMON_CONFIG = {
	"db_type": "postgres",
	"db_host": "127.0.0.1",
	"db_port": 5432,
	"root_login": "postgres",
	"redis_cache": "redis://127.0.0.1:13000",
	"redis_queue": "redis://127.0.0.1:11000",
	"redis_socketio": "redis://127.0.0.1:11000",
	"socketio_port": 9000,
	"webserver_port": 8000,
	"developer_mode": 0,
}


def _bench_or_exit() -> Bench:
	try:
		return find_bench()
	except BenchNotFound as e:
		raise click.ClickException(str(e)) from e


def _frappe_cli(bench: Bench, site: str | None, args: list[str]) -> int:
	"""Invoke frappe's own click app, which needs no bench and no POSIX shell."""
	cmd = [bench.python, "-m", "frappe.utils.bench_helper", "frappe"]
	if site:
		cmd += ["--site", site]
	cmd += args
	env = {**os.environ, "FRAPPE_BENCH_ROOT": str(bench.root)}
	return subprocess.call(cmd, cwd=str(bench.sites_dir), env=env)


def _resolve_site(bench: Bench, site: str | None) -> str:
	if site:
		return site
	if env_site := os.environ.get("FRAPPE_SITE"):
		return env_site
	sites = bench.sites()
	if len(sites) == 1:
		return sites[0]
	if not sites:
		raise click.ClickException("No sites in this bench. Run `winbench new-site <name>` first.")
	raise click.ClickException(
		f"This bench has several sites ({', '.join(sites)}); pass --site explicitly."
	)


@click.group(context_settings={"help_option_names": ["-h", "--help"]})
@click.version_option(__version__, prog_name="winbench")
def main():
	"""Run Frappe on Windows: Postgres, waitress, no supervisor, no nginx."""


# ---------------------------------------------------------------------------
# bench lifecycle
# ---------------------------------------------------------------------------


def _install_app_from_archive(archive: Path, destination: Path) -> None:
	"""Unpack a GitHub source archive (or a directory) into ``destination``.

	This is the path for networks where `git clone` is blocked but a browser
	download is not -- the "Download ZIP" button, or
	``github.com/frappe/frappe/archive/refs/heads/version-15.zip``.

	GitHub archives wrap everything in a single top-level directory
	(``frappe-version-15/``), which we strip so that ``apps/frappe`` is the app
	itself rather than ``apps/frappe/frappe-version-15``.

	Frappe builds with flit, which reads its version from ``frappe/__init__.py``
	rather than from git metadata, so an archive with no ``.git`` installs and
	runs normally. The only loss is cosmetic: the About dialog shows an empty
	branch and commit, because `frappe.utils.change_log` shells out to git.
	"""
	import shutil
	import tempfile

	archive = Path(archive).expanduser().resolve()
	if not archive.exists():
		raise click.ClickException(f"No such archive or directory: {archive}")

	if archive.is_dir():
		click.echo(f"Copying {archive} -> {destination}")
		shutil.copytree(archive, destination)
		return

	click.echo(f"Unpacking {archive.name} -> {destination}")
	with tempfile.TemporaryDirectory() as staging:
		try:
			shutil.unpack_archive(str(archive), staging)
		except (ValueError, OSError) as e:
			raise click.ClickException(f"Could not unpack {archive.name}: {e}") from e

		entries = [p for p in Path(staging).iterdir() if not p.name.startswith(".")]
		# Strip GitHub's single wrapper directory, but only if that is what it is.
		root = entries[0] if len(entries) == 1 and entries[0].is_dir() else Path(staging)

		if not (root / "frappe" / "__init__.py").exists():
			raise click.ClickException(
				f"{archive.name} does not look like a frappe source tree "
				f"(no frappe/__init__.py under {root.name})"
			)

		destination.parent.mkdir(parents=True, exist_ok=True)
		shutil.move(str(root), str(destination))


@main.command()
@click.argument("path", type=click.Path())
@click.option("--frappe-branch", default="version-15", show_default=True)
@click.option("--frappe-repo", default="https://github.com/frappe/frappe.git", show_default=True)
@click.option(
	"--from-archive",
	type=click.Path(),
	default=None,
	help="Install frappe from a downloaded .zip/.tar.gz (or an extracted directory) "
	"instead of cloning. Use this where git is blocked but downloads are not.",
)
@click.option("--skip-clone", is_flag=True, help="Assume apps/frappe is already present.")
@click.option("--skip-install", is_flag=True, help="Create the venv but do not pip install.")
@click.option(
	"--find-links",
	default=None,
	help="Directory of pre-downloaded wheels; implies --no-index for a fully offline install.",
)
def init(path, frappe_branch, frappe_repo, from_archive, skip_clone, skip_install, find_links):
	"""Create a new bench directory with a venv and the frappe app."""
	bench = Bench(Path(path))
	bench.ensure_dirs()

	frappe_dir = bench.apps_dir / "frappe"
	if frappe_dir.exists():
		click.echo(f"apps/frappe already present at {frappe_dir}")
	elif from_archive:
		_install_app_from_archive(Path(from_archive), frappe_dir)
	elif not skip_clone:
		click.echo(f"Cloning {frappe_repo} @ {frappe_branch}")
		rc = subprocess.call(
			["git", "clone", "--depth", "1", "--branch", frappe_branch, frappe_repo, str(frappe_dir)]
		)
		if rc:
			raise click.ClickException("git clone failed")

	if not bench.env_dir.exists():
		click.echo("Creating virtualenv")
		rc = subprocess.call([sys.executable, "-m", "venv", str(bench.env_dir)])
		if rc:
			raise click.ClickException("venv creation failed")

	if not skip_install:
		click.echo("Installing frappe (this takes a few minutes)")
		# Offline mode: resolve everything from a wheelhouse instead of PyPI.
		offline = ["--no-index", "--find-links", find_links] if find_links else []

		def pip(*args):
			subprocess.check_call([bench.python, "-m", "pip", "install", *offline, *args])

		pip("--upgrade", "pip", "wheel")
		# flit_core is frappe's build backend. pip normally fetches it on the fly,
		# which fails with --no-index unless it is in the wheelhouse.
		pip("flit_core")

		if find_links:
			# frappe's pyproject pins two dependencies to GitHub URLs:
			#   PyPika @ git+https://github.com/frappe/pypika@2c50e61...
			#   gunicorn @ git+https://github.com/frappe/gunicorn@bb55405...
			# pip honours a direct reference even under --no-index, so letting it
			# resolve frappe's dependencies would silently phone GitHub and defeat
			# the whole point of the wheelhouse. Install the dependency set from
			# the wheelhouse first, then frappe itself with --no-deps.
			#
			# The wheelhouse MUST carry frappe's PyPika *fork*, not PyPI's PyPika:
			# both report version 0.48.9, but the fork rewrites ~850 lines across
			# terms.py, queries.py and dialects.py -- the modules frappe uses most.
			requirements = Path(__file__).resolve().parents[2] / "requirements" / "frappe-full.txt"
			if requirements.exists():
				pip("-r", str(requirements))
			else:
				click.echo(f"  note: {requirements} not found; installing deps from the wheelhouse only")
			pip("--no-deps", "--no-build-isolation", "-e", str(frappe_dir))
		else:
			# Editable, deliberately: a copied install puts the package in
			# site-packages without package.json, and `winbench build` then cannot
			# find the esbuild config.
			pip("--no-build-isolation", "-e", str(frappe_dir))

		pip("waitress")

		# winbench must live in the *bench* venv, not just the one that ran
		# `winbench init`: `winbench serve` imports frappe in-process, so the two
		# have to share an interpreter. Installed from this source tree, so it
		# works offline with no index at all.
		winbench_src = Path(__file__).resolve().parents[1]
		if (winbench_src / "pyproject.toml").exists():
			subprocess.check_call(
				[bench.python, "-m", "pip", "install", "--no-deps", "-e", str(winbench_src)]
			)
		else:
			click.echo("  note: could not locate the winbench source; install it into env/ yourself")

	bench.add_app("frappe")
	if not bench.common_site_config.exists():
		bench.write_common_config(dict(DEFAULT_COMMON_CONFIG))
	bench.write_winbench_config({"version": __version__, "web_workers": 1, "background_workers": 2})

	click.echo(f"\nBench ready at {bench.root}")
	click.echo("Next: winbench doctor, then winbench new-site <name>")


@main.command("new-site")
@click.argument("site")
@click.option("--admin-password", prompt=True, hide_input=True)
@click.option("--db-root-username", default=None)
@click.option("--db-root-password", default=None)
@click.option("--db-name", default=None)
@click.option("--install-app", multiple=True)
def new_site(site, admin_password, db_root_username, db_root_password, db_name, install_app):
	"""Create a site backed by PostgreSQL."""
	bench = _bench_or_exit()
	common = bench.read_common_config()

	args = [
		"new-site",
		site,
		"--db-type",
		"postgres",
		"--db-host",
		str(common.get("db_host", "127.0.0.1")),
		"--db-port",
		str(common.get("db_port", 5432)),
		"--db-root-username",
		db_root_username or common.get("root_login", "postgres"),
		"--db-root-password",
		db_root_password or common.get("root_password", ""),
		"--admin-password",
		admin_password,
	]
	if db_name:
		args += ["--db-name", db_name]
	for app in install_app:
		args += ["--install-app", app]

	sys.exit(_frappe_cli(bench, None, args))


@main.command()
@click.option("--site", default=None)
def migrate(site):
	"""Run pending patches and sync doctype schemas."""
	bench = _bench_or_exit()
	sys.exit(_frappe_cli(bench, _resolve_site(bench, site), ["migrate"]))


@main.command()
@click.option("--app", default=None)
@click.option("--production", is_flag=True)
def build(app, production):
	"""Compile JS/CSS with esbuild (node must be on PATH)."""
	bench = _bench_or_exit()
	args = ["build"]
	if app:
		args += ["--app", app]
	if production:
		args.append("--production")
	sys.exit(_frappe_cli(bench, None, args))


@main.command()
@click.option("--site", default=None)
def backup(site):
	"""Take a database + files backup (pg_dump under the hood)."""
	bench = _bench_or_exit()
	sys.exit(_frappe_cli(bench, _resolve_site(bench, site), ["backup", "--with-files"]))


@main.command()
@click.option("--site", default=None)
def console(site):
	"""Open an IPython console bound to the site."""
	bench = _bench_or_exit()
	sys.exit(_frappe_cli(bench, _resolve_site(bench, site), ["console"]))


# ---------------------------------------------------------------------------
# running
# ---------------------------------------------------------------------------


@main.command()
@click.option("--site", default=None)
@click.option("--port", default=None, type=int)
@click.option("--host", default="127.0.0.1", show_default=True)
@click.option("--threads", default=8, show_default=True)
@click.option(
	"--no-statics",
	is_flag=True,
	help="Do not serve /assets and /files from this process (use when a reverse proxy does it).",
)
@click.option("--proxy", is_flag=True, help="Trust X-Forwarded-* headers (behind IIS/Caddy/ALB).")
def serve(site, port, host, threads, no_statics, proxy):
	"""Serve the WSGI app with waitress (the gunicorn replacement).

	By default this also serves ``/assets`` and ``/files``, which on a Linux
	bench is nginx's job. Without it the Desk loads its HTML and then 404s on
	every JS/CSS bundle, leaving a blank page -- so statics are on unless a real
	reverse proxy is in front.
	"""
	from winbench.compat import install as install_compat

	bench = _bench_or_exit()
	site = _resolve_site(bench, site)
	port = port or int(bench.read_common_config().get("webserver_port", 8000))

	os.chdir(bench.sites_dir)
	os.environ.setdefault("FRAPPE_SITE", site)
	os.environ.setdefault("FRAPPE_BENCH_ROOT", str(bench.root))

	install_compat()

	import frappe.app as frappe_app
	from waitress import serve as waitress_serve

	# frappe.app keeps the sites path in a module global that the statics
	# middleware reads; it defaults to "." and we have already chdir'd there.
	frappe_app._site = site
	frappe_app._sites_path = str(bench.sites_dir)

	app = frappe_app.application
	if not no_statics:
		app = frappe_app.application_with_statics()
	if proxy:
		from werkzeug.middleware.proxy_fix import ProxyFix

		app = ProxyFix(app, x_for=1, x_proto=1, x_host=1, x_port=1, x_prefix=1)

	statics = "no" if no_statics else "yes"
	click.echo(
		f"Serving {site} on http://{host}:{port} "
		f"({threads} threads, waitress, statics={statics})"
	)
	waitress_serve(app, host=host, port=port, threads=threads)


@main.command()
@click.option("--queue", default=None, help="Comma-separated queues, e.g. short,default,long")
@click.option("--site", default=None)
@click.option("--burst", is_flag=True, help="Drain the queue and exit.")
@click.option("--quiet", is_flag=True)
def worker(queue, site, burst, quiet):
	"""Run a background worker without os.fork()."""
	bench = _bench_or_exit()
	os.chdir(bench.sites_dir)
	os.environ.setdefault("FRAPPE_BENCH_ROOT", str(bench.root))

	from winbench import worker as worker_mod

	worker_mod.start(queue=queue, quiet=quiet, burst=burst, site=site)


@main.command()
@click.option("--site", default=None)
def scheduler(site):
	"""Run the scheduler loop as its own process."""
	from winbench.compat import install as install_compat

	bench = _bench_or_exit()
	os.chdir(bench.sites_dir)
	os.environ.setdefault("FRAPPE_BENCH_ROOT", str(bench.root))

	install_compat()

	from frappe.utils.scheduler import start_scheduler

	click.echo("Scheduler started (Ctrl+C to stop)")
	start_scheduler()


@main.command()
@click.option("--export", "export_to", type=click.Path(), default=None,
              help="Write the built assets to a portable .tar.gz for another machine.")
@click.option("--import", "import_from", type=click.Path(), default=None,
              help="Unpack an assets bundle produced by --export, then relink.")
@click.option("--copy", "use_copy", is_flag=True,
              help="Copy assets into sites/assets instead of linking. Safer on Windows.")
@click.option("--with-sourcemaps", is_flag=True,
              help="Include .js.map files in an export. They are ~75%% of the bytes and "
                   "are only read by browser devtools, so they are excluded by default.")
def assets(export_to, import_from, use_copy, with_sourcemaps):
	"""Link, export or import built assets -- without running node.

	`winbench build` needs node and yarn. On a locked-down laptop yarn is often
	the first thing that fails: the npm registry is blocked, the corporate proxy
	breaks TLS, or `air-datepicker` (the one frappe dependency served from
	GitHub rather than the npm registry) is refused.

	None of that has to block you. Assets are static build output -- compile them
	once on any machine that has node, and move them. The runtime never needs
	node or yarn.

	    # on a machine with node
	    winbench build --production
	    winbench assets --export frappe-assets.tar.gz

	    # on the locked-down laptop -- no node required
	    winbench assets --import frappe-assets.tar.gz --copy

	Bundles are ~5 MB gzipped.
	"""
	from winbench.compat import install as install_compat

	bench = _bench_or_exit()
	os.chdir(bench.sites_dir)
	os.environ.setdefault("FRAPPE_BENCH_ROOT", str(bench.root))
	install_compat()

	import frappe

	frappe.init("")

	if import_from:
		_import_assets(bench, Path(import_from))
	if export_to:
		_export_assets(bench, Path(export_to), with_sourcemaps=with_sourcemaps)
		return

	_relink_assets(use_copy, bench)


# The build output each app keeps, relative to the app's package directory.
# `sites/assets/<app>` is only a link to this -- the real bytes live here.
_ASSET_SUBDIR = "public"


def _app_module_dir(bench: Bench, app: str) -> Path:
	"""Where the app's Python package actually is.

	On a development bench that is ``apps/<app>/<app>``. On an installation from
	the offline bundle the app is a wheel in the environment's site-packages and
	``apps/`` holds nothing, so the conventional path points nowhere and the
	framework's compiled assets would be skipped as "not installed in this
	bench". The framework itself locates an app's public directory (and its
	``node_modules``, one level up) from the imported module, so do the same:
	both layouts then resolve to the place the framework will serve from.
	"""
	import importlib.util

	try:
		spec = importlib.util.find_spec(app)
	except (ImportError, ValueError):
		spec = None
	if spec and spec.origin:
		return Path(spec.origin).resolve().parent
	return bench.apps_dir / app / app


def _app_public_dir(bench: Bench, app: str) -> Path:
	return _app_module_dir(bench, app) / _ASSET_SUBDIR


def _app_node_modules_dir(bench: Bench, app: str) -> Path:
	# frappe.build.generate_assets_map links /assets/<app>/node_modules from
	# here: the directory above the package.
	return _app_module_dir(bench, app).parent / "node_modules"


# Libraries the desk does not bundle but fetches from
# /assets/<app>/node_modules/... the first time a screen needs them: the code
# editor behind every JSON and Code field, the Gantt view, the barcode scanner
# and direct printing. `dist/` alone leaves them out, and the failure is quiet --
# the field renders, the script request 404s, and the console fills with
# "Unexpected token '<'" while nothing on the page says why. Only these paths are
# carried, not node_modules wholesale, which would be hundreds of megabytes.
_RUNTIME_NODE_MODULES = (
	"ace-builds/src-min-noconflict",
	"ace-builds/LICENSE",
	"frappe-gantt/dist/frappe-gantt.css",
	"frappe-gantt/dist/frappe-gantt.min.js",
	"frappe-gantt/license.txt",
	"html5-qrcode/html5-qrcode.min.js",
	"html5-qrcode/LICENSE",
	"qz-tray/qz-tray.js",
	"qz-tray/package.json",  # its licence (LGPL-2.1) is declared only here
	"js-sha256/build/sha256.min.js",
	"js-sha256/LICENSE.txt",
)

# The desk asks for the unminified editor in developer mode and the minified one
# otherwise. The two behave identically, so the bundle carries one and the
# import supplies it under both names rather than doubling the archive.
_NODE_MODULE_ALIASES = {"ace-builds/src-noconflict": "ace-builds/src-min-noconflict"}


def _relink_assets(use_copy: bool, bench: Bench | None = None) -> None:
	"""Recreate sites/assets/<app> from the local apps directory.

	This is what `winbench build` does after compiling -- pulled out so it can
	run on its own, with no node involved.
	"""
	import frappe.build

	frappe.build.setup()
	frappe.build.make_asset_dirs(hard_link=use_copy)
	_serve_shared_node_modules(bench or find_bench(), use_copy)


def _serve_shared_node_modules(bench: Bench, use_copy: bool) -> None:
	"""Serve runtime libraries for every app, when apps share one node_modules.

	The framework maps ``<package>/../node_modules`` to
	``sites/assets/<app>/node_modules``, in a dict keyed by the *source*. On a
	development bench every app has its own directory, so every app gets its
	own entry. Installed from wheels, every app's package sits in the same
	site-packages, so they all name the same source, each overwrites the one
	before, and only the last app listed gets its libraries served -- never the
	framework, whose desk is the one that asks for them. The code editor then
	fails to load in every JSON and Code field. So give each app that lacks the
	directory a copy (or a link) of it.
	"""
	from frappe.build import link_assets_dir

	for app in bench.apps():
		source = _app_node_modules_dir(bench, app)
		target = bench.sites_dir / "assets" / app / "node_modules"
		if source.is_dir() and not target.exists() and target.parent.is_dir():
			link_assets_dir(str(source), str(target), hard_link=use_copy)


def _export_assets(bench: Bench, destination: Path, with_sourcemaps: bool = False) -> None:
	"""Bundle built assets into a portable archive.

	Symlinks are *dereferenced* deliberately. `sites/assets/<app>` points into
	this bench's `apps/` directory, so an archive that preserved the link would
	arrive on the target machine pointing at a path that does not exist there --
	a bundle that looks fine and serves nothing.

	Source maps are excluded unless asked for: they are roughly three quarters of
	the bytes and are only ever fetched by browser devtools, never by the running
	application.
	"""
	import tarfile

	destination = destination.expanduser().resolve()
	destination.parent.mkdir(parents=True, exist_ok=True)

	members: list[tuple[Path, str]] = []
	for app in bench.apps():
		dist = _app_public_dir(bench, app) / "dist"
		if dist.is_dir():
			members.append((dist, f"apps/{app}/dist"))
		else:
			click.echo(f"  note: {app} has no built dist/ -- run `winbench build --production` first")
		node_modules = _app_node_modules_dir(bench, app)
		for rel in _RUNTIME_NODE_MODULES:
			if (node_modules / rel).exists():
				members.append((node_modules / rel, f"apps/{app}/node_modules/{rel}"))

	# The manifests and the shared css/js/locale trees live under sites/assets.
	for name in ("assets.json", "assets-rtl.json", "css", "js", "locale"):
		path = bench.sites_dir / "assets" / name
		if path.exists():
			members.append((path, f"sites/{name}"))

	if not members:
		raise click.ClickException("Nothing to export -- run `winbench build --production` first.")

	def _keep(info: "tarfile.TarInfo"):
		if not with_sourcemaps and info.name.endswith(".map"):
			return None
		return info

	with tarfile.open(destination, "w:gz", dereference=True) as archive:
		for source, arcname in members:
			archive.add(str(source), arcname=arcname, filter=_keep)

	size_mb = destination.stat().st_size / (1024 * 1024)
	maps = "with" if with_sourcemaps else "without"
	click.echo(f"Wrote {destination} ({size_mb:.1f} MB, {maps} source maps)")
	click.echo("On the target machine: winbench assets --import <this file> --copy")


def _import_assets(bench: Bench, archive_path: Path) -> None:
	import shutil
	import tarfile
	import tempfile

	archive_path = archive_path.expanduser().resolve()
	if not archive_path.exists():
		raise click.ClickException(f"No such bundle: {archive_path}")

	click.echo(f"Unpacking {archive_path.name}")
	with tempfile.TemporaryDirectory() as staging:
		with tarfile.open(archive_path, "r:gz") as archive:
			for member in archive.getmembers():
				_assert_safe_member(member.name)
				archive.extract(member, path=staging)

		staged = Path(staging)

		for app_dir in (staged / "apps").iterdir() if (staged / "apps").is_dir() else []:
			target = _app_public_dir(bench, app_dir.name) / "dist"
			if not target.parent.is_dir():
				click.echo(f"  skipping {app_dir.name}: not installed in this bench")
				continue
			if target.exists():
				shutil.rmtree(target)
			shutil.copytree(app_dir / "dist" if (app_dir / "dist").is_dir() else app_dir, target)
			click.echo(f"  {app_dir.name} -> {target}")
			_import_node_modules(app_dir / "node_modules", _app_node_modules_dir(bench, app_dir.name))

		sites_assets = bench.sites_dir / "assets"
		sites_assets.mkdir(parents=True, exist_ok=True)
		for item in (staged / "sites").iterdir() if (staged / "sites").is_dir() else []:
			target = sites_assets / item.name
			if target.is_dir() and not target.is_symlink():
				shutil.rmtree(target)
			elif target.exists() or target.is_symlink():
				target.unlink()
			if item.is_dir():
				shutil.copytree(item, target)
			else:
				shutil.copy2(item, target)
			click.echo(f"  {item.name} -> {target}")


def _import_node_modules(staged: Path, target: Path) -> None:
	"""Place the runtime libraries where the framework links them from.

	`apps/<app>/node_modules` is what the relink step exposes as
	/assets/<app>/node_modules, so the files go there -- merged package by
	package, so a bench that does have a full node_modules keeps it.
	"""
	import shutil

	if not staged.is_dir():
		return
	for package in staged.iterdir():
		destination = target / package.name
		if destination.exists():
			shutil.rmtree(destination)
		shutil.copytree(package, destination)
	for alias, source in _NODE_MODULE_ALIASES.items():
		alias_path, source_path = target / alias, target / source
		if source_path.is_dir() and not alias_path.exists():
			# A copy rather than a link: Windows needs a privilege for links
			# that a locked-down workstation will not grant.
			shutil.copytree(source_path, alias_path)
	click.echo(f"  runtime libraries -> {target}")


def _assert_safe_member(name: str) -> None:
	if name.startswith("/") or ".." in Path(name).parts:
		raise click.ClickException(f"Refusing to extract unsafe path from bundle: {name!r}")


@main.command()
@click.option("--site", default=None)
@click.option("--web-workers", default=None, type=int)
@click.option("--background-workers", default=None, type=int)
@click.option("--no-scheduler", is_flag=True)
def start(site, web_workers, background_workers, no_scheduler):
	"""Start the whole stack under winbench's own supervisor."""
	from winbench.procs import ProcessSpec, Supervisor

	bench = _bench_or_exit()
	site = _resolve_site(bench, site)
	cfg = bench.read_winbench_config()
	web_workers = web_workers if web_workers is not None else cfg.get("web_workers", 1)
	background_workers = (
		background_workers if background_workers is not None else cfg.get("background_workers", 2)
	)

	port = int(bench.read_common_config().get("webserver_port", 8000))
	env = {"FRAPPE_BENCH_ROOT": str(bench.root), "FRAPPE_SITE": site}
	cwd = str(bench.sites_dir)
	me = [bench.python, "-m", "winbench.cli"]

	specs: list[ProcessSpec] = []
	for i in range(web_workers):
		specs.append(
			ProcessSpec(
				name=f"web-{i}",
				args=[*me, "serve", "--site", site, "--port", str(port + i)],
				cwd=cwd,
				env=env,
			)
		)
	for i in range(background_workers):
		specs.append(
			ProcessSpec(
				name=f"worker-{i}",
				args=[*me, "worker", "--site", site],
				cwd=cwd,
				env=env,
			)
		)
	if not no_scheduler:
		specs.append(
			ProcessSpec(name="scheduler", args=[*me, "scheduler", "--site", site], cwd=cwd, env=env)
		)

	supervisor = Supervisor(specs)
	supervisor.start()
	sys.exit(supervisor.wait())


# ---------------------------------------------------------------------------
# diagnostics
# ---------------------------------------------------------------------------


@main.command()
def doctor():
	"""Check services and report which compatibility patches are active."""
	from winbench import services
	from winbench.compat import APPLIED, IS_WINDOWS, SKIPPED
	from winbench.compat import install as install_compat

	bench = _bench_or_exit()
	click.echo(f"bench root : {bench.root}")
	click.echo(f"python     : {bench.python}")
	click.echo(f"platform   : {sys.platform} ({'windows' if IS_WINDOWS else 'posix'})")
	click.echo(f"apps       : {', '.join(bench.apps()) or '(none)'}")
	click.echo(f"sites      : {', '.join(bench.sites()) or '(none)'}\n")

	site_config = None
	sites = bench.sites()
	if sites:
		site = os.environ.get("FRAPPE_SITE") if os.environ.get("FRAPPE_SITE") in sites else sites[0]
		site_config = json.loads((bench.sites_dir / site / "site_config.json").read_text())

	failures = 0
	for check in services.run_all(bench.read_common_config(), site_config):
		click.echo(str(check))
		if not check.ok and check.name in {"postgres", "redis_cache", "redis_queue"}:
			failures += 1

	click.echo("\ncompatibility patches:")
	if IS_WINDOWS:
		install_compat()
		for name in APPLIED:
			click.echo(f"  applied  {name}")
		for name, reason in SKIPPED:
			click.echo(f"  SKIPPED  {name}: {reason}")
	else:
		# None is live here: every patch defers to the original on POSIX. They
		# are still installed, inertly, to prove each one still finds what it
		# replaces in this framework version -- so a framework upgrade that
		# breaks a patch is caught on the Linux build machine, not on the first
		# Windows workstation.
		click.echo("  (none needed on this platform)")
		install_compat(force=True)
		click.echo(
			f"  {len(APPLIED)} Windows patches install cleanly against this framework version "
			"(inert here)"
		)
		for name, reason in SKIPPED:
			click.echo(f"  would FAIL on Windows  {name}: {reason}")
			failures += 1

	sys.exit(1 if failures else 0)


@main.command("list-sites")
def list_sites():
	"""List sites in this bench."""
	bench = _bench_or_exit()
	for site in bench.sites():
		config = json.loads((bench.sites_dir / site / "site_config.json").read_text())
		click.echo(f"{site}\t{config.get('db_type', '?')}\t{config.get('db_name', '?')}")


if __name__ == "__main__":
	main()
