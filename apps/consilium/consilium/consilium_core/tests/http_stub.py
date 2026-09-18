"""A scriptable HTTP server on 127.0.0.1, for tests of outbound integrations.

Nothing in the test suite may reach the network. Tests of code that speaks to
an outside service — the Microsoft Graph mail route, the AI connection test —
start one of these instead, point the code's configurable base address at it,
and script what it answers. It records every request, so a test can assert on
exactly what would have left the platform.

    with stub_server(handler) as (server, url):
        ...
        server.requests  # [{"method", "path", "headers", "body", "json", "form"}]

``handler(request, server)`` returns ``(status, headers, body)``; ``body`` may
be bytes, a string or anything JSON-serialisable. A handler that sleeps longer
than the client's timeout is how a timeout is tested.
"""

from __future__ import annotations

import contextlib
import json
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class _Handler(BaseHTTPRequestHandler):
	def log_message(self, *args):  # keep test output clean
		pass

	def _handle(self):
		length = int(self.headers.get("content-length") or 0)
		raw = self.rfile.read(length) if length else b""
		headers = {k.lower(): v for k, v in self.headers.items()}
		request = {"method": self.command, "path": self.path, "headers": headers, "body": raw,
		           "json": None, "form": None}
		content_type = headers.get("content-type", "")
		if "json" in content_type:
			try:
				request["json"] = json.loads(raw or b"{}")
			except ValueError:
				pass
		elif "x-www-form-urlencoded" in content_type:
			request["form"] = dict(urllib.parse.parse_qsl(raw.decode()))
		self.server.requests.append(request)
		status, extra_headers, body = self.server.handler(request, self.server)
		if not isinstance(body, bytes | str):
			body = json.dumps(body)
		if isinstance(body, str):
			body = body.encode()
		try:
			self.send_response(status)
			self.send_header("content-type", (extra_headers or {}).get("content-type", "application/json"))
			for key, value in (extra_headers or {}).items():
				if key.lower() != "content-type":
					self.send_header(key, value)
			self.send_header("content-length", str(len(body)))
			self.end_headers()
			self.wfile.write(body)
		except (BrokenPipeError, ConnectionResetError):
			pass  # the client gave up (a timeout test), which is the point

	do_POST = _handle  # noqa: N815 — the stdlib's naming
	do_GET = _handle  # noqa: N815


@contextlib.contextmanager
def stub_server(handler):
	server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
	server.daemon_threads = True
	server.handler = handler
	server.requests = []
	thread = threading.Thread(target=server.serve_forever, daemon=True)
	thread.start()
	try:
		yield server, f"http://127.0.0.1:{server.server_address[1]}"
	finally:
		server.shutdown()
		server.server_close()
