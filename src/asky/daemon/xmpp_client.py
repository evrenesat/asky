"""Thin XMPP client wrapper around slixmpp for daemon mode."""

from __future__ import annotations

import inspect
import logging
from typing import Callable, Optional

from asky.daemon.errors import DaemonUserError

logger = logging.getLogger(__name__)
OOB_XML_NAMESPACES = ("jabber:x:oob", "urn:xmpp:oob")
MUC_USER_NAMESPACE = "http://jabber.org/protocol/muc#user"

try:
    import slixmpp  # type: ignore
except ImportError:
    slixmpp = None  # type: ignore[assignment]


class AskyXMPPClient:
    """Foreground XMPP client that forwards inbound stanzas to callbacks."""

    def __init__(
        self,
        *,
        jid: str,
        password: str,
        host: str,
        port: int,
        resource: str,
        message_callback: Callable[[dict], None],
        session_start_callback: Optional[Callable[[], None]] = None,
    ):
        if slixmpp is None:
            raise DaemonUserError(
                "XMPP dependency missing: slixmpp is not installed.",
                hint="Install asky-cli[xmpp] or asky-cli[mac].",
            )
        if not jid or not password:
            raise DaemonUserError(
                "XMPP credentials are not configured.",
                hint="Run asky --edit-daemon to set jid/password/allowlist.",
            )

        self._message_callback = message_callback
        self._session_start_callback = session_start_callback
        full_jid = jid if not resource else f"{jid}/{resource}"
        self._client = slixmpp.ClientXMPP(full_jid, password)
        self._host = host
        self._port = int(port)
        self._nick = str(resource or "asky").strip() or "asky"

        register_plugin = getattr(self._client, "register_plugin", None)
        if callable(register_plugin):
            try:
                register_plugin("xep_0045")
            except Exception:
                logger.debug("failed to register xep_0045 plugin", exc_info=True)

        self._client.add_event_handler("session_start", self._on_session_start)
        self._client.add_event_handler("message", self._on_message)

    def _on_session_start(self, _event) -> None:
        self._client.send_presence()
        self._client.get_roster()
        if self._session_start_callback is not None:
            self._session_start_callback()

    def _on_message(self, msg) -> None:
        from_jid = _full_jid(msg.get("from"))
        message_type = str(msg.get("type", "") or "")
        oob_urls = _extract_oob_urls(msg)
        room_jid = _room_jid_from_message(from_jid, message_type)
        sender_nick = _sender_nick_from_message(from_jid, message_type)
        sender_jid = _extract_group_sender_jid(msg)
        invite_room, invite_from = _extract_group_invite(msg)
        payload = {
            "from_jid": from_jid,
            "type": message_type,
            "body": str(msg.get("body", "") or ""),
            "audio_url": _extract_oob_url(msg),
            "oob_urls": oob_urls,
            "room_jid": room_jid,
            "sender_nick": sender_nick,
            "sender_jid": sender_jid,
            "invite_room_jid": invite_room,
            "invite_from_jid": invite_from,
        }
        self._message_callback(payload)

    def start_foreground(self) -> None:
        """Connect and enter processing loop."""
        logger.info("xmpp client starting foreground host=%s port=%s", self._host, self._port)
        connected = _connect_client(self._client, self._host, self._port)
        connected = _resolve_connect_result(self._client, connected)
        if connected is False:
            logger.error("xmpp client connect returned false")
            raise DaemonUserError(
                "Failed to connect to XMPP server.",
                hint="Check xmpp host/port/jid/password and network reachability.",
            )
        logger.debug("xmpp client connected successfully; entering runtime loop")
        _run_client_forever(self._client)

    def stop(self) -> None:
        """Attempt graceful shutdown for foreground loop."""
        logger.info("xmpp client stop requested")
        _disconnect_client(self._client)

    def send_chat_message(self, to_jid: str, body: str) -> None:
        self.send_message(to_jid=to_jid, body=body, message_type="chat")

    def send_group_message(self, room_jid: str, body: str) -> None:
        self.send_message(to_jid=room_jid, body=body, message_type="groupchat")

    def send_message(self, *, to_jid: str, body: str, message_type: str) -> None:
        payload = {
            "mto": to_jid,
            "mbody": str(body or ""),
            "mtype": str(message_type or "chat"),
        }
        _dispatch_client_send(self._client, payload)

    def join_room(self, room_jid: str) -> None:
        normalized_room = str(room_jid or "").strip()
        if not normalized_room:
            return
        muc_plugin = _get_muc_plugin(self._client)
        if muc_plugin is None:
            logger.debug("xep_0045 plugin is not available; cannot join room=%s", room_jid)
            return
        join_method = getattr(muc_plugin, "join_muc", None)
        if not callable(join_method):
            logger.debug("xep_0045 plugin has no join_muc(); room=%s", room_jid)
            return
        try:
            signature = inspect.signature(join_method)
            if "wait" in signature.parameters:
                join_method(normalized_room, self._nick, wait=False)
                return
        except Exception:
            logger.debug("failed to inspect join_muc signature", exc_info=True)
        try:
            join_method(normalized_room, self._nick)
        except TypeError:
            # Fallback for plugin variants that prefer keyword-only room/nick.
            join_method(room=normalized_room, nick=self._nick)


