"""Constants for XMPP daemon plugin."""

from pathlib import Path

# Storage defaults
XMPP_VOICE_STORAGE_DIR = Path("~/.config/asky/voice").expanduser()
XMPP_IMAGE_STORAGE_DIR = Path("~/.config/asky/images").expanduser()

# Behavior defaults
XMPP_VOICE_AUTO_YES_WITHOUT_INTERFACE_MODEL = True
