#!/usr/bin/env python3
"""Generate deterministic nginx 'combined'-style access logs for the lab."""
import gzip
from datetime import datetime, timedelta, timezone
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "data" / "logs"
BASE = datetime(2024, 5, 1, 10, 0, 0, tzinfo=timezone.utc)
PATHS = ["/", "/api/orders", "/api/products", "/health"]
def make_line(i):
    ts = (BASE + timedelta(seconds=i)).strftime("%d/%b/%Y:%H:%M:%S %z")
    method = "GET"
    if i % 10 == 0:
        ip, path, status = "203.0.113.50", "/wp-login.php", 404
    else:
        ip = "198.51.100.7" if i % 10 in (1, 2) else f"10.0.0.{i % 50 + 1}"
        if i % 50 == 1:
            method, path, status = "POST", "/api/orders", 500
        elif i % 25 == 3:
            path, status = "/api/payments", 503
        else:
            path, status = PATHS[i % 4], 200
    size = 150 + (i % 7) * 100
    return f'{ip} - - [{ts}] "{method} {path} HTTP/1.1" {status} {size} "-" "curl/7.81.0"\n'
def main():
    OUT.mkdir(parents=True, exist_ok=True)
    rotated, current = [], []
    for i in range(1000):
        target = rotated if i < 500 else current
        target.append(make_line(i))
        if i % 100 == 99:
            target.append("garbage line without the expected format\n")
    with gzip.open(OUT / "access.log.1.gz", "wt", encoding="utf-8") as fh:
        fh.writelines(rotated)
    (OUT / "access.log").write_text("".join(current), encoding="utf-8")
    print(f"wrote {len(rotated)} lines to access.log.1.gz and {len(current)} lines to access.log in {OUT}")


if __name__ == "__main__":
    main()
