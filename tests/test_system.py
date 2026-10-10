"""OS install hints and Python version window."""

from app.system import ffmpeg_install_hint, os_family, python_version_ok


def test_os_family() -> None:
    assert os_family("Darwin") == "macos"
    assert os_family("Linux") == "linux"


def test_ffmpeg_hint_macos() -> None:
    assert "brew" in ffmpeg_install_hint("Darwin")


def test_ffmpeg_hint_linux() -> None:
    hint = ffmpeg_install_hint("Linux")
    assert "ffmpeg" in hint


def test_python_version_window() -> None:
    assert python_version_ok(3, 11)
    assert python_version_ok(3, 12)
    assert not python_version_ok(3, 10)
    assert not python_version_ok(3, 13)
