"""OS helpers for install hints and environment checks."""

from __future__ import annotations

import platform
from pathlib import Path


def os_family(system: str | None = None) -> str:
    name = system if system is not None else platform.system()
    if name == "Darwin":
        return "macos"
    if name == "Linux":
        return "linux"
    return name.lower()


def ffmpeg_install_hint(system: str | None = None) -> str:
    family = os_family(system)
    if family == "macos":
        return "brew install ffmpeg"
    if family == "linux":
        if Path("/etc/arch-release").exists():
            return "sudo pacman -S ffmpeg"
        if Path("/etc/debian_version").exists():
            return "sudo apt install ffmpeg"
        if Path("/etc/fedora-release").exists() or Path("/etc/redhat-release").exists():
            return "sudo dnf install ffmpeg"
        return "sudo apt install ffmpeg  # or: sudo pacman -S ffmpeg / sudo dnf install ffmpeg"
    return "install ffmpeg and add it to PATH"


def tts_install_hint(system: str | None = None) -> str:
    family = os_family(system)
    if family == "macos":
        return (
            "Install a Russian voice in System Settings → Accessibility → Spoken Content "
            "(Milena or Yuri)."
        )
    if family == "linux":
        if Path("/etc/arch-release").exists():
            return "sudo pacman -S espeak-ng"
        if Path("/etc/debian_version").exists():
            return "sudo apt install espeak-ng"
        return "sudo apt install espeak-ng  # or: sudo pacman -S espeak-ng"
    return "install a Russian TTS engine"


def python_version_ok(major: int, minor: int) -> bool:
    return (3, 11) <= (major, minor) < (3, 13)
