"""Thin XMPP client wrapper around slixmpp for daemon mode."""

from __future__ import annotations

import asyncio
import inspect
import logging
import re
import threading
import uuid
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Callable, Optional

from asky.daemon.errors import DaemonUserError

logger = logging.getLogger(__name__)
OOB_XML_NAMESPACES = ("jabber:x:oob", "urn:xmpp:oob")
MUC_USER_NAMESPACE = "http://jabber.org/protocol/muc#user"
DISCO_INFO_NAMESPACE = "http://jabber.org/protocol/disco#info"
XEP0004_DATA_FORM_NAMESPACE = "jabber:x:data"
DISCO_TIMEOUT_SECONDS = 3
XEP0004_CAPABILITY = "xep_0004"
RESOURCE_TOKEN_SPLIT_PATTERN = re.compile(r"[^a-z0-9]+")
XHTML_IM_NAMESPACE = "http://jabber.org/protocol/xhtml-im"
XHTML_BODY_NAMESPACE = "http://www.w3.org/1999/xhtml"

try:
    import slixmpp  # type: ignore
except ImportError:
    slixmpp = None  # type: ignore[assignment]


@dataclass(frozen=True)
class StatusMessageHandle:
    """Handle for updating a previously sent status message."""

    message_id: str
    to_jid: str
    message_type: str
    correction_supported: bool


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
        client_capabilities: Optional[dict[str, object]] = None,
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
        self._xep0004_support_cache: dict[str, bool] = {}
        self._xep0004_support_lock = threading.Lock()
        self._client_capabilities = _normalize_client_capabilities(client_capabilities)

        register_plugin = getattr(self._client, "register_plugin", None)
        if callable(register_plugin):
            for _plugin_name in (
                "xep_0045",
                "xep_0050",
                "xep_0004",
                "xep_0030",
                "xep_0071",
                "xep_0308",
                "xep_0363",
            ):
                try:
                    register_plugin(_plugin_name)
                except Exception:
                    logger.debug(
                        "failed to register %s plugin", _plugin_name, exc_info=True
                    )

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
        logger.info(
            "xmpp client starting foreground host=%s port=%s", self._host, self._port
        )
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

    def get_plugin(self, name: str):
        """Return a registered slixmpp plugin by name, or None."""
        plugins = getattr(self._client, "plugin", None)
        if plugins is None:
            return None
        try:
            return plugins[name]
        except Exception:
            return None

    @property
    def loop(self):
        """Return the underlying asyncio event loop, or None."""
        return getattr(self._client, "loop", None)

    def send_chat_message(self, to_jid: str, body: str) -> None:
        self.send_message(to_jid=to_jid, body=body, message_type="chat")

    def send_group_message(self, room_jid: str, body: str) -> None:
        self.send_message(to_jid=room_jid, body=body, message_type="groupchat")

    def send_message(
        self,
        *,
        to_jid: str,
        body: str,
        message_type: str,
        message_id: Optional[str] = None,
        replace_id: Optional[str] = None,
        xhtml_body: Optional[str] = None,
    ) -> None:
        normalized_message_id = str(message_id or "").strip()
        normalized_replace_id = str(replace_id or "").strip()
        normalized_xhtml_body = str(xhtml_body or "").strip()
        if normalized_message_id or normalized_replace_id or normalized_xhtml_body:
            try:
                _dispatch_client_send_stanza(
                    self._client,
                    to_jid=to_jid,
                    body=str(body or ""),
                    message_type=str(message_type or "chat"),
                    message_id=normalized_message_id or None,
                    replace_id=normalized_replace_id or None,
                    xhtml_body=normalized_xhtml_body or None,
                )
                return
            except Exception:
                if normalized_replace_id:
                    raise
                logger.debug(
                    "failed to send stanza with explicit id; falling back",
                    exc_info=True,
                )
        payload = {
            "mto": to_jid,
            "mbody": str(body or ""),
            "mtype": str(message_type or "chat"),
        }
        _dispatch_client_send(self._client, payload)

    def supports_message_correction(self) -> bool:
        return self.get_plugin("xep_0308") is not None

    def supports_xep0004_data_forms(self, to_jid: str) -> bool:
        target_jid = str(to_jid or "").strip()
        if not target_jid:
            return False
        cache_key = _capability_cache_key(target_jid)
        with self._xep0004_support_lock:
            cached = self._xep0004_support_cache.get(cache_key)
        if cached is not None:
            return cached
        supported = _probe_data_form_support(
            self._client,
            target_jid,
            client_capabilities=self._client_capabilities,
            capability_name=XEP0004_CAPABILITY,
        )
        if supported:
            with self._xep0004_support_lock:
                self._xep0004_support_cache[cache_key] = True
        logger.debug(
            "xep_0004 support decision jid=%s cache_key=%s supported=%s",
            target_jid,
            cache_key,
            supported,
        )
        return supported

    def send_status_message(
        self,
        *,
        to_jid: str,
        body: str,
        message_type: str,
    ) -> StatusMessageHandle:
        message_id = uuid.uuid4().hex
        self.send_message(
            to_jid=to_jid,
            body=body,
            message_type=message_type,
            message_id=message_id,
        )
        return StatusMessageHandle(
            message_id=message_id,
            to_jid=str(to_jid or "").strip(),
            message_type=str(message_type or "chat").strip().lower() or "chat",
            correction_supported=self.supports_message_correction(),
        )

    def update_status_message(
        self,
        handle: StatusMessageHandle,
        *,
        body: str,
    ) -> StatusMessageHandle:
        new_message_id = uuid.uuid4().hex
        if handle.correction_supported and handle.message_id:
            try:
                self.send_message(
                    to_jid=handle.to_jid,
                    body=body,
                    message_type=handle.message_type,
                    message_id=new_message_id,
                    replace_id=handle.message_id,
                )
                return StatusMessageHandle(
                    message_id=new_message_id,
                    to_jid=handle.to_jid,
                    message_type=handle.message_type,
                    correction_supported=True,
                )
            except Exception:
                logger.debug(
                    "status correction send failed, falling back", exc_info=True
                )
                correction_supported = False
        else:
            correction_supported = handle.correction_supported
        self.send_message(
            to_jid=handle.to_jid,
            body=body,
            message_type=handle.message_type,
            message_id=new_message_id,
        )
        return StatusMessageHandle(
            message_id=new_message_id,
            to_jid=handle.to_jid,
            message_type=handle.message_type,
            correction_supported=correction_supported,
        )

    def join_room(self, room_jid: str) -> None:
        normalized_room = str(room_jid or "").strip()
        if not normalized_room:
            return
        muc_plugin = _get_muc_plugin(self._client)
        if muc_plugin is None:
            logger.debug(
                "xep_0045 plugin is not available; cannot join room=%s", room_jid
            )
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

    def upload_file(self, file_path: str, *, content_type: str = "") -> str:
        """Upload a local file using XEP-0363 and return the download URL."""
        if self.loop is None:
            raise DaemonUserError("XMPP client is not connected (loop is None).")

        plugin = self.get_plugin("xep_0363")
        if plugin is None:
            raise DaemonUserError(
                "XMPP upload service not available (xep_0363 plugin not loaded)."
            )

        import os

        if not os.path.exists(file_path):
            raise FileNotFoundError(f"File not found: {file_path}")

        file_size = os.path.getsize(file_path)
        filename = os.path.basename(file_path)

        async def _upload():
            with open(file_path, "rb") as f:
                # slixmpp xep_0363.upload_file signature:
                # upload_file(filename, size, content_type, input=None, ...)
                try:
                    return await plugin.upload_file(
                        filename,
                        file_size,
                        content_type,
                        input=f,
                    )
                except TypeError:
                    # Fallback for older slixmpp variants
                    return await plugin.upload_file(
                        name=filename,
                        size=file_size,
                        mime_type=content_type,
                        file=f,
                    )

        future = asyncio.run_coroutine_threadsafe(_upload(), self.loop)
        try:
            return future.result(timeout=60)
        except Exception as e:
            logger.debug("XMPP file upload failed: %s", e, exc_info=True)
            raise

    def send_oob_message(
        self, *, to_jid: str, url: str, body: str, message_type: str
    ) -> None:
        """Send a message with an OOB x element (XEP-0066)."""
        make_message = getattr(self._client, "make_message", None)
        if not callable(make_message):
            raise RuntimeError("Invalid slixmpp client: missing make_message()")

        msg = make_message(mto=to_jid, mbody=body, mtype=message_type)
        x_node = ET.Element("{jabber:x:oob}x")
        url_node = ET.SubElement(x_node, "{jabber:x:oob}url")
        url_node.text = url
        msg.xml.append(x_node)

        _dispatch_client_send_stanza_direct(self._client, msg)