def _full_jid(from_value) -> str:
    try:
        if hasattr(from_value, "full"):
            return str(from_value.full)
    except Exception:
        pass
    return str(from_value or "")


def _extract_oob_url(msg) -> Optional[str]:
    """Best-effort extraction of media URL from OOB stanza payload."""
    try:
        xml = getattr(msg, "xml", None)
        if xml is None:
            return None

        urls = _extract_oob_urls(msg)
        if urls:
            return urls[0]
    except Exception:
        logger.debug("failed to parse XMPP oob payload", exc_info=True)
    return None


def _extract_oob_urls(msg) -> list[str]:
    """Extract all OOB URLs from the message stanza."""
    xml = getattr(msg, "xml", None)
    if xml is None:
        return []
    urls: list[str] = []
    seen: set[str] = set()
    for namespace in OOB_XML_NAMESPACES:
        for node in xml.findall(f".//{{{namespace}}}url"):
            url = str(getattr(node, "text", "") or "").strip()
            if url and url not in seen:
                seen.add(url)
                urls.append(url)

        for wrapper in xml.findall(f".//{{{namespace}}}x"):
            for child in list(wrapper):
                if _xml_local_name(getattr(child, "tag", "")) != "url":
                    continue
                url = str(getattr(child, "text", "") or "").strip()
                if url and url not in seen:
                    seen.add(url)
                    urls.append(url)
    return urls


def _xml_local_name(tag: str) -> str:
    tag_value = str(tag or "")
    if tag_value.startswith("{") and "}" in tag_value:
        return tag_value.split("}", 1)[1]
    return tag_value


def _room_jid_from_message(from_jid: str, message_type: str) -> str:
    if str(message_type or "").strip().lower() != "groupchat":
        return ""
    return _bare_jid(from_jid)


def _sender_nick_from_message(from_jid: str, message_type: str) -> str:
    if str(message_type or "").strip().lower() != "groupchat":
        return ""
    if "/" not in str(from_jid or ""):
        return ""
    return str(from_jid).split("/", 1)[1]


def _extract_group_sender_jid(msg) -> str:
    """Best effort extraction of real sender JID from MUC user extension."""
    xml = getattr(msg, "xml", None)
    if xml is None:
        return ""
    for item in xml.findall(f".//{{{MUC_USER_NAMESPACE}}}item"):
        jid = str(getattr(item, "attrib", {}).get("jid", "") or "").strip()
        if jid:
            return jid
    return ""


