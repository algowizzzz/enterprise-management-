#!/usr/bin/env python3
"""Drive an OpenID Connect sign-in through the real stack, as a browser would.

Runs INSIDE the harness container after the site has been configured with
[sso] mode = oidc against scripts/mock_oidc_provider.py on 127.0.0.1:9100.

    python3 sso_demo.py --site governance.example.internal --ca /etc/pki/tls/certs/rehearsal-ca.crt \\
        --existing sso.person@example.internal --stranger stranger@example.internal

1. Opens the sign-in page over HTTPS (through nginx) and finds the provider's
   button, whose link the platform built with a one-time state.
2. Follows it to the provider, which redirects back with a code; the platform
   exchanges the code, reads the user info, and signs the person in.
3. Asks the platform who is signed in.
4. Repeats for a person the provider vouches for but who has no account here,
   and expects the platform to refuse (sign-ups are denied by default).

Standard library only. Prints a JSON summary.
"""

from __future__ import annotations

import argparse
import html
import http.cookiejar
import json
import re
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request


def browser(ca: str):
    ctx = ssl.create_default_context(cafile=ca)
    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({}),
        urllib.request.HTTPSHandler(context=ctx),
        urllib.request.HTTPCookieProcessor(jar),
    )
    return opener, jar


def sign_in(site: str, ca: str, login_hint: str | None) -> dict:
    opener, jar = browser(ca)
    base = f"https://{site}"
    page = opener.open(base + "/login", timeout=60).read().decode()
    links = [html.unescape(u) for u in re.findall(r'href="([^"]*/authorize\?[^"]+)"', page)]
    result = {"login_page_has_provider_button": bool(links)}
    if not links:
        return result
    url = links[0] + (f"&login_hint={urllib.parse.quote(login_hint)}" if login_hint else "")
    result["authorize_url"] = url.split("?")[0]
    try:
        response = opener.open(url, timeout=60)
        result["landed_on"] = urllib.parse.urlsplit(response.geturl()).path
        result["status"] = response.status
    except urllib.error.HTTPError as e:
        result["status"] = e.code
        body = e.read().decode(errors="replace")
        result["refusal"] = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", body)).strip()[:160]
    who = opener.open(base + "/api/method/frappe.auth.get_logged_user", timeout=60) if any(
        c.name == "sid" and c.value != "Guest" for c in jar) else None
    result["signed_in_as"] = json.loads(who.read()).get("message") if who else None
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--site", required=True)
    parser.add_argument("--ca", required=True)
    parser.add_argument("--existing", required=True)
    parser.add_argument("--stranger", required=True)
    args = parser.parse_args()
    summary = {
        "existing_account": sign_in(args.site, args.ca, args.existing),
        "no_account": sign_in(args.site, args.ca, args.stranger),
    }
    print(json.dumps(summary, indent=1))
    ok = (summary["existing_account"].get("signed_in_as") == args.existing
          and summary["no_account"].get("signed_in_as") is None
          and summary["no_account"].get("status") == 403)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