def _dispatch_client_send_stanza_direct(client, msg) -> None:
    """Dispatch an already constructed message stanza on client loop."""
    loop = getattr(client, "loop", None)
    send = getattr(msg, "send", None)
    if not callable(send):
        raise RuntimeError("Invalid slixmpp stanza: missing send()")

    if loop is not None and hasattr(loop, "call_soon_threadsafe"):
        loop.call_soon_threadsafe(send)
        return
    send()


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


def _dispatch_client_send_stanza(
    client,
    *,
    to_jid: str,
    body: str,
    message_type: str,
    message_id: Optional[str],
    replace_id: Optional[str],
    xhtml_body: Optional[str] = None,
) -> None:
    """Dispatch a constructed message stanza (supports XEP-0308 replace)."""
    loop = getattr(client, "loop", None)
    make_message = getattr(client, "make_message", None)
    if not callable(make_message):
        raise RuntimeError("Invalid slixmpp client: missing make_message()")

    def _send() -> None:
        msg = make_message(mto=to_jid, mbody=body, mtype=message_type)
        if message_id:
            msg["id"] = message_id
        if replace_id:
            msg["replace"]["id"] = replace_id
        if xhtml_body:
            _attach_xhtml_payload(msg, xhtml_body)
        send = getattr(msg, "send", None)
        if not callable(send):
            raise RuntimeError("Invalid slixmpp stanza: missing send()")
        send()

    if loop is not None and hasattr(loop, "call_soon_threadsafe"):
        loop.call_soon_threadsafe(_send)
        return
    _send()


