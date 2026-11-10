import pytest

from focusblocks import cli


@pytest.fixture(autouse=True)
def no_app(monkeypatch):
    """Never start the real tracker from a test."""
    def refuse(*args, **kwargs):
        raise AssertionError("Application was created")

    monkeypatch.setattr("focusblocks.app.Application.create", refuse)
    monkeypatch.setattr(cli, "configure_logging", lambda **kwargs: None)


def test_unknown_command_is_rejected(capsys):
    with pytest.raises(SystemExit) as exit_info:
        cli.main(["foo"])
    assert exit_info.value.code == 2
    assert "unknown command: foo" in capsys.readouterr().err


def test_help_lists_commands(capsys):
    cli.main(["--help"])
    assert "focusblocks report" in capsys.readouterr().out
