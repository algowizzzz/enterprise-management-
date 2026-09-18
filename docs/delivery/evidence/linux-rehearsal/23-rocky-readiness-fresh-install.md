# Readiness report — governance.example.internal

- Generated: 2026-09-18T07:23:48+00:00
- Host: governance.example.internal — Rocky Linux 9.3 (Blue Onyx), x86_64, 8 CPUs
- Installed release: release abecd3f1fd63: consilium 0.1.0 (source c2c8a91+uncommitted), frappe 15.121.0, for linux/x86_64 Python 3.11, built 2026-09-18T07:16:20+00:00
- Public address: https://governance.example.internal
- Result: **READY** — 14 passed, 0 failed, 0 not applicable

| | Phase | Check |
|---|---|---|
| pass | Services | every unit is active |
| pass | Services | exactly one scheduler process on this host |
| pass | Services | web server answers |
| pass | Health | deploy/healthcheck.py |
| pass | Phase 1 | sign-in by a server-created session (no password) |
| pass | Phase 1 | smoke test 8/8, desk loads with every asset |
| pass | Phase 2 | a document moves through a workflow; Workflow Action and Version rows are written |
| pass | PDF | a governing document renders to a valid PDF |
| pass | Phase 3 | winbench doctor: no compatibility patches needed on this platform |
| pass | Phase 3 | every install and upgrade made no network access |
| pass | Interface | UI regression sweep |
| pass | Offline | no served page or asset references an external host |
| pass | TLS | nginx terminates TLS for governance.example.internal |
| pass | Scheduler | scheduler enabled for the site |

## Evidence

### Services: every unit is active

```
consilium-web.service=active, consilium-scheduler.service=active, consilium-worker@1.service=active, consilium-worker@2.service=active
```

### Services: exactly one scheduler process on this host

```
1 process(es) running 'winbench.cli scheduler'
```

### Services: web server answers

```
http://127.0.0.1:8000/api/method/ping
```

### Health: deploy/healthcheck.py

```
17/17 checks passed. The installation is healthy.
```

### Phase 1: sign-in by a server-created session (no password)

```
session for Administrator created: yes
```

### Phase 1: smoke test 8/8, desk loads with every asset

```
8 passed, 0 failed
  [ok ] api ping -- {"message":"pong"}
  [ok ] login (server-created session) -- {"message":"Administrator"}
  [ok ] session accepted -- as Administrator
  [ok ] desk html -- 143409 bytes
  [ok ] desk references assets -- 10 found in /app
  [ok ] all referenced assets load -- 10/10 ok
  [ok ] workflow api -- {"data":[{"name":"Governing Document Lifecycle"}]}
  [ok ] doctype list api -- {"data":[]}
```

### Phase 2: a document moves through a workflow; Workflow Action and Version rows are written

```
{"ok": true, "workflow": "Readiness 7def8c", "created_in_state": "Readiness 7def8c Pending", "open_workflow_actions_before": 1, "state_after_approve": "Readiness 7def8c Approved", "workflow_actions": [{"name": "1jia8ui90d", "status": "Completed", "workflow_state": "Readiness 7def8c Pending", "completed_by": "Administrator"}], "version_rows": 1, "version_records_state_change": true, "cleanup": "removed everything it created"}
```

### PDF: a governing document renders to a valid PDF

```
{"ok": true, "engine": "0.12.6.1", "document": "an unsaved document built in memory (the site has none yet)", "seconds": 1.96, "bytes": 18459, "starts_with_pdf_header": true, "ends_with_eof": true, "pages": 1}
```

### Phase 3: winbench doctor: no compatibility patches needed on this platform

```
: /opt/consilium
python     : /opt/consilium/env/bin/python
platform   : linux (posix)
apps       : frappe, consilium
sites      : governance.example.internal
[ok ] postgres: PostgreSQL 16.15 (as the site's own role)
[ok ] redis_cache: redis://cons-redis:6379/0 -> 7.4.11
[ok ] redis_queue: redis://cons-redis:6379/1 -> 7.4.11
[FAIL] node: node is not on PATH. Needed only for `winbench build` and the realtime server.
[ok ] wkhtmltopdf: /usr/local/bin/wkhtmltopdf
compatibility patches:
  (none needed on this platform)
  8 Windows patches install cleanly against this framework version (inert here)
```

### Phase 3: every install and upgrade made no network access

```
2026-09-18T07:20:02+00:00: 0 network lines in pip-20260918-071910.log; internet from the host unreachable
```

### Interface: UI regression sweep

```
237 passed, 0 failed
```

### Offline: no served page or asset references an external host

```
9 pages and 30 scripts/stylesheets fetched; no external fetch found
```

### TLS: nginx terminates TLS for governance.example.internal

```
TLSv1.3 handshake verified for governance.example.internal; certificate expires Oct 18 07:18:57 2026 GMT
https://governance.example.internal:443/api/method/ping -> HTTP/1.1 200 OK; HSTS present
http://governance.example.internal:80/app -> HTTP/1.1 301 Moved Permanently Location: https://governance.example.internal/app
```

### Scheduler: scheduler enabled for the site

```
{"enabled": true, "consilium_jobs": 11, "recent_runs": {}, "last_run": null}
```
