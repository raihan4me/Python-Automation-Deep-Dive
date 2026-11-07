import os
import tarfile
import time

import pytest

from opskit.sysutil import CommandError, archive_old_files, run


def test_run_returns_stdout():
    assert run(["echo", "hello"]) == "hello"


def test_run_timeout_raises():
    with pytest.raises(CommandError, match="timeout"):
        run(["sleep", "3"], timeout=1)


def test_archive_is_idempotent(tmp_path):
    src, dest = tmp_path / "src", tmp_path / "dest"
    src.mkdir()
    old, new = src / "old.log", src / "new.log"
    old.write_text("old")
    new.write_text("new")
    ten_days_ago = time.time() - 10 * 86400
    os.utime(old, (ten_days_ago, ten_days_ago))
    assert archive_old_files(src, dest, older_than_days=7) == ["old.log"]
    assert not old.exists() and new.exists()
    with tarfile.open(dest / "old.log.tar.gz") as tar:
        assert tar.getnames() == ["old.log"]
    assert archive_old_files(src, dest, older_than_days=7) == []