def _extract_group_invite(msg) -> tuple[str, str]:
    """Extract invite target room and inviter JID from MUC user extension."""
    xml = getattr(msg, "xml", None)
    if xml is None:
        return "", ""
    from_value = _full_jid(msg.get("from"))
    room_jid = _bare_jid(from_value)
    for invite in xml.findall(f".//{{{MUC_USER_NAMESPACE}}}invite"):
        inviter = str(getattr(invite, "attrib", {}).get("from", "") or "").strip()
        if inviter:
            return room_jid, inviter
    return "", ""


def _bare_jid(jid: str) -> str:
    normalized = str(jid or "").strip()
    if "/" not in normalized:
        return normalized
    return normalized.split("/", 1)[0]


def _get_muc_plugin(client):
    plugins = getattr(client, "plugin", None)
    if plugins is None:
        return None
    if isinstance(plugins, dict):
        return plugins.get("xep_0045")
    try:
        return plugins["xep_0045"]
    except Exception:
        return None


def _resolve_connect_result(client, connected):
    """Resolve sync/async connect results to a boolean-like outcome."""
    if inspect.isawaitable(connected):
        # Some slixmpp versions return an already scheduled asyncio Task/Future.
        if hasattr(connected, "add_done_callback"):
            return True
        loop = getattr(client, "loop", None)
        if loop is not None and hasattr(loop, "create_task"):
            loop.create_task(connected)
            return True
        if loop is not None and hasattr(loop, "run_until_complete"):
            return loop.run_until_complete(connected)
    return connected


def _connect_client(client, host: str, port: int):
    """Connect with host override across slixmpp API variants."""
    connect_method = getattr(client, "connect", None)
    if not callable(connect_method):
        raise RuntimeError("Invalid slixmpp client: missing connect()")

    signature = inspect.signature(connect_method)
    param_names = set(signature.parameters.keys())
    host_value = str(host or "").strip()
    port_value = int(port)

    if "host" in param_names and "port" in param_names:
        if host_value:
            return connect_method(host=host_value, port=port_value)
        return connect_method()

    if "address" in param_names:
        if host_value:
            return connect_method((host_value, port_value))
        return connect_method(())

    if host_value:
        try:
            return connect_method((host_value, port_value))
        except TypeError:
            return connect_method(host_value, port_value)
    return connect_method()


def _run_client_forever(client) -> None:
    """Run the XMPP event loop across slixmpp API variants."""
    process_method = getattr(client, "process", None)
    if callable(process_method):
        process_method(forever=True)
        return

    loop = getattr(client, "loop", None)
    if loop is not None and hasattr(loop, "run_forever"):
        loop.run_forever()
        return

    disconnected = getattr(client, "disconnected", None)
    if disconnected is not None and hasattr(disconnected, "wait"):
        disconnected.wait()
        return

    raise RuntimeError("Unsupported slixmpp client runtime API.")


def _dispatch_client_send(client, payload: dict) -> None:
    """Dispatch outbound stanza on client loop when available."""
    loop = getattr(client, "loop", None)
    send_method = getattr(client, "send_message", None)
    if not callable(send_method):
        raise RuntimeError("Invalid slixmpp client: missing send_message()")

    def _send() -> None:
        send_method(**payload)

    if loop is not None and hasattr(loop, "call_soon_threadsafe"):
        loop.call_soon_threadsafe(_send)
        return
    _send()


def _disconnect_client(client) -> None:
    """Best-effort disconnect across slixmpp runtime variants."""
    disconnect_method = getattr(client, "disconnect", None)
    if callable(disconnect_method):
        try:
            disconnect_method()
        except Exception:
            logger.debug("xmpp disconnect() failed", exc_info=True)
    loop = getattr(client, "loop", None)
    if loop is not None and hasattr(loop, "call_soon_threadsafe") and hasattr(loop, "stop"):
        try:
            loop.call_soon_threadsafe(loop.stop)
        except Exception:
            logger.debug("xmpp loop stop failed", exc_info=True)
