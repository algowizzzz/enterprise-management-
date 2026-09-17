"""A minimal process supervisor -- the replacement for supervisord + Procfile.

bench generates ``config/supervisor.conf`` and hands it to supervisord, which is
POSIX-only (it forks, it uses signals, it manages process groups through
``os.setpgid``).  Our needs here are modest: start N child processes,
restart them if they die, stream their output, and shut the whole tree down
cleanly on Ctrl+C.

The Windows-specific parts:

* Child processes are put in a **Job Object** so that killing the supervisor
  kills the tree.  Without this, ``winbench serve`` leaves orphaned workers
  holding the Postgres connections and the next start fails on port-in-use.
* Shutdown uses ``CTRL_BREAK_EVENT`` (which requires
  ``CREATE_NEW_PROCESS_GROUP`` at spawn time) rather than ``SIGTERM``, because
  Windows has no SIGTERM delivery to another process.
* ``os.killpg`` is used on POSIX for the same effect.
"""

import os
import signal
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field

IS_WINDOWS = os.name == "nt"


@dataclass
class ProcessSpec:
	name: str
	args: list[str]
	cwd: str | None = None
	env: dict[str, str] = field(default_factory=dict)
	restart: bool = True


class Supervisor:
	"""Start a set of processes, keep them alive, stop them all together."""

	def __init__(self, specs: list[ProcessSpec], restart_delay: float = 2.0):
		self.specs = specs
		self.restart_delay = restart_delay
		self._procs: dict[str, subprocess.Popen] = {}
		self._stopping = threading.Event()
		self._job_handle = None

	# -- windows job object ----------------------------------------------
	def _create_job_object(self):
		"""Create a Job Object that kills all children when the handle closes."""
		if not IS_WINDOWS:
			return None
		try:
			import ctypes
			import ctypes.wintypes as wt

			kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

			class JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
				_fields_ = [
					("PerProcessUserTimeLimit", ctypes.c_int64),
					("PerJobUserTimeLimit", ctypes.c_int64),
					("LimitFlags", wt.DWORD),
					("MinimumWorkingSetSize", ctypes.c_size_t),
					("MaximumWorkingSetSize", ctypes.c_size_t),
					("ActiveProcessLimit", wt.DWORD),
					("Affinity", ctypes.POINTER(ctypes.c_ulong)),
					("PriorityClass", wt.DWORD),
					("SchedulingClass", wt.DWORD),
				]

			class IO_COUNTERS(ctypes.Structure):
				_fields_ = [
					("ReadOperationCount", ctypes.c_uint64),
					("WriteOperationCount", ctypes.c_uint64),
					("OtherOperationCount", ctypes.c_uint64),
					("ReadTransferCount", ctypes.c_uint64),
					("WriteTransferCount", ctypes.c_uint64),
					("OtherTransferCount", ctypes.c_uint64),
				]

			class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
				_fields_ = [
					("BasicLimitInformation", JOBOBJECT_BASIC_LIMIT_INFORMATION),
					("IoInfo", IO_COUNTERS),
					("ProcessMemoryLimit", ctypes.c_size_t),
					("JobMemoryLimit", ctypes.c_size_t),
					("PeakProcessMemoryUsed", ctypes.c_size_t),
					("PeakJobMemoryUsed", ctypes.c_size_t),
				]

			JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000
			JobObjectExtendedLimitInformation = 9

			job = kernel32.CreateJobObjectW(None, None)
			if not job:
				return None

			info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
			info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
			kernel32.SetInformationJobObject(
				job,
				JobObjectExtendedLimitInformation,
				ctypes.byref(info),
				ctypes.sizeof(info),
			)
			self._kernel32 = kernel32
			return job
		except Exception:
			return None

	def _assign_to_job(self, proc: subprocess.Popen) -> None:
		if not (IS_WINDOWS and self._job_handle):
			return
		try:
			import ctypes

			handle = int(proc._handle)  # type: ignore[attr-defined]
			self._kernel32.AssignProcessToJobObject(self._job_handle, ctypes.c_void_p(handle))
		except Exception:
			pass

	# -- lifecycle --------------------------------------------------------
	def _spawn(self, spec: ProcessSpec) -> subprocess.Popen:
		env = {**os.environ, **spec.env}
		kwargs: dict = {"cwd": spec.cwd, "env": env}
		if IS_WINDOWS:
			# Required for CTRL_BREAK_EVENT to be deliverable to this child only.
			kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
		else:
			kwargs["start_new_session"] = True

		proc = subprocess.Popen(spec.args, **kwargs)
		self._assign_to_job(proc)
		return proc

	def start(self) -> None:
		self._job_handle = self._create_job_object()
		for spec in self.specs:
			print(f"[winbench] starting {spec.name}: {subprocess.list2cmdline(spec.args)}")
			self._procs[spec.name] = self._spawn(spec)

	def wait(self) -> int:
		"""Block until interrupted, restarting any child that exits unexpectedly."""
		try:
			while not self._stopping.is_set():
				time.sleep(0.5)
				for spec in self.specs:
					proc = self._procs.get(spec.name)
					if proc is None or proc.poll() is None:
						continue
					code = proc.returncode
					if self._stopping.is_set():
						continue
					if not spec.restart:
						print(f"[winbench] {spec.name} exited with {code}; not restarting")
						self._procs.pop(spec.name, None)
						continue
					print(f"[winbench] {spec.name} exited with {code}; restarting in {self.restart_delay}s")
					time.sleep(self.restart_delay)
					self._procs[spec.name] = self._spawn(spec)
		except KeyboardInterrupt:
			print("\n[winbench] shutting down...")
		finally:
			self.stop()
		return 0

	def stop(self, timeout: float = 10.0) -> None:
		self._stopping.set()

		for name, proc in self._procs.items():
			if proc.poll() is not None:
				continue
			try:
				if IS_WINDOWS:
					proc.send_signal(signal.CTRL_BREAK_EVENT)
				else:
					os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
			except Exception:
				try:
					proc.terminate()
				except Exception:
					pass

		deadline = time.monotonic() + timeout
		for name, proc in self._procs.items():
			remaining = max(0.0, deadline - time.monotonic())
			try:
				proc.wait(timeout=remaining)
			except subprocess.TimeoutExpired:
				print(f"[winbench] {name} did not stop in time; killing")
				proc.kill()

		if IS_WINDOWS and self._job_handle:
			# Closing the job handle kills anything still in the tree.
			try:
				self._kernel32.CloseHandle(self._job_handle)
			except Exception:
				pass
			self._job_handle = None

		self._procs.clear()


def python_spec(name: str, python: str, module_args: list[str], cwd: str, **kw) -> ProcessSpec:
	return ProcessSpec(name=name, args=[python, *module_args], cwd=cwd, **kw)
