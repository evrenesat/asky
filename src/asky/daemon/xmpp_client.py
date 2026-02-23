"""Thin XMPP client wrapper around slixmpp for daemon mode."""

from __future__ import annotations

import inspect
import logging
from typing import Callable, Optional

logger = logging.getLogger(__name__)
OOB_XML_NAMESPACES = ("jabber:x:oob", "urn:xmpp:oob")

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
    ):
        if slixmpp is None:
            raise RuntimeError(
                "slixmpp is required for XMPP daemon mode. Install asky-cli[xmpp]."
            )
        if not jid or not password:
            raise RuntimeError("XMPP credentials are not configured.")

        self._message_callback = message_callback
        full_jid = jid if not resource else f"{jid}/{resource}"
        self._client = slixmpp.ClientXMPP(full_jid, password)
        self._host = host
        self._port = int(port)

        self._client.add_event_handler("session_start", self._on_session_start)
        self._client.add_event_handler("message", self._on_message)

    def _on_session_start(self, _event) -> None:
        self._client.send_presence()
        self._client.get_roster()

    def _on_message(self, msg) -> None:
        from_jid = _full_jid(msg.get("from"))
        payload = {
            "from_jid": from_jid,
            "type": str(msg.get("type", "") or ""),
            "body": str(msg.get("body", "") or ""),
            "audio_url": _extract_oob_url(msg),
        }
        self._message_callback(payload)

    def start_foreground(self) -> None:
        """Connect and enter processing loop."""
        connected = _connect_client(self._client, self._host, self._port)
        connected = _resolve_connect_result(self._client, connected)
        if connected is False:
            raise RuntimeError("Failed to connect to XMPP server.")
        _run_client_forever(self._client)

    def send_chat_message(self, to_jid: str, body: str) -> None:
        payload = {
            "mto": to_jid,
            "mbody": str(body or ""),
            "mtype": "chat",
        }
        _dispatch_client_send(self._client, payload)


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

        for namespace in OOB_XML_NAMESPACES:
            for node in xml.findall(f".//{{{namespace}}}url"):
                url = str(getattr(node, "text", "") or "").strip()
                if url:
                    return url

            for wrapper in xml.findall(f".//{{{namespace}}}x"):
                for child in list(wrapper):
                    if _xml_local_name(getattr(child, "tag", "")) != "url":
                        continue
                    url = str(getattr(child, "text", "") or "").strip()
                    if url:
                        return url
    except Exception:
        logger.debug("failed to parse XMPP oob payload", exc_info=True)
    return None


def _xml_local_name(tag: str) -> str:
    tag_value = str(tag or "")
    if tag_value.startswith("{") and "}" in tag_value:
        return tag_value.split("}", 1)[1]
    return tag_value


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
