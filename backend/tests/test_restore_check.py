"""The restore check (scripts/restore_check.py): the URL helpers, and a real dump-restore-compare
of the test database on this machine."""

import shutil

import pytest

from app.core.config import get_settings
from scripts import restore_check as rc


def test_url_helpers_keep_the_password_out_of_the_way():
    assert rc.libpq("postgresql+psycopg://u:p@h:5432/db") == "postgresql://u:p@h:5432/db"
    assert (
        rc.with_db("postgresql+psycopg://u:p@h:5432/db?sslmode=require", "x")
        == "postgresql://u:p@h:5432/x?sslmode=require"
    )
    assert rc._server("postgresql://u:p@Host:5432/db") == "host:5432"


def test_it_refuses_a_scratch_database_on_the_same_server(capsys):
    url = get_settings().database_url
    assert rc.main(["--source", url, "--scratch", url]) == 2
    assert "different server" in capsys.readouterr().err


@pytest.mark.skipif(not shutil.which("pg_dump"), reason="pg_dump is not installed here")
def test_a_real_dump_restores_and_the_counts_match(capsys):
    url = get_settings().database_url
    assert (
        rc.main(["--source", url, "--scratch", rc.with_db(url, "postgres"), "--allow-same-server"])
        == 0
    )
    out = capsys.readouterr().out
    assert out.startswith("OK:") and "tables" in out
