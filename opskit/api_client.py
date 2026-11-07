"""Inventory API client with timeouts, retries with backoff, and pagination."""
import argparse
import json
import logging
import os
import sys
from collections import Counter

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from opskit.logconf import setup_logging

log = logging.getLogger("opskit.api")


class InventoryClient:
    def __init__(self, base_url, token, timeout=5.0, retries=3, backoff=0.5):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({"Authorization": f"Bearer {token}", "User-Agent": "opskit/1.0"})
        retry = Retry(
            total=retries,
            backoff_factor=backoff,
            status_forcelist=(500, 502, 503, 504),
            allowed_methods=frozenset({"GET"}),
            raise_on_status=False,
        )
        adapter = HTTPAdapter(max_retries=retry)
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)

    def _get(self, path, **params):
        resp = self.session.get(f"{self.base_url}{path}", params=params, timeout=self.timeout)
        resp.raise_for_status()
        return resp.json()

    def health(self):
        return self._get("/health")

    def list_hosts(self):
        """Return every host across all pages."""
        first = self._get("/api/hosts", page=1)
        hosts = list(first["items"])
        for page in range(2, first["pages"] + 1):
            hosts.extend(self._get("/api/hosts", page=page)["items"])
        return hosts

    def set_maintenance(self, name, enabled=True):
        resp = self.session.post(f"{self.base_url}/api/hosts/{name}/maintenance",
                                 json={"enabled": enabled}, timeout=self.timeout)
        resp.raise_for_status()
        return resp.json()


def summarize_hosts(hosts):
    return {
        "total": len(hosts),
        "by_role": dict(Counter(h["role"] for h in hosts)),
        "by_env": dict(Counter(h["env"] for h in hosts)),
        "in_maintenance": sorted(h["name"] for h in hosts if h.get("maintenance")),
    }


def main(argv=None):
    parser = argparse.ArgumentParser(prog="opskit api", description="Inventory API client")
    parser.add_argument("--url", default=os.environ.get("OPSKIT_API_URL", "http://127.0.0.1:5000"))
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("health")
    sub.add_parser("summary")
    m = sub.add_parser("maintenance")
    m.add_argument("name")
    m.add_argument("--off", action="store_true", help="take the host out of maintenance")
    args = parser.parse_args(argv)
    setup_logging()

    token = os.environ.get("OPSKIT_API_TOKEN")
    if not token:
        log.error("OPSKIT_API_TOKEN is not set")
        return 1
    client = InventoryClient(args.url, token)
    try:
        if args.cmd == "health":
            out = client.health()
        elif args.cmd == "summary":
            out = summarize_hosts(client.list_hosts())
        else:
            out = client.set_maintenance(args.name, enabled=not args.off)
    except requests.exceptions.ConnectionError as exc:
        log.error("cannot reach %s (%s)", args.url, type(exc).__name__)
        return 3
    except requests.exceptions.HTTPError as exc:
        log.error("HTTP %s from %s", exc.response.status_code, exc.response.url)
        return 4
    print(json.dumps(out, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
