"""XMPP client compatibility tests."""

import xml.etree.ElementTree as ET
from types import SimpleNamespace

import asky.daemon.xmpp_client as xmpp_client


class _Loop:
    def __init__(self):
        self.run_forever_called = False
        self.created_tasks = []
        self.threadsafe_callbacks = []
        self.stop_called = False

    def run_forever(self):
        self.run_forever_called = True

    def create_task(self, coro):
        self.created_tasks.append(coro)
        close = getattr(coro, "close", None)
        if callable(close):
            close()

    def call_soon_threadsafe(self, callback):
        self.threadsafe_callbacks.append(callback)
        callback()

    def stop(self):
        self.stop_called = True


class _ClientWithProcess:
    def __init__(self, jid, password):
        self.jid = jid
        self.password = password
        self.handlers = {}
        self.connected_to = None
        self.process_called = False
        self.sent_messages = []

    def add_event_handler(self, name, callback):
        self.handlers[name] = callback

    def connect(self, address):
        self.connected_to = address
        return True

    def process(self, forever=True):
        self.process_called = bool(forever)

    def send_message(self, **kwargs):
        self.sent_messages.append(kwargs)


class _ClientWithLoop:
    def __init__(self, jid, password):
        self.jid = jid
        self.password = password
        self.handlers = {}
        self.connected_to = None
        self.loop = _Loop()

    def add_event_handler(self, name, callback):
        self.handlers[name] = callback

    def connect(self, address):
        self.connected_to = address
        return True

    def send_message(self, **kwargs):
        return None


class _ClientConnectFails:
    def __init__(self, jid, password):
        self.handlers = {}

    def add_event_handler(self, name, callback):
        self.handlers[name] = callback

    def connect(self, address):
        return False


class _ClientWithHostPort:
    def __init__(self, jid, password):
        self.jid = jid
        self.password = password
        self.handlers = {}
        self.connected_host = None
        self.connected_port = None
        self.process_called = False
        self.sent_messages = []

    def add_event_handler(self, name, callback):
        self.handlers[name] = callback

    def connect(self, host=None, port=None):
        self.connected_host = host
        self.connected_port = port
        return True

    def process(self, forever=True):
        self.process_called = bool(forever)

    def send_message(self, **kwargs):
        self.sent_messages.append(kwargs)


class _ClientWithAsyncConnect:
    def __init__(self, jid, password):
        self.jid = jid
        self.password = password
        self.handlers = {}
        self.loop = _Loop()
        self.process_called = False
        self.sent_messages = []

    def add_event_handler(self, name, callback):
        self.handlers[name] = callback

    async def connect(self, host=None, port=None):
        return True

    def process(self, forever=True):
        self.process_called = bool(forever)

    def send_message(self, **kwargs):
        self.sent_messages.append(kwargs)


class _AwaitableTaskLike:
    def __await__(self):
        if False:
            yield None
        return True

    def add_done_callback(self, _fn):
        return None


class _ClientWithTaskConnect:
    def __init__(self, jid, password):
        self.jid = jid
        self.password = password
        self.handlers = {}
        self.loop = _Loop()
        self.process_called = False
        self.sent_messages = []

    def add_event_handler(self, name, callback):
        self.handlers[name] = callback

    def connect(self, host=None, port=None):
        return _AwaitableTaskLike()

    def process(self, forever=True):
        self.process_called = bool(forever)

    def send_message(self, **kwargs):
        self.sent_messages.append(kwargs)


class _FakeMessage:
    def __init__(self, xml):
        self.xml = xml


class _MucPlugin:
    def __init__(self):
        self.join_calls = []

    def join_muc(self, room_jid, nick, wait=False):
        self.join_calls.append((room_jid, nick, wait))


class _MucPluginNoWait:
    def __init__(self):
        self.join_calls = []

    def join_muc(self, room_jid, nick):
        self.join_calls.append((room_jid, nick))


