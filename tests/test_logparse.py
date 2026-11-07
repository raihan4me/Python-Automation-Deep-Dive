import gzip

import pytest

from opskit.logparse import main, parse_line, summarize

GOOD = '10.0.0.1 - - [01/May/2024:10:00:00 +0000] "GET /health HTTP/1.1" 200 512 "-" "curl/7.81.0"\n'


def test_parse_good_line():
    rec = parse_line(GOOD)
    assert rec["ip"] == "10.0.0.1"
    assert rec["path"] == "/health"
    assert rec["status"] == 200 and rec["size"] == 512


def test_parse_bad_line():
    assert parse_line("garbage\n") is None


def test_summarize_plain_and_gzip(tmp_path):
    plain = tmp_path / "a.log"
    plain.write_text(GOOD * 3 + "junk\n")
    gz = tmp_path / "a.log.1.gz"
    with gzip.open(gz, "wt") as fh:
        fh.write(GOOD.replace(" 200 ", " 503 "))
    rep = summarize([plain, gz])
    assert rep["total_requests"] == 4
    assert rep["malformed_lines"] == 1
    assert rep["status_counts"] == {"200": 3, "503": 1}
    assert rep["error_rate_5xx_pct"] == 25.0


def test_threshold_exit_code(tmp_path):
    path = tmp_path / "t.log"
    path.write_text(GOOD + GOOD.replace(" 200 ", " 503 "))
    assert main([str(path), "--threshold", "10"]) == 2
    assert main([str(path), "--threshold", "60"]) == 0