def _attach_xhtml_payload(msg, xhtml_body: str) -> None:
    stanza_xml = getattr(msg, "xml", None)
    if stanza_xml is None:
        raise RuntimeError("Invalid slixmpp stanza: missing xml payload")
    html_node = ET.Element(f"{{{XHTML_IM_NAMESPACE}}}html")
    body_node = ET.SubElement(html_node, f"{{{XHTML_BODY_NAMESPACE}}}body")
    fragment_text = str(xhtml_body or "").strip()
    if fragment_text:
        wrapped = f"<root>{fragment_text}</root>"
        root = ET.fromstring(wrapped)
        body_node.text = root.text
        for child in list(root):
            root.remove(child)
            body_node.append(child)
    stanza_xml.append(html_node)


def _probe_data_form_support(
    client,
    to_jid: str,
    *,
    client_capabilities: dict[str, set[str]],
    capability_name: str,
) -> bool:
    disco_plugin = _get_disco_plugin(client)
    if disco_plugin is None:
        return False
    get_info = getattr(disco_plugin, "get_info", None)
    if not callable(get_info):
        return False
    for candidate_jid in _disco_jid_candidates(to_jid):
        try:
            info = _call_disco_get_info(get_info, candidate_jid)
        except Exception:
            logger.debug(
                "xep_0030 disco probing failed for jid=%s (candidate=%s)",
                to_jid,
                candidate_jid,
                exc_info=True,
            )
            continue
        features = _extract_disco_features(info)
        identity_tokens = _extract_disco_identity_tokens(info)
        if not identity_tokens:
            identity_tokens.update(_extract_jid_resource_identity_tokens(candidate_jid))
        matched_capabilities = _resolve_capabilities_for_identity_tokens(
            identity_tokens,
            client_capabilities,
        )
        logger.debug(
            "xep_0030 disco features jid=%s candidate=%s features=%s identity_tokens=%s matched_capabilities=%s",
            to_jid,
            candidate_jid,
            sorted(features),
            sorted(identity_tokens),
            sorted(matched_capabilities),
        )
        if _capability_enabled(matched_capabilities, capability_name):
            return True
        if XEP0004_DATA_FORM_NAMESPACE in features:
            return True
    return False


def _disco_jid_candidates(to_jid: str) -> list[str]:
    normalized = str(to_jid or "").strip()
    if not normalized:
        return []
    bare = _bare_jid(normalized)
    candidates = [normalized]
    if bare and bare != normalized:
        candidates.append(bare)
    return candidates


def _capability_cache_key(to_jid: str) -> str:
    normalized = str(to_jid or "").strip()
    if not normalized:
        return ""
    return _bare_jid(normalized)