class _ClientWithMucSupport:
    def __init__(self, jid, password):
        self.jid = jid
        self.password = password
        self.handlers = {}
        self.loop = _Loop()
        self.plugin = {"xep_0045": _MucPlugin()}

    def add_event_handler(self, name, callback):
        self.handlers[name] = callback

    def register_plugin(self, _name):
        return None

    def connect(self, host=None, port=None):
        _ = (host, port)
        return True

    def process(self, forever=True):
        _ = forever

    def send_message(self, **kwargs):
        _ = kwargs

    def disconnect(self):
        return None


class _ClientWithMucSupportNoWait:
    def __init__(self, jid, password):
        self.jid = jid
        self.password = password
        self.handlers = {}
        self.loop = _Loop()
        self.plugin = {"xep_0045": _MucPluginNoWait()}

    def add_event_handler(self, name, callback):
        self.handlers[name] = callback

    def register_plugin(self, _name):
        return None

    def connect(self, host=None, port=None):
        _ = (host, port)
        return True

    def process(self, forever=True):
        _ = forever

    def send_message(self, **kwargs):
        _ = kwargs

    def disconnect(self):
        return None


def test_start_foreground_uses_process_api(monkeypatch):
    module = SimpleNamespace(ClientXMPP=_ClientWithProcess)
    monkeypatch.setattr(xmpp_client, "slixmpp", module)
    client = xmpp_client.AskyXMPPClient(
        jid="bot@example.com",
        password="secret",
        host="xmpp.example.com",
        port=5222,
        resource="asky",
        message_callback=lambda _payload: None,
    )

    client.start_foreground()
    assert client._client.process_called is True


def test_stop_requests_disconnect_and_loop_stop(monkeypatch):
    module = SimpleNamespace(ClientXMPP=_ClientWithMucSupport)
    monkeypatch.setattr(xmpp_client, "slixmpp", module)
    client = xmpp_client.AskyXMPPClient(
        jid="bot@example.com",
        password="secret",
        host="xmpp.example.com",
        port=5222,
        resource="asky",
        message_callback=lambda _payload: None,
    )

    client.stop()
    assert client._client.loop.stop_called is True


def test_start_foreground_falls_back_to_loop_run_forever(monkeypatch):
    module = SimpleNamespace(ClientXMPP=_ClientWithLoop)
    monkeypatch.setattr(xmpp_client, "slixmpp", module)
    client = xmpp_client.AskyXMPPClient(
        jid="bot@example.com",
        password="secret",
        host="xmpp.example.com",
        port=5222,
        resource="asky",
        message_callback=lambda _payload: None,
    )

    client.start_foreground()
    assert client._client.loop.run_forever_called is True


def test_start_foreground_connect_failure_raises(monkeypatch):
    module = SimpleNamespace(ClientXMPP=_ClientConnectFails)
    monkeypatch.setattr(xmpp_client, "slixmpp", module)
    client = xmpp_client.AskyXMPPClient(
        jid="bot@example.com",
        password="secret",
        host="",
        port=5222,
        resource="asky",
        message_callback=lambda _payload: None,
    )

    try:
        client.start_foreground()
    except RuntimeError as exc:
        assert "failed to connect" in str(exc).lower()
    else:
        raise AssertionError("Expected RuntimeError for failed connect.")


def test_start_foreground_uses_host_port_connect_signature(monkeypatch):
    module = SimpleNamespace(ClientXMPP=_ClientWithHostPort)
    monkeypatch.setattr(xmpp_client, "slixmpp", module)
    client = xmpp_client.AskyXMPPClient(
        jid="bot@example.com",
        password="secret",
        host="xmpp.example.com",
        port=5222,
        resource="asky",
        message_callback=lambda _payload: None,
    )

    client.start_foreground()
    assert client._client.connected_host == "xmpp.example.com"
    assert client._client.connected_port == 5222


def test_start_foreground_schedules_async_connect(monkeypatch):
    module = SimpleNamespace(ClientXMPP=_ClientWithAsyncConnect)
    monkeypatch.setattr(xmpp_client, "slixmpp", module)
    client = xmpp_client.AskyXMPPClient(
        jid="bot@example.com",
        password="secret",
        host="xmpp.example.com",
        port=5222,
        resource="asky",
        message_callback=lambda _payload: None,
    )

    client.start_foreground()
    assert len(client._client.loop.created_tasks) == 1
    assert client._client.process_called is True


