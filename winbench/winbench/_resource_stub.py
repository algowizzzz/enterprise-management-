"""A minimal stand-in for the POSIX-only :mod:`resource` module.

Frappe imports ``resource`` unconditionally (``frappe/core/doctype/prepared_report``)
and uses exactly one call: ``resource.getrusage(resource.RUSAGE_SELF).ru_maxrss``.
On Windows that import is an immediate ``ModuleNotFoundError``, which takes down
the whole Prepared Report doctype and therefore every background report run.

This module is registered in ``sys.modules`` as ``resource`` by
:mod:`winbench.compat` before Frappe is imported.  Values are sourced from
psutil so ``ru_maxrss`` stays meaningful rather than being hard-coded to zero.

Units follow the Linux convention (kilobytes) so that any code comparing against
Linux-derived thresholds keeps working.
"""

import os
from typing import NamedTuple

RUSAGE_SELF = 0
RUSAGE_CHILDREN = -1
RUSAGE_THREAD = 1

RLIMIT_AS = 5
RLIMIT_CPU = 0
RLIMIT_NOFILE = 7
RLIM_INFINITY = -1


class struct_rusage(NamedTuple):
	ru_utime: float = 0.0
	ru_stime: float = 0.0
	ru_maxrss: int = 0
	ru_ixrss: int = 0
	ru_idrss: int = 0
	ru_isrss: int = 0
	ru_minflt: int = 0
	ru_majflt: int = 0
	ru_nswap: int = 0
	ru_inblock: int = 0
	ru_oublock: int = 0
	ru_msgsnd: int = 0
	ru_msgrcv: int = 0
	ru_nsignals: int = 0
	ru_nvcsw: int = 0
	ru_nivcsw: int = 0


def _peak_rss_kb(pid: int | None = None) -> int:
	try:
		import psutil
	except ImportError:
		return 0
	try:
		info = psutil.Process(pid or os.getpid()).memory_info()
	except Exception:
		return 0
	# peak_wset is Windows-only and is the true analogue of ru_maxrss; fall back
	# to the current working set when it is unavailable.
	peak = getattr(info, "peak_wset", None) or getattr(info, "rss", 0)
	return int(peak // 1024)


def getrusage(who: int = RUSAGE_SELF) -> struct_rusage:
	try:
		import psutil
	except ImportError:
		return struct_rusage(ru_maxrss=_peak_rss_kb())

	proc = psutil.Process(os.getpid())
	try:
		cpu = proc.cpu_times()
		utime, stime = float(cpu.user), float(cpu.system)
	except Exception:
		utime = stime = 0.0

	if who == RUSAGE_CHILDREN:
		children_rss = 0
		try:
			for child in proc.children(recursive=True):
				children_rss = max(children_rss, _peak_rss_kb(child.pid))
		except Exception:
			pass
		return struct_rusage(ru_utime=utime, ru_stime=stime, ru_maxrss=children_rss)

	return struct_rusage(ru_utime=utime, ru_stime=stime, ru_maxrss=_peak_rss_kb())


def getrlimit(resource_id: int) -> tuple[int, int]:
	"""Windows has no per-process rlimits; report "unlimited" for every resource."""
	return (RLIM_INFINITY, RLIM_INFINITY)


def setrlimit(resource_id: int, limits: tuple[int, int]) -> None:
	"""No-op. Windows job objects are not a drop-in for setrlimit, and Frappe only
	ever uses this defensively."""
	return None


def getpagesize() -> int:
	try:
		import mmap

		return mmap.PAGESIZE
	except Exception:
		return 4096
