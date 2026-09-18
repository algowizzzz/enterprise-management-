"""Discovery and health checks for the two external services Frappe needs.

Frappe on Linux is normally handed MariaDB and three Redis instances by bench's
generated config. On Windows we assume the operator installed:

  * PostgreSQL for Windows (the official EDB installer), and
  * a Redis-compatible server -- Memurai, or the Windows build of Redis.

Neither ships a socket path or an init script we can rely on, so everything here
speaks TCP only and reports actionable errors rather than raising ConnectionError
from three layers down.
"""

import os
import shutil
import socket
from dataclasses import dataclass
from urllib.parse import urlparse

IS_WINDOWS = os.name == "nt"

DEFAULT_REDIS_CACHE = "redis://127.0.0.1:13000"
DEFAULT_REDIS_QUEUE = "redis://127.0.0.1:11000"


@dataclass
class Check:
	name: str
	ok: bool
	detail: str

	def __str__(self) -> str:
		return f"[{'ok ' if self.ok else 'FAIL'}] {self.name}: {self.detail}"


def _port_open(host: str, port: int, timeout: float = 2.0) -> bool:
	try:
		with socket.create_connection((host, port), timeout=timeout):
			return True
	except OSError:
		return False


def check_postgres(host: str, port: int, user: str, password: str, dbname: str = "postgres") -> Check:
	if not _port_open(host, port):
		hint = (
			"Install PostgreSQL for Windows and make sure the service is running "
			"(services.msc -> postgresql-x64-16)."
			if IS_WINDOWS
			else "Is postgres running?"
		)
		return Check("postgres", False, f"nothing listening on {host}:{port}. {hint}")

	try:
		import psycopg2
	except ImportError:
		return Check("postgres", False, "psycopg2 is not installed in this environment")

	try:
		conn = psycopg2.connect(
			host=host, port=port, user=user, password=password, dbname=dbname, connect_timeout=5
		)
	except Exception as e:
		return Check("postgres", False, f"{host}:{port} refused the credentials: {e}")

	with conn:
		with conn.cursor() as cur:
			cur.execute("select version()")
			version = cur.fetchone()[0]
	conn.close()
	return Check("postgres", True, version.split(" on ")[0])


def check_redis(url: str, label: str = "redis") -> Check:
	parsed = urlparse(url)
	host, port = parsed.hostname or "127.0.0.1", parsed.port or 6379

	if not _port_open(host, port):
		hint = (
			"Install Memurai (https://www.memurai.com) or the Windows Redis build, "
			"then start one instance per port."
			if IS_WINDOWS
			else "Is redis-server running on this port?"
		)
		return Check(label, False, f"nothing listening on {host}:{port}. {hint}")

	try:
		import redis

		client = redis.from_url(url, socket_connect_timeout=5)
		info = client.info("server")
	except Exception as e:
		return Check(label, False, f"{url} did not answer PING: {e}")

	return Check(label, True, f"{url} -> {info.get('redis_version', 'unknown')}")


def check_node() -> Check:
	node = shutil.which("node")
	if not node:
		return Check(
			"node",
			False,
			"node is not on PATH. Needed only for `winbench build` and the realtime server.",
		)
	return Check("node", True, node)


def check_wkhtmltopdf() -> Check:
	exe = shutil.which("wkhtmltopdf")
	if not exe:
		return Check(
			"wkhtmltopdf",
			False,
			"not on PATH. PDF print formats will fall back to WeasyPrint; "
			"install the patched-qt Windows build for pixel-identical output.",
		)
	return Check("wkhtmltopdf", True, exe)


def run_all(common_config: dict, site_config: dict | None = None) -> list[Check]:
	"""Run every check.

	The database check signs in as the superuser named in the bench config when
	one is configured there -- a development bench, where `new-site` needs it.
	An installation made by the deployment kit deliberately keeps no superuser
	password on disk, so there it signs in with the site's own role instead,
	which is also the more honest test: it is the login the application uses.
	"""
	host = common_config.get("db_host", "127.0.0.1")
	port = int(common_config.get("db_port", 5432))
	if not common_config.get("root_password") and site_config and site_config.get("db_name"):
		postgres = check_postgres(
			host,
			port,
			site_config.get("db_user") or site_config["db_name"],
			site_config.get("db_password", ""),
			dbname=site_config["db_name"],
		)
		postgres.detail += " (as the site's own role)"
	else:
		postgres = check_postgres(
			host,
			port,
			common_config.get("root_login", "postgres"),
			common_config.get("root_password", ""),
		)
	checks = [
		postgres,
		check_redis(common_config.get("redis_cache", DEFAULT_REDIS_CACHE), "redis_cache"),
		check_redis(common_config.get("redis_queue", DEFAULT_REDIS_QUEUE), "redis_queue"),
		check_node(),
		check_wkhtmltopdf(),
	]
	return checks