def _get_disco_plugin(client):
    plugins = getattr(client, "plugin", None)
    if plugins is None:
        return None
    if isinstance(plugins, dict):
        return plugins.get("xep_0030")
    try:
        return plugins["xep_0030"]
    except Exception:
        return None


def _call_disco_get_info(get_info, to_jid: str):
    signature = inspect.signature(get_info)
    kwargs = {}
    parameters = set(signature.parameters.keys())
    if "jid" in parameters:
        kwargs["jid"] = to_jid
    if "block" in parameters:
        kwargs["block"] = True
    if "timeout" in parameters:
        kwargs["timeout"] = DISCO_TIMEOUT_SECONDS
    if kwargs:
        return get_info(**kwargs)
    return get_info(to_jid)


def _extract_disco_features(info_payload) -> set[str]:
    features: set[str] = set()
    if info_payload is None:
        return features

    feature_values = getattr(info_payload, "features", None)
    if isinstance(feature_values, (list, tuple, set)):
        for value in feature_values:
            normalized = str(value or "").strip()
            if normalized:
                features.add(normalized)

    get_features = getattr(info_payload, "get_features", None)
    if callable(get_features):
        try:
            method_values = get_features()
            if isinstance(method_values, (list, tuple, set)):
                for value in method_values:
                    normalized = str(value or "").strip()
                    if normalized:
                        features.add(normalized)
        except Exception:
            logger.debug(
                "failed reading disco features via get_features()", exc_info=True
            )

    if hasattr(info_payload, "xml"):
        xml = getattr(info_payload, "xml", None)
        if xml is not None:
            for feature_node in xml.findall(f".//{{{DISCO_INFO_NAMESPACE}}}feature"):
                value = str(
                    getattr(feature_node, "attrib", {}).get("var", "") or ""
                ).strip()
                if value:
                    features.add(value)
    if isinstance(info_payload, dict):
        nested_features = info_payload.get("features")
        if isinstance(nested_features, (list, tuple, set)):
            for value in nested_features:
                normalized = str(value or "").strip()
                if normalized:
                    features.add(normalized)
    disco_info = None
    try:
        disco_info = info_payload["disco_info"]
    except Exception:
        disco_info = None
    if disco_info is not None:
        nested_values = getattr(disco_info, "features", None)
        if isinstance(nested_values, (list, tuple, set)):
            for value in nested_values:
                normalized = str(value or "").strip()
                if normalized:
                    features.add(normalized)
        nested_get = getattr(disco_info, "get_features", None)
        if callable(nested_get):
            try:
                nested_method_values = nested_get()
                if isinstance(nested_method_values, (list, tuple, set)):
                    for value in nested_method_values:
                        normalized = str(value or "").strip()
                        if normalized:
                            features.add(normalized)
            except Exception:
                logger.debug(
                    "failed reading disco_info features via get_features()",
                    exc_info=True,
                )
    return features


def _extract_disco_identity_tokens(info_payload) -> set[str]:
    identity_tokens: set[str] = set()
    if info_payload is None:
        return identity_tokens
    _collect_identity_tokens(identity_tokens, getattr(info_payload, "identities", None))
    get_identities = getattr(info_payload, "get_identities", None)
    if callable(get_identities):
        try:
            _collect_identity_tokens(identity_tokens, get_identities())
        except Exception:
            logger.debug(
                "failed reading disco identities via get_identities()", exc_info=True
            )
    if hasattr(info_payload, "xml"):
        xml = getattr(info_payload, "xml", None)
        if xml is not None:
            for identity_node in xml.findall(f".//{{{DISCO_INFO_NAMESPACE}}}identity"):
                _add_identity_tokens(
                    identity_tokens,
                    name=getattr(identity_node, "attrib", {}).get("name", ""),
                    category=getattr(identity_node, "attrib", {}).get("category", ""),
                    identity_type=getattr(identity_node, "attrib", {}).get("type", ""),
                )
    if isinstance(info_payload, dict):
        _collect_identity_tokens(identity_tokens, info_payload.get("identities"))
    disco_info = None
    try:
        disco_info = info_payload["disco_info"]
    except Exception:
        disco_info = None
    if disco_info is not None:
        _collect_identity_tokens(
            identity_tokens, getattr(disco_info, "identities", None)
        )
        nested_get = getattr(disco_info, "get_identities", None)
        if callable(nested_get):
            try:
                _collect_identity_tokens(identity_tokens, nested_get())
            except Exception:
                logger.debug(
                    "failed reading disco_info identities via get_identities()",
                    exc_info=True,
                )
    return identity_tokens


