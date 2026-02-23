import importlib.metadata
import logging
import pathlib
import plistlib
import shutil
import subprocess
import sys
from pathlib import Path

logger = logging.getLogger("asky.daemon.app_bundle_macos")

BUNDLE_NAME = "AskyDaemon"
BUNDLE_IDENTIFIER = "com.evren.asky.daemon"
BUNDLE_PATH = Path.home() / "Applications" / f"{BUNDLE_NAME}.app"


def bundle_is_current(python_path: str) -> bool:
    """Check if the existing bundle matches the current Python interpreter."""
    if not BUNDLE_PATH.exists():
        return False

    marker = BUNDLE_PATH / "Contents" / "MacOS" / ".bundle_meta"
    if not marker.exists():
        return False

    try:
        content = marker.read_text().strip()
        return content == python_path
    except Exception:
        return False


def create_bundle(python_path: str) -> Path:
    """Create the AskyDaemon.app bundle."""
    macos_dir = BUNDLE_PATH / "Contents" / "MacOS"
    resources_dir = BUNDLE_PATH / "Contents" / "Resources"

    macos_dir.mkdir(parents=True, exist_ok=True)
    resources_dir.mkdir(parents=True, exist_ok=True)

    # 1. Info.plist
    try:
        version = importlib.metadata.version("asky-cli")
    except importlib.metadata.PackageNotFoundError:
        version = "0.0.0"

    plist = {
        "CFBundleName": BUNDLE_NAME,
        "CFBundleIdentifier": BUNDLE_IDENTIFIER,
        "CFBundleExecutable": BUNDLE_NAME,
        "CFBundleIconFile": "AppIcon",
        "CFBundleVersion": version,
        "CFBundleShortVersionString": version,
        "CFBundlePackageType": "APPL",
        "LSUIElement": True,
        "NSHighResolutionCapable": True,
    }

    plist_path = BUNDLE_PATH / "Contents" / "Info.plist"
    with plist_path.open("wb") as f:
        plistlib.dump(plist, f)

    # 2. Launcher script
    launcher = macos_dir / BUNDLE_NAME
    launcher.write_text(
        f'#!/bin/bash\nexec "{python_path}" -m asky --xmpp-daemon --xmpp-menubar-child "$@"\n'
    )
    launcher.chmod(0o755)

    # 3. Copy icon
    # Path(__file__) is src/asky/daemon/app_bundle_macos.py
    # data/icons/ is src/asky/data/icons/
    # so we go up 1 level to asky/ and then into data/icons/
    icns_src = Path(__file__).resolve().parent.parent / "data" / "icons" / "asky.icns"
    png_fallback = (
        Path(__file__).resolve().parent.parent
        / "data"
        / "icons"
        / "asky_icon_small.png"
    )
    icns_dest = resources_dir / "AppIcon.icns"

    if icns_src.exists():
        shutil.copy2(icns_src, icns_dest)
    elif png_fallback.exists():
        shutil.copy2(png_fallback, icns_dest)

    # 4. Marker
    marker = macos_dir / ".bundle_meta"
    marker.write_text(python_path)

    # 5. Touch to invalidate Spotlight index
    subprocess.run(["touch", str(BUNDLE_PATH)], capture_output=True)

    return BUNDLE_PATH


def ensure_bundle_exists() -> None:
    """Ensure the macOS app bundle is present and up to date."""
    python_path = sys.executable
    if bundle_is_current(python_path):
        logger.debug("app bundle is current, skipping creation")
        return

    logger.info("creating macOS app bundle at %s", BUNDLE_PATH)
    try:
        create_bundle(python_path)
        logger.info("macOS app bundle created at %s", BUNDLE_PATH)
    except Exception:
        # We don't want to block daemon startup if this fails
        logger.debug("app bundle creation failed", exc_info=True)
