"""winbench -- a Windows-first replacement for Frappe's `bench` CLI.

`bench` is a thin orchestration layer that assumes supervisor, nginx, Ansible and
a POSIX shell. None of that is required to *run* Frappe; winbench replaces it with
plain Python process management that works identically on Windows and Linux.
"""

__version__ = "0.1.0"

from winbench.compat import install as install_compat  # noqa: E402,F401