def test_start_foreground_does_not_reschedule_task_like_connect(monkeypatch):
    module = SimpleNamespace(ClientXMPP=_ClientWithTaskConnect)
    monkeypatch.setattr(xmpp_client, "slixmpp", module)
    client = xmpp_client.AskyXMPPClient(
        jid="bot@example.com",
        password="secret",
        host="xmpp.example.com",
        port=5222,
        resource="asky",
        message_callback=lambda _payload: None,
    )

    client.start_foreground()
    assert len(client._client.loop.created_tasks) == 0
    assert client._client.process_called is True


def test_extract_oob_url_from_namespaced_url_node():
    root = ET.Element("message")
    oob = ET.SubElement(root, "{jabber:x:oob}x")
    url_node = ET.SubElement(oob, "{jabber:x:oob}url")
    url_node.text = "https://example.com/audio.m4a"

    url = xmpp_client._extract_oob_url(_FakeMessage(root))
    assert url == "https://example.com/audio.m4a"


def test_extract_oob_url_from_x_wrapper_with_plain_url_child():
    root = ET.Element("message")
    oob = ET.SubElement(root, "{urn:xmpp:oob}x")
    url_node = ET.SubElement(oob, "url")
    url_node.text = "https://example.com/audio.ogg"

    url = xmpp_client._extract_oob_url(_FakeMessage(root))
    assert url == "https://example.com/audio.ogg"


def test_send_chat_message_uses_loop_threadsafe_dispatch(monkeypatch):
    module = SimpleNamespace(ClientXMPP=_ClientWithTaskConnect)
    monkeypatch.setattr(xmpp_client, "slixmpp", module)
    client = xmpp_client.AskyXMPPClient(
        jid="bot@example.com",
        password="secret",
        host="xmpp.example.com",
        port=5222,
        resource="asky",
        message_callback=lambda _payload: None,
    )

    client.send_chat_message("u@example.com/resource", "hello")
    assert len(client._client.loop.threadsafe_callbacks) == 1
    assert client._client.sent_messages == [
        {"mto": "u@example.com/resource", "mbody": "hello", "mtype": "chat"}
    ]


def test_extract_group_invite_from_muc_user_extension():
    root = ET.Element("message")
    x = ET.SubElement(root, "{http://jabber.org/protocol/muc#user}x")
    invite = ET.SubElement(x, "{http://jabber.org/protocol/muc#user}invite")
    invite.set("from", "owner@example.com/resource")
    msg = SimpleNamespace(xml=root)
    msg.get = lambda key, default=None: "room@conference.example.com/inviter" if key == "from" else default

    room_jid, inviter = xmpp_client._extract_group_invite(msg)
    assert room_jid == "room@conference.example.com"
    assert inviter == "owner@example.com/resource"


def test_join_room_uses_xep0045_plugin(monkeypatch):
    module = SimpleNamespace(ClientXMPP=_ClientWithMucSupport)
    monkeypatch.setattr(xmpp_client, "slixmpp", module)
    client = xmpp_client.AskyXMPPClient(
        jid="bot@example.com",
        password="secret",
        host="xmpp.example.com",
        port=5222,
        resource="asky",
        message_callback=lambda _payload: None,
    )
    client.join_room("room@conference.example.com")
    plugin = client._client.plugin["xep_0045"]
    assert plugin.join_calls == [("room@conference.example.com", "asky", False)]


def test_join_room_supports_xep0045_without_wait_param(monkeypatch):
    module = SimpleNamespace(ClientXMPP=_ClientWithMucSupportNoWait)
    monkeypatch.setattr(xmpp_client, "slixmpp", module)
    client = xmpp_client.AskyXMPPClient(
        jid="bot@example.com",
        password="secret",
        host="xmpp.example.com",
        port=5222,
        resource="asky",
        message_callback=lambda _payload: None,
    )
    client.join_room("room@conference.example.com")
    plugin = client._client.plugin["xep_0045"]
    assert plugin.join_calls == [("room@conference.example.com", "asky")]
