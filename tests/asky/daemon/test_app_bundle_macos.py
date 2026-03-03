import os
import pathlib
import plistlib
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from asky.daemon.app_bundle_macos import (
    BUNDLE_NAME,
    LAUNCHER_VERSION,
    bundle_is_current,
    create_bundle,
    ensure_bundle_exists,
)


@pytest.fixture
def mock_bundle_path(tmp_path):
    """Override BUNDLE_PATH to use a temporary directory."""
    test_bundle = tmp_path / "AskyDaemon.app"
    with patch("asky.daemon.app_bundle_macos.BUNDLE_PATH", test_bundle):
        yield test_bundle


def test_bundle_is_current_missing_bundle(mock_bundle_path):
    """bundle_is_current returns False when the bundle does not exist."""
    assert bundle_is_current("/usr/bin/python3") is False


def test_bundle_is_current_wrong_python(mock_bundle_path):
    """bundle_is_current returns False when the Python path in .bundle_meta differs."""
    macos_dir = mock_bundle_path / "Contents" / "MacOS"
    macos_dir.mkdir(parents=True)
    marker = macos_dir / ".bundle_meta"
    marker.write_text("/old/python")

    assert bundle_is_current("/new/python") is False


def test_bundle_is_current_correct_python(mock_bundle_path):
    """bundle_is_current returns True when the Python path and version both match."""
    macos_dir = mock_bundle_path / "Contents" / "MacOS"
    macos_dir.mkdir(parents=True)
    marker = macos_dir / ".bundle_meta"
    marker.write_text(f"/current/python\n{LAUNCHER_VERSION}")

    assert bundle_is_current("/current/python") is True


def test_bundle_is_current_old_format_triggers_rebuild(mock_bundle_path):
    """bundle_is_current returns False for old single-line markers (forces rebuild)."""
    macos_dir = mock_bundle_path / "Contents" / "MacOS"
    macos_dir.mkdir(parents=True)
    marker = macos_dir / ".bundle_meta"
    marker.write_text("/current/python")

    assert bundle_is_current("/current/python") is False


def test_create_bundle_creates_all_paths(mock_bundle_path):
    """create_bundle creates the expected directory structure and files."""
    python_path = "/test/python"

    # Mock resources to avoid Copy errors if files don't exist in the test env
    with patch("shutil.copy2"):
        create_bundle(python_path)

    macos_dir = mock_bundle_path / "Contents" / "MacOS"
    resources_dir = mock_bundle_path / "Contents" / "Resources"
    plist_path = mock_bundle_path / "Contents" / "Info.plist"
    launcher = macos_dir / BUNDLE_NAME
    marker = macos_dir / ".bundle_meta"

    assert macos_dir.exists()
    assert resources_dir.exists()
    assert plist_path.exists()
    assert launcher.exists()
    assert marker.exists()

    # Verify marker content
    lines = marker.read_text().splitlines()
    assert lines[0] == python_path
    assert lines[1] == LAUNCHER_VERSION

    # Verify launcher content
    launcher_content = launcher.read_text()
    assert python_path in launcher_content
    assert "--xmpp-daemon" in launcher_content
    assert "--xmpp-menubar-child" in launcher_content
    assert ".zshrc" in launcher_content
    assert ".zprofile" in launcher_content

    # Verify launcher is executable
    assert os.access(launcher, os.X_OK)


def test_create_bundle_info_plist_content(mock_bundle_path):
    """Info.plist contains the required keys and values."""
    python_path = "/test/python"

    with (
        patch("shutil.copy2"),
        patch("importlib.metadata.version", return_value="1.2.3"),
    ):
        create_bundle(python_path)

    plist_path = mock_bundle_path / "Contents" / "Info.plist"
    with open(plist_path, "rb") as f:
        plist = plistlib.load(f)

    assert plist["CFBundleName"] == BUNDLE_NAME
    assert plist["CFBundleIdentifier"] == "com.evren.asky.daemon"
    assert plist["CFBundleExecutable"] == BUNDLE_NAME
    assert plist["LSUIElement"] is True
    assert plist["NSHighResolutionCapable"] is True
    assert plist["CFBundleVersion"] == "1.2.3"


def test_ensure_bundle_exists_skips_when_current(mock_bundle_path):
    """ensure_bundle_exists does nothing if the bundle is already current."""
    with (
        patch(
            "asky.daemon.app_bundle_macos.bundle_is_current", return_value=True
        ) as mock_current,
        patch("asky.daemon.app_bundle_macos.create_bundle") as mock_create,
    ):
        ensure_bundle_exists()
        mock_current.assert_called_once()
        mock_create.assert_not_called()


def test_ensure_bundle_exists_creates_when_missing(mock_bundle_path):
    """ensure_bundle_exists calls create_bundle if the bundle is not current."""
    with (
        patch(
            "asky.daemon.app_bundle_macos.bundle_is_current", return_value=False
        ) as mock_current,
        patch("asky.daemon.app_bundle_macos.create_bundle") as mock_create,
    ):
        ensure_bundle_exists()
        mock_current.assert_called_once()
        mock_create.assert_called_once()
