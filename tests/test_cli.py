from importlib.metadata import version

import pytest

from jml.cli import main


def test_help_exits_cleanly(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["--help"])
    assert exc.value.code == 0
    assert "usage: jml" in capsys.readouterr().out


def test_version(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0
    assert capsys.readouterr().out.strip() == f"jml {version('jml-kit')}"


def test_no_arguments_prints_help(capsys):
    assert main([]) == 0
    assert "usage: jml" in capsys.readouterr().out
