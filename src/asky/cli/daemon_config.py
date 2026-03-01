"""Interactive daemon configuration editing for all platforms."""

from __future__ import annotations

from dataclasses import dataclass
import logging
import os
from pathlib import Path
from typing import Optional

import tomllib
import tomlkit
from rich.console import Console
from rich.prompt import Confirm, Prompt

from asky.config.loader import _get_config_dir
from asky.daemon import startup

XMPP_CONFIG_FILENAME = "xmpp.toml"
DEFAULT_XMPP_PASSWORD_ENV = "ASKY_XMPP_PASSWORD"

console = Console()
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DaemonSettings:
    """Minimal daemon settings needed for startup."""

    enabled: bool
    jid: str
    password: str
    password_env: str
    allowed_jids: list[str]

    def effective_password(self) -> str:
        """Return password from file or configured environment variable."""
        env_name = str(self.password_env or DEFAULT_XMPP_PASSWORD_ENV).strip()
        from_env = os.environ.get(env_name, "")
        if str(from_env).strip():
            return str(from_env)
        return str(self.password or "")

    def has_minimum_requirements(self) -> bool:
        return bool(
            self.jid.strip()
            and self.effective_password().strip()
            and self.allowed_jids
        )


def _xmpp_config_path() -> Path:
    return _get_config_dir() / XMPP_CONFIG_FILENAME


def _load_toml_document(path: Path) -> tomlkit.TOMLDocument:
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("[xmpp]\n")
    content = path.read_text()
    return tomlkit.parse(content or "[xmpp]\n")


def _normalized_allowed_jids(raw: str) -> list[str]:
    if not raw.strip():
        return []
    items = []
    seen = set()
    for line in raw.replace(",", "\n").splitlines():
        normalized = line.strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        items.append(normalized)
    return items


def get_daemon_settings() -> DaemonSettings:
    """Load current daemon settings from xmpp.toml."""
    path = _xmpp_config_path()
    if not path.exists():
        logger.debug("xmpp config file is missing: %s", path)
        return DaemonSettings(
            enabled=False,
            jid="",
            password="",
            password_env=DEFAULT_XMPP_PASSWORD_ENV,
            allowed_jids=[],
        )
    with path.open("rb") as handle:
        parsed = tomllib.load(handle)
    xmpp = parsed.get("xmpp", {}) if isinstance(parsed, dict) else {}
    return DaemonSettings(
        enabled=bool(xmpp.get("enabled", False)),
        jid=str(xmpp.get("jid", "") or "").strip(),
        password=str(xmpp.get("password", "") or "").strip(),
        password_env=str(
            xmpp.get("password_env", DEFAULT_XMPP_PASSWORD_ENV)
            or DEFAULT_XMPP_PASSWORD_ENV
        ).strip(),
        allowed_jids=[
            str(value).strip()
            for value in xmpp.get("allowed_jids", [])
            if str(value).strip()
        ],
    )


def update_daemon_settings(
    *,
    enabled: Optional[bool] = None,
    jid: Optional[str] = None,
    password: Optional[str] = None,
    allowed_jids: Optional[list[str]] = None,
) -> DaemonSettings:
    """Persist daemon settings into xmpp.toml."""
    path = _xmpp_config_path()
    doc = _load_toml_document(path)
    if "xmpp" not in doc:
        doc["xmpp"] = tomlkit.table()
    xmpp = doc["xmpp"]
    current = get_daemon_settings()
    logger.debug(
        "updating daemon settings enabled=%s jid=%s allowed_count=%s",
        enabled if enabled is not None else current.enabled,
        jid if jid is not None else current.jid,
        len(allowed_jids if allowed_jids is not None else current.allowed_jids),
    )

    xmpp["enabled"] = bool(current.enabled if enabled is None else enabled)
    xmpp["jid"] = current.jid if jid is None else str(jid).strip()
    xmpp["password"] = current.password if password is None else str(password)
    xmpp["allowed_jids"] = (
        list(current.allowed_jids) if allowed_jids is None else list(allowed_jids)
    )

    path.write_text(doc.as_string())
    logger.debug("saved xmpp daemon config at %s", path)
    return get_daemon_settings()


def edit_daemon_command() -> None:
    """Interactively edit daemon settings for any supported OS."""
    current = get_daemon_settings()
    startup_status = startup.get_status()
    logger.debug(
        "starting interactive daemon editor enabled=%s jid=%s allowed_count=%s startup_supported=%s startup_enabled=%s",
        current.enabled,
        current.jid,
        len(current.allowed_jids),
        startup_status.supported,
        startup_status.enabled,
    )

    console.print("[bold]Edit Daemon Configuration[/bold]\n")
    console.print(f"Current daemon enabled: {current.enabled}")
    console.print(f"Current JID: {current.jid or '(empty)'}")
    console.print(f"Allowed users count: {len(current.allowed_jids)}")
    if startup_status.supported:
        console.print(f"Run at login: {startup_status.enabled}")
    else:
        console.print(f"Run at login: unsupported ({startup_status.platform_name})")

    enabled = Confirm.ask("Enable XMPP daemon", default=current.enabled)
    jid = Prompt.ask("XMPP JID", default=current.jid)
    password_default = current.password if current.password else ""
    password = Prompt.ask("XMPP Password", default=password_default, password=True)
    allowlist_default = ",".join(current.allowed_jids)
    allowed_raw = Prompt.ask(
        "Allowed users (comma-separated bare/full JIDs)",
        default=allowlist_default,
    )
    allowed = _normalized_allowed_jids(allowed_raw)

    updated = update_daemon_settings(
        enabled=enabled,
        jid=jid,
        password=password,
        allowed_jids=allowed,
    )
    if not updated.has_minimum_requirements():
        console.print(
            "[yellow]Warning: daemon start requires jid, password (or password_env), and at least one allowed user.[/yellow]"
        )
    logger.debug(
        "daemon editor saved enabled=%s jid=%s allowed_count=%s minimum_ready=%s",
        updated.enabled,
        updated.jid,
        len(updated.allowed_jids),
        updated.has_minimum_requirements(),
    )

    if startup_status.supported:
        startup_default = startup_status.enabled
        set_startup = Confirm.ask("Run at login", default=startup_default)
        if set_startup:
            state = startup.enable_startup()
            logger.debug(
                "startup enable result supported=%s enabled=%s active=%s details=%s",
                state.supported,
                state.enabled,
                state.active,
                state.details,
            )
            if state.enabled:
                console.print("[green]Startup at login enabled.[/green]")
            else:
                console.print(f"[yellow]Could not enable startup: {state.details}[/yellow]")
        else:
            state = startup.disable_startup()
            logger.debug(
                "startup disable result supported=%s enabled=%s active=%s details=%s",
                state.supported,
                state.enabled,
                state.active,
                state.details,
            )
            if not state.enabled:
                console.print("[green]Startup at login disabled.[/green]")
            else:
                console.print(f"[yellow]Could not disable startup: {state.details}[/yellow]")

    console.print("[green]Daemon configuration saved.[/green]")
