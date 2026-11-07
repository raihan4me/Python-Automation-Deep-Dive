"""Run checks on and push files to a fleet of SSH nodes with Paramiko."""
import argparse
import hashlib
import json
import logging
import os
import shlex
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import paramiko
import yaml

from opskit.logconf import setup_logging

log = logging.getLogger("opskit.remote")
ROOT = Path(__file__).resolve().parent.parent


def load_fleet(path):
    with open(path, encoding="utf-8") as fh:
        cfg = yaml.safe_load(fh)
    cfg["key_file"] = os.path.expanduser(cfg["key_file"])
    kh = Path(cfg["known_hosts"])
    cfg["known_hosts"] = kh if kh.is_absolute() else ROOT / kh
    return cfg


def connect(node, cfg):
    """Open an SSH connection with STRICT host-key checking (RejectPolicy)."""
    client = paramiko.SSHClient()
    if cfg["known_hosts"].exists():
        client.load_host_keys(str(cfg["known_hosts"]))
    client.set_missing_host_key_policy(paramiko.RejectPolicy())
    client.connect(node["host"], port=node["port"], username=cfg["user"],
                   key_filename=cfg["key_file"], timeout=10, banner_timeout=10,
                   auth_timeout=10, allow_agent=False, look_for_keys=False)
    return client


def run_remote(client, cmd, timeout=15):
    _stdin, stdout, stderr = client.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode(errors="replace").strip()
    err = stderr.read().decode(errors="replace").strip()
    rc = stdout.channel.recv_exit_status()
    return rc, out, err


def check_node(node, cfg):
    """Run every configured check on one node. Never raises."""
    result = {"node": node["name"], "ok": True, "checks": {}, "failed": []}
    client = None
    try:
        client = connect(node, cfg)
        for chk in cfg["checks"]:
            rc, out, err = run_remote(client, chk["cmd"])
            if rc == 0:
                result["checks"][chk["name"]] = out
            else:
                result["checks"][chk["name"]] = f"rc={rc} {err}".strip()
                result["failed"].append(chk["name"])
                result["ok"] = False
    except Exception as exc:  # noqa: BLE001
        result["ok"] = False
        result["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        if client is not None:
            client.close()
    return result


def push_file(node, cfg, local, remote_path):
    """Upload via SFTP and compare SHA-256 on both sides. Never raises."""
    try:
        local_sum = hashlib.sha256(Path(local).read_bytes()).hexdigest()
        client = connect(node, cfg)
        try:
            with client.open_sftp() as sftp:
                sftp.put(str(local), remote_path)
                size = sftp.stat(remote_path).st_size
            rc, out, _ = run_remote(client, f"sha256sum {shlex.quote(remote_path)}")
            remote_sum = out.split()[0] if rc == 0 and out else ""
            return {"node": node["name"], "bytes": size, "sha256_match": remote_sum == local_sum}
        finally:
            client.close()
    except Exception as exc:  # noqa: BLE001
        return {"node": node["name"], "error": f"{type(exc).__name__}: {exc}"}


def main(argv=None):
    parser = argparse.ArgumentParser(prog="opskit fleet", description="SSH fleet automation")
    parser.add_argument("--fleet", type=Path, default=ROOT / "config" / "fleet.yaml")
    parser.add_argument("--workers", type=int, default=4)
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("check", help="run configured checks on every node")
    p = sub.add_parser("push", help="upload a file to every node")
    p.add_argument("local", type=Path)
    p.add_argument("remote")
    args = parser.parse_args(argv)
    setup_logging()
    logging.getLogger("paramiko").setLevel(logging.WARNING)

    cfg = load_fleet(args.fleet)
    nodes = cfg["nodes"]
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        if args.cmd == "check":
            results = list(pool.map(lambda n: check_node(n, cfg), nodes))
            ok = all(r["ok"] for r in results)
        else:
            if not args.local.is_file():
                log.error("no such file: %s", args.local)
                return 1
            results = list(pool.map(lambda n: push_file(n, cfg, args.local, args.remote), nodes))
            ok = all(r.get("sha256_match") for r in results)
    for r in results:
        if r.get("error") or r.get("failed"):
            log.error("%s: %s", r["node"], r.get("error") or f"failed checks: {r['failed']}")
    print(json.dumps(results, indent=2, sort_keys=True))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