def _extract_jid_resource_identity_tokens(jid: str) -> set[str]:
    normalized = str(jid or "").strip().lower()
    if "/" not in normalized:
        return set()
    resource = normalized.split("/", 1)[1].strip()
    if not resource:
        return set()
    tokens = {resource}
    for value in RESOURCE_TOKEN_SPLIT_PATTERN.split(resource):
        token = str(value or "").strip().lower()
        if token:
            tokens.add(token)
    return tokens


def _collect_identity_tokens(identity_tokens: set[str], identities: object) -> None:
    if isinstance(identities, dict):
        iterable = [identities]
    elif isinstance(identities, (list, tuple, set)):
        iterable = list(identities)
    else:
        return
    for entry in iterable:
        if isinstance(entry, dict):
            _add_identity_tokens(
                identity_tokens,
                name=entry.get("name", ""),
                category=entry.get("category", ""),
                identity_type=entry.get("type", ""),
            )
            continue
        _add_identity_tokens(
            identity_tokens,
            name=getattr(entry, "name", ""),
            category=getattr(entry, "category", ""),
            identity_type=getattr(entry, "type", ""),
        )


def _add_identity_tokens(
    identity_tokens: set[str],
    *,
    name: object,
    category: object,
    identity_type: object,
) -> None:
    normalized_name = _normalize_identity_token(name)
    normalized_category = _normalize_identity_token(category)
    normalized_type = _normalize_identity_token(identity_type)
    if normalized_name:
        identity_tokens.add(normalized_name)
    if normalized_category:
        identity_tokens.add(normalized_category)
    if normalized_type:
        identity_tokens.add(normalized_type)
    if normalized_category and normalized_type:
        identity_tokens.add(f"{normalized_category}/{normalized_type}")
    if normalized_category and normalized_type and normalized_name:
        identity_tokens.add(
            f"{normalized_category}/{normalized_type}/{normalized_name}"
        )


def _normalize_identity_token(value: object) -> str:
    return str(value or "").strip().lower()


def _normalize_client_capabilities(
    capabilities: Optional[dict[str, object]],
) -> dict[str, set[str]]:
    normalized: dict[str, set[str]] = {}
    if not isinstance(capabilities, dict):
        return normalized
    for raw_client_id, raw_capabilities in capabilities.items():
        client_id = _normalize_identity_token(raw_client_id)
        if not client_id:
            continue
        capability_values: list[str] = []
        if isinstance(raw_capabilities, str):
            capability_values = [raw_capabilities]
        elif isinstance(raw_capabilities, (list, tuple, set)):
            capability_values = [str(value) for value in raw_capabilities]
        if not capability_values:
            continue
        for raw_capability in capability_values:
            capability = _normalize_capability_token(raw_capability)
            if not capability:
                continue
            normalized.setdefault(client_id, set()).add(capability)
    return normalized


def _normalize_capability_token(value: object) -> str:
    return str(value or "").strip().lower().replace("-", "_")


def _resolve_capabilities_for_identity_tokens(
    identity_tokens: set[str],
    client_capabilities: dict[str, set[str]],
) -> set[str]:
    resolved: set[str] = set()
    for token in identity_tokens:
        resolved.update(client_capabilities.get(token, set()))
    return resolved


def _capability_enabled(capabilities: set[str], capability_name: str) -> bool:
    target = _normalize_capability_token(capability_name)
    if not target:
        return False
    aliases = {target, target.replace("_", "")}
    if target == XEP0004_CAPABILITY:
        aliases.add(_normalize_capability_token(XEP0004_DATA_FORM_NAMESPACE))
    return any(capability in aliases for capability in capabilities)


def _disconnect_client(client) -> None:
    """Best-effort disconnect across slixmpp runtime variants."""
    disconnect_method = getattr(client, "disconnect", None)
    if callable(disconnect_method):
        try:
            disconnect_method()
        except Exception:
            logger.debug("xmpp disconnect() failed", exc_info=True)
    loop = getattr(client, "loop", None)
    if (
        loop is not None
        and hasattr(loop, "call_soon_threadsafe")
        and hasattr(loop, "stop")
    ):
        try:
            loop.call_soon_threadsafe(loop.stop)
        except Exception:
            logger.debug("xmpp loop stop failed", exc_info=True)
