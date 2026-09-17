"""Fork-free RQ worker.

This is the single most important difference between Frappe on Linux and Frappe
on Windows.

Upstream ``frappe.utils.background_jobs.start_worker`` uses ``rq.Worker``, whose
"work horse" model calls ``os.fork()`` for every job so a crashing or hanging job
can be killed without taking the worker down.  Windows has no ``fork``, so that
worker cannot even be instantiated there.

RQ ships the pieces to run without it:

* :class:`rq.SimpleWorker` executes the job in the worker process itself.
* :class:`rq.timeouts.TimerDeathPenalty` implements job timeouts with a
  ``threading.Timer`` that raises in the main thread, instead of ``SIGALRM``.

The trade-off is real and worth stating plainly: a job that segfaults the
interpreter, or that blocks in a C call where the timer's exception cannot be
delivered, takes its worker down with it.  We mitigate that the way Windows
services normally do -- run several single-job workers under the supervisor in
:mod:`winbench.procs`, which restarts any that die.
"""

import os
import sys

IS_WINDOWS = os.name == "nt"


def build_worker_class():
	from rq import SimpleWorker, Worker
	from rq.timeouts import TimerDeathPenalty

	if not IS_WINDOWS:
		# On POSIX keep upstream semantics exactly: fork per job.
		return Worker

	class WindowsWorker(SimpleWorker):
		"""SimpleWorker with a thread-timer death penalty instead of SIGALRM."""

		death_penalty_class = TimerDeathPenalty

	return WindowsWorker


def start(
	queue: str | None = None,
	quiet: bool = False,
	burst: bool = False,
	site: str | None = None,
) -> None:
	from winbench.compat import install as install_compat

	install_compat()

	import frappe
	from frappe.utils.background_jobs import get_queue_list, get_redis_conn, set_niceness

	with frappe.init_site(site):
		connection = get_redis_conn()
		queues = get_queue_list(
			[q.strip() for q in queue.split(",")] if queue else None,
			build_queue_name=True,
		)

	set_niceness()

	worker_class = build_worker_class()
	worker = worker_class(queues, connection=connection)

	if IS_WINDOWS:
		# FrappeWorker starts the scheduler in a thread; SimpleWorker does not,
		# so `winbench scheduler` runs it as its own supervised process instead.
		pass

	worker.work(
		logging_level="WARNING" if quiet else "INFO",
		burst=burst,
		date_format="%Y-%m-%d %H:%M:%S",
		log_format="%(asctime)s,%(msecs)03d %(message)s",
	)


def main() -> int:
	import argparse

	parser = argparse.ArgumentParser(prog="winbench-worker")
	parser.add_argument("--queue", default=None)
	parser.add_argument("--site", default=None)
	parser.add_argument("--quiet", action="store_true")
	parser.add_argument("--burst", action="store_true")
	args = parser.parse_args()

	start(queue=args.queue, quiet=args.quiet, burst=args.burst, site=args.site)
	return 0


if __name__ == "__main__":
	sys.exit(main())
