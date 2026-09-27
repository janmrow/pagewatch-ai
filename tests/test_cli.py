"""Checks for the available CLI surface."""

from importlib.metadata import version

import pytest

from pagewatch.cli import main


def test_help_exits_successfully(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc_info:
        main(["--help"])

    assert exc_info.value.code == 0
    output = capsys.readouterr()
    assert "usage: pagewatch" in output.out
    assert "--version" in output.out


def test_version_exits_successfully(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc_info:
        main(["--version"])

    assert exc_info.value.code == 0
    assert capsys.readouterr().out.strip() == f"pagewatch {version('pagewatch-ai')}"


def test_bare_command_does_not_claim_to_monitor(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as exc_info:
        main([])

    assert exc_info.value.code == 2
    assert "monitoring is not implemented yet" in capsys.readouterr().err
