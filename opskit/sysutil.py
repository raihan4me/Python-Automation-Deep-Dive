"""System automation helpers: safe subprocess calls, service/disk/process checks, log archiving."""
import argparse
import json
import logging
import shlex
import shutil
import subprocess
import sys
import tarfile
import time
from pathlib import Path
import psutil
from opskit.logconf import setup_logging

log = logging.getLogger("opskit.sysutil")

class CommandError(RuntimeError):
    """Raised when an external command fails, times out or does not exist."""

def run(cmd, timeout=10):
    """Run a command WITHOUT a shell and return stripped stdout."""
    if isinstance(cmd, str):
        cmd = shlex.split(cmd)
    log.debug("running %s", cmd)
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=True)
    except FileNotFoundError as exc:
        raise CommandError(f"command not found: {cmd[0]}") from exc
    except subprocess.TimeoutExpired as exc:
        raise CommandError(f"timeout after {timeout}s: {' '.join(cmd)}") from exc
    except subprocess.CalledProcessError as exc:
        raise CommandError(f"exit {exc.returncode}: {' '.join(cmd)}: {exc.stderr.strip()}") from exc
    return proc.stdout.strip()

def service_status(name):
    """Return the systemd state of a unit (non-zero exit for inactive is a valid answer)."""
    proc = subprocess.run(["systemctl", "is-active", name], capture_output=True, text=True, timeout=5)
    return proc.stdout.strip() or "unknown"

def disk_report(paths, warn_pct=80.0):
    rows = []
    for p in paths:
        usage = shutil.disk_usage(p)
        pct = round(100 * usage.used / usage.total, 1)
        rows.append({"path": str(p), "total_gb": round(usage.total / 1e9, 1), "used_pct": pct, "status": "WARN" if pct >= warn_pct else "OK"})
    return rows

def top_processes(n=5):
    procs = []
    for p in psutil.process_iter(["pid", "name", "memory_info"]):
        mem = p.info.get("memory_info")
        if mem is None:
            continue
        procs.append({"pid": p.info["pid"], "name": p.info["name"], "rss_mb": round(mem.rss / 1048576, 1)})
    return sorted(procs, key=lambda r: r["rss_mb"], reverse=True)[:n]

def archive_old_files(src, dest, pattern="*.log", older_than_days=7, dry_run=False):
    """Compress and remove files older than N days (idempotent, atomic .part -> rename)."""
    src, dest = Path(src), Path(dest)
    cutoff = time.time() - older_than_days * 86400
    archived = []
    for path in sorted(src.glob(pattern)):
        if not path.is_file() or path.stat().st_mtime >= cutoff:
            continue
        target = dest / f"{path.name}.tar.gz"
        if dry_run:
            log.info("[dry-run] would archive %s -> %s", path, target)
            archived.append(path.name)
            continue
        dest.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            tmp = target.with_name(target.name + ".part")
            with tarfile.open(tmp, "w:gz") as tar:
                tar.add(path, arcname=path.name)
            tmp.rename(target)
            path.unlink()
            log.info("archived %s -> %s", path, target)
            archived.append(path.name)
    return archived

def main(argv=None):
    parser = argparse.ArgumentParser(prog="opskit sys", description="System checks and housekeeping")
    sub = parser.add_subparsers(dest="cmd", required=True)
    
    d = sub.add_parser("disk", help="disk usage per path")
    d.add_argument("paths", nargs="*", default=["/"])
    d.add_argument("--warn", type=float, default=80.0)
    
    s = sub.add_parser("services", help="systemd unit states")
    s.add_argument("names", nargs="+")
    
    pr = sub.add_parser("procs", help="top processes by memory")
    pr.add_argument("-n", type=int, default=5)
    
    a = sub.add_parser("archive", help="archive and remove old files")
    a.add_argument("src")
    a.add_argument("dest")
    a.add_argument("--pattern", default="*.log")
    a.add_argument("--days", type=int, default=7)
    a.add_argument("--dry-run", action="store_true")
    
    args = parser.parse_args(argv)
    setup_logging()
    
    if args.cmd == "disk":
        rows = disk_report(args.paths, args.warn)
        print(json.dumps(rows, indent=2, sort_keys=True))
        return 1 if any(r["status"] == "WARN" for r in rows) else 0
    if args.cmd == "services":
        states = {name: service_status(name) for name in args.names}
        print(json.dumps(states, indent=2, sort_keys=True))
        return 0 if all(v == "active" for v in states.values()) else 1
    if args.cmd == "procs":
        print(json.dumps(top_processes(args.n), indent=2))
        return 0
    
    archived = archive_old_files(args.src, args.dest, args.pattern, args.days, args.dry_run)
    print(json.dumps({"archived": archived, "dry_run": args.dry_run}, indent=2, sort_keys=True))
    return 0

if __name__ == "__main__":
    sys.exit(main())
