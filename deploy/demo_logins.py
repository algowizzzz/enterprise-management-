#!/usr/bin/env python3
"""Give the demonstration personas passwords, and write them down — outside git.

    cd .bench/sites
    FRAPPE_BENCH_ROOT=<bench> ../../.venv/bin/python ../../deploy/demo_logins.py \\
        --site <site> --url http://<site>:8000 --out ~/demo-logins.md [--administrator]

``deploy/demo_data.py`` creates its personas with no password, so none of them
can sign in until someone decides they should. This is that decision, made for
a demonstration or training site: every persona (``*@demo.example``) gets a
fresh random password, and — with ``--administrator`` — so does Administrator.
The list is written to one Markdown file with each person's roles and where
their day starts, so a reviewer can sign in as the Chief Risk Officer, then as
the Committee Secretary, and see the same platform through each role.

Why the file must live outside the repository: this repository is shared, and
a password committed to it is public for good, even if the commit is later
reverted. A shared, known demo password is worse still — the demo loader is
meant to be run by whoever receives the platform, possibly on a server. So the
passwords are random per run, the script refuses to write the file anywhere
inside this git work tree, and a site that already holds real (non-demo) users
is refused unless ``--force`` says the operator knows what the site is.

Running it again issues new passwords and overwrites the file; nothing else
changes. Nothing is emailed.
"""

from __future__ import annotations

import argparse
import secrets
import string
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DEMO_DOMAIN = "@demo.example"

# Where each kind of user starts. Keyed by the role that decides it, most
# specific first; the first role a persona holds picks its line.
START_HERE = [
    ("Consilium Administrator", "/admin — reference data, imports, attestation campaigns; the desk at /app"),
    ("Head of Risk Governance", "Inbox, then /escalations (sensitive matters visible) and /reports"),
    ("Risk Governance Office", "/formation-requests to decide new forums; /forums compliance reviews"),
    ("Committee Secretary", "/forums — a forum's meetings, minutes, motions and votes"),
    ("Enterprise Policy Office", "/policies — approvals, gate exceptions, attestation from a policy"),
    ("Compliance Reviewer", "Inbox — reviews waiting; /forum-review for compliance decisions"),
    ("Policy Reviewer", "Inbox — documents in review; return with comments from /policy"),
    ("Escalation Owner", "/escalations — matters you own; take ownership from a group queue in the Inbox"),
    ("Escalation Reviewer", "Inbox — escalation approvals and challenges"),
    ("Policy Owner", "/policies — your documents, versions and review dates"),
    ("Forum Owner", "/forums — the forums you own and their reviews"),
    ("Consilium Audit", "/reports and a record's History tab; Export evidence pack"),
    ("Records Manager", "/policies retention and dispositions; the desk for archive records"),
    ("Governance Viewer", "Home — the forum map; read-only across forums and policies"),
]


def _password() -> str:
    # 20 characters from letters and digits plus a few symbols that survive
    # copy and paste; at least one of each class so any password policy passes.
    classes = [string.ascii_lowercase, string.ascii_uppercase, string.digits, "-_.!"]
    chars = [secrets.choice(c) for c in classes]
    alphabet = "".join(classes)
    chars += [secrets.choice(alphabet) for _ in range(16)]
    secrets.SystemRandom().shuffle(chars)
    return "".join(chars)


def _inside_repo(path: Path) -> bool:
    try:
        top = subprocess.run(["git", "-C", str(REPO), "rev-parse", "--show-toplevel"],
                             capture_output=True, text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        top = str(REPO)
    return path.resolve().is_relative_to(Path(top).resolve())


def _start_for(roles: set[str]) -> str:
    for role, where in START_HERE:
        if role in roles:
            return where
    return "Home"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--site", required=True)
    parser.add_argument("--sites-path", default=".")
    parser.add_argument("--url", required=True, help="the address people open, e.g. http://consilium.localhost:8000")
    parser.add_argument("--out", required=True, help="Markdown file to write; must be outside this repository")
    parser.add_argument("--administrator", action="store_true", help="also give Administrator a new password")
    parser.add_argument("--force", action="store_true", help="run even though the site has non-demo users")
    args = parser.parse_args()

    out = Path(args.out).expanduser()
    if _inside_repo(out):
        print(f"Refused: {out} is inside the repository. Passwords must never be committed; "
              "write the file somewhere outside it.", file=sys.stderr)
        return 2

    import frappe
    from frappe.utils.password import update_password

    frappe.init(site=args.site, sites_path=str(Path(args.sites_path).resolve()))
    frappe.connect()
    frappe.set_user("Administrator")
    frappe.flags.mute_emails = True

    users = frappe.get_all("User", filters={"user_type": "System User", "enabled": 1},
                           fields=["name", "full_name"], order_by="name")
    personas = [u for u in users if u.name.endswith(DEMO_DOMAIN)]
    others = [u.name for u in users if not u.name.endswith(DEMO_DOMAIN) and u.name != "Administrator"]
    if not personas:
        print("Refused: no demonstration personas on this site; run deploy/demo_data.py first.", file=sys.stderr)
        return 2
    if others and not args.force:
        print(f"Refused: this site has {len(others)} non-demo user(s) (e.g. {others[0]}). "
              "Pass --force only if it is a demonstration site.", file=sys.stderr)
        return 2

    rows = []
    for user in personas:
        roles = set(frappe.get_roles(user.name)) - {"All", "Guest", "Desk User"}
        password = _password()
        update_password(user.name, password)
        rows.append((user.full_name or user.name, user.name, password, sorted(roles), _start_for(roles)))
    admin_password = None
    if args.administrator:
        admin_password = _password()
        update_password("Administrator", admin_password)
    frappe.db.commit()

    url = args.url.rstrip("/")
    lines = [
        "# Demonstration logins",
        "",
        f"Site: **{args.site}** — open <{url}/login>. Generated by `deploy/demo_logins.py`;",
        "running it again issues new passwords and replaces this file.",
        "",
        "> **Keep this file private.** It is deliberately outside the git repository. These are",
        "> fictitious personas on a demonstration site — never load demo data, or these",
        "> passwords, onto a server that holds real records.",
        "",
    ]
    if admin_password:
        lines += [
            "## Administrator",
            "",
            "| Login | Password | Use it for |",
            "|---|---|---|",
            f"| `Administrator` | `{admin_password}` | Everything, including the desk at {url}/app — "
            "workflows, state flags, settings |",
            "",
        ]
    lines += [
        f"## Personas ({len(rows)})",
        "",
        "| Persona | Login | Password | Roles | Start here |",
        "|---|---|---|---|---|",
    ]
    for name, login, password, roles, start in rows:
        lines.append(f"| {name} | `{login}` | `{password}` | {', '.join(roles)} | {start} |")
    lines += [
        "",
        "## A tour in five sign-ins",
        "",
        "1. **Chief Risk Officer** — Inbox, then a sensitive escalation, then Reports → Gaps and risk.",
        "2. **Committee Secretary** — a forum's Meetings and Decisions tabs; put a motion to a vote.",
        "3. **Enterprise Policy Office Lead** — a policy in review: approvals in order, a gate exception.",
        "4. **Risk Governance Office Lead** — Requests: decide a new forum; Admin for reference data.",
        "5. **Internal Auditor** — any record's History tab and *Export evidence pack*.",
        "",
    ]
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines))
    out.chmod(0o600)
    print(f"{len(rows)} persona password(s){' and Administrator' if admin_password else ''} set; "
          f"written to {out} (readable by you only).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
