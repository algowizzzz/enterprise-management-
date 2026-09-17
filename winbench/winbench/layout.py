"""Bench directory layout.

Frappe itself only cares about a handful of things:

    <root>/apps/<app>/          importable python packages
    <root>/sites/apps.txt       which apps exist
    <root>/sites/common_site_config.json
    <root>/sites/<site>/site_config.json

`bench` adds config/supervisor.conf, config/nginx.conf, config/redis_*.conf and a
Procfile on top. winbench keeps the first set verbatim -- so a bench created here
is readable by upstream tooling -- and replaces the second set with its own
``winbench.json``.
"""

import json
import os
from pathlib import Path

WINBENCH_FILE = "winbench.json"


class BenchNotFound(Exception):
	pass


class Bench:
	def __init__(self, root: Path):
		self.root = Path(root).resolve()

	# -- paths ------------------------------------------------------------
	@property
	def apps_dir(self) -> Path:
		return self.root / "apps"

	@property
	def sites_dir(self) -> Path:
		return self.root / "sites"

	@property
	def logs_dir(self) -> Path:
		return self.root / "logs"

	@property
	def config_dir(self) -> Path:
		return self.root / "config"

	@property
	def env_dir(self) -> Path:
		return self.root / "env"

	@property
	def apps_txt(self) -> Path:
		return self.sites_dir / "apps.txt"

	@property
	def common_site_config(self) -> Path:
		return self.sites_dir / "common_site_config.json"

	@property
	def winbench_json(self) -> Path:
		return self.root / WINBENCH_FILE

	@property
	def python(self) -> str:
		"""The interpreter that owns this bench's virtualenv."""
		for candidate in (
			self.env_dir / "Scripts" / "python.exe",  # Windows venv layout
			self.env_dir / "bin" / "python",  # POSIX venv layout
		):
			if candidate.exists():
				return str(candidate)
		import sys

		return sys.executable

	# -- data -------------------------------------------------------------
	def apps(self) -> list[str]:
		if not self.apps_txt.exists():
			return []
		return [line.strip() for line in self.apps_txt.read_text().splitlines() if line.strip()]

	def add_app(self, app: str) -> None:
		apps = self.apps()
		if app not in apps:
			apps.append(app)
			self.apps_txt.write_text("\n".join(apps) + "\n")

	def sites(self) -> list[str]:
		if not self.sites_dir.exists():
			return []
		return sorted(
			p.name
			for p in self.sites_dir.iterdir()
			if p.is_dir() and (p / "site_config.json").exists()
		)

	def read_common_config(self) -> dict:
		if not self.common_site_config.exists():
			return {}
		return json.loads(self.common_site_config.read_text())

	def write_common_config(self, config: dict) -> None:
		self.common_site_config.write_text(json.dumps(config, indent=1, sort_keys=True))

	def read_winbench_config(self) -> dict:
		if not self.winbench_json.exists():
			return {}
		return json.loads(self.winbench_json.read_text())

	def write_winbench_config(self, config: dict) -> None:
		self.winbench_json.write_text(json.dumps(config, indent=2, sort_keys=True))

	def ensure_dirs(self) -> None:
		for d in (self.apps_dir, self.sites_dir, self.logs_dir, self.config_dir):
			d.mkdir(parents=True, exist_ok=True)


def find_bench(start: str | os.PathLike | None = None) -> Bench:
	"""Walk upwards looking for a bench root, the way `bench` itself does."""
	if env_root := os.environ.get("FRAPPE_BENCH_ROOT"):
		return Bench(Path(env_root))

	current = Path(start or os.getcwd()).resolve()
	for candidate in (current, *current.parents):
		if (candidate / "sites" / "apps.txt").exists() or (candidate / WINBENCH_FILE).exists():
			return Bench(candidate)

	raise BenchNotFound(
		f"No bench found at or above {current}. "
		"Run `winbench init <path>` first, or set FRAPPE_BENCH_ROOT."
	)
