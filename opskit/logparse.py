"""Parse nginx access logs (plain or gzip) and produce a JSON summary."""
import argparse
import gzip
import json
import logging
import re
import sys
from collections import Counter
from pathlib import Path

from opskit.logconf import setup_logging

log = logging.getLogger("opskit.logparse")

LINE_RE = re.compile(
    r'^(?P<ip>\S+) \S+ \S+ \[(?P<ts>[^\]]+)\] '
    r'"(?P<method>[A-Z]+) (?P<path>\S+) HTTP/[\d.]+" '
    r'(?P<status>\d{3}) (?P<size>\d+)'
)
def open_log(path: Path):
    """Open .gz files transparently in text mode."""
    if path.suffix == ".gz":
        return gzip.open(path, "rt", encoding="utf-8")
    return path.open("r", encoding="utf-8")


def parse_line(line):
    """Return a dict for a valid line or None for a malformed one."""
    m = LINE_RE.match(line)
    if not m:
        return None
    rec = m.groupdict()
    rec["status"] = int(rec["status"])
    rec["size"] = int(rec["size"])
    return rec
def iter_records(paths, stats):
    """Yield parsed records from all files; count malformed lines in stats."""
    for path in paths:
        with open_log(path) as fh:
            for lineno, line in enumerate(fh, 1):
                rec = parse_line(line)
                if rec is None:
                    stats["malformed"] += 1
                    log.debug("malformed line %s:%d", path.name, lineno)
                    continue
                yield rec


def summarize(paths, top=3):
    stats, status, ips = Counter(), Counter(), Counter()
    total = 0
    for rec in iter_records(paths, stats):
        total += 1
        status[rec["status"]] += 1
        ips[rec["ip"]] += 1
    errors_5xx = sum(count for code, count in status.items() if code >= 500)
    return {
        "files": [p.name for p in paths],
        "total_requests": total,
        "malformed_lines": stats["malformed"],
        "status_counts": {str(code): count for code, count in sorted(status.items())},
        "error_rate_5xx_pct": round(100 * errors_5xx / total, 2) if total else 0.0,
        "top_ips": ips.most_common(top),
    }
def main(argv=None):
    parser = argparse.ArgumentParser(prog="opskit logs", description="Summarise nginx access logs")
    parser.add_argument("paths", nargs="+", type=Path, help="log files (.gz supported)")
    parser.add_argument("--top", type=int, default=3, help="number of top client IPs")
    parser.add_argument("--threshold", type=float, default=5.0, help="max allowed 5xx rate in percent")
    parser.add_argument("--output", type=Path, help="write JSON here instead of stdout")
    args = parser.parse_args(argv)
    setup_logging()

    missing = [str(p) for p in args.paths if not p.is_file()]
    if missing:
        log.error("missing log files: %s", ", ".join(missing))
        return 1

    report = summarize(args.paths, args.top)
    text = json.dumps(report, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + "\n", encoding="utf-8")
        log.info("report written to %s", args.output)
    else:
        print(text)

    if report["error_rate_5xx_pct"] > args.threshold:
        log.warning("5xx error rate %.2f%% exceeds threshold %.2f%%",
                    report["error_rate_5xx_pct"], args.threshold)
        return 2
    return 0
if __name__ == "__main__":
    sys.exit(main())
