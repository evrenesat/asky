"""Tests for XMPP file upload service (XEP-0363)."""

import asyncio
import os
import xml.etree.ElementTree as ET
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from asky.daemon.errors import DaemonUserError
from asky.plugins.xmpp_daemon.file_upload import (
    FileUploadError,
    FileUploadService,
    get_file_upload_service,
    set_file_upload_service,
)
from asky.plugins.xmpp_daemon.xmpp_client import AskyXMPPClient


class _MockXEP0363:
    def __init__(self, return_url):
        self.return_url = return_url
        self.upload_calls = []

    async def upload_file(self, filename, size, content_type, input=None):
        self.upload_calls.append((filename, size, content_type))
        return self.return_url


class _MockXEP0363Old:
    def __init__(self, return_url):
        self.return_url = return_url
        self.upload_calls = []

    async def upload_file(self, name, size, mime_type, file=None):
        self.upload_calls.append((name, size, mime_type))
        return self.return_url


class _MockLoop:
    def asyncio_run_coroutine_threadsafe(self, coro, loop):
        # Synchronously run for testing
        return MagicMock(result=lambda timeout: asyncio.run(coro))


@pytest.fixture
def mock_client(monkeypatch):
    monkeypatch.setattr("asky.plugins.xmpp_daemon.xmpp_client.slixmpp", MagicMock())
    client = AskyXMPPClient(
        jid="bot@example.com",
        password="password",
        host="localhost",
        port=5222,
        resource="asky",
        message_callback=lambda p: None,
    )
    client._client.loop = MagicMock()
    return client


def test_asky_xmpp_client_upload_file_happy_path(mock_client, tmp_path, monkeypatch):
    test_file = tmp_path / "test.txt"
    test_file.write_text("hello")

    mock_plugin = _MockXEP0363("https://example.com/d/test.txt")
    monkeypatch.setattr(
        mock_client,
        "get_plugin",
        lambda name: mock_plugin if name == "xep_0363" else None,
    )

    # Mock asyncio.run_coroutine_threadsafe
    mock_future = MagicMock()
    mock_future.result.return_value = "https://example.com/d/test.txt"

    def _mock_run(coro, loop):
        coro.close()  # Prevent RuntimeWarning: coroutine was never awaited
        return mock_future

    monkeypatch.setattr("asyncio.run_coroutine_threadsafe", _mock_run)

    url = mock_client.upload_file(str(test_file))
    assert url == "https://example.com/d/test.txt"


def test_asky_xmpp_client_upload_file_no_plugin(mock_client, tmp_path, monkeypatch):
    test_file = tmp_path / "test.txt"
    test_file.write_text("hello")

    monkeypatch.setattr(mock_client, "get_plugin", lambda name: None)

    with pytest.raises(DaemonUserError, match="upload service not available"):
        mock_client.upload_file(str(test_file))


def test_asky_xmpp_client_upload_file_no_loop(mock_client, tmp_path):
    test_file = tmp_path / "test.txt"
    test_file.write_text("hello")

    mock_client._client.loop = None
    with pytest.raises(DaemonUserError, match="loop is None"):
        mock_client.upload_file(str(test_file))


def test_asky_xmpp_client_send_oob_message(mock_client):
    sent_stanzas = []

    def mock_send_stanza(client, msg):
        sent_stanzas.append(msg)

    with patch(
        "asky.plugins.xmpp_daemon.xmpp_client._dispatch_client_send_stanza_direct",
        mock_send_stanza,
    ):
        mock_client._client.make_message = MagicMock()
        mock_msg = MagicMock()
        mock_msg.xml = ET.Element("message")
        mock_client._client.make_message.return_value = mock_msg

        mock_client.send_oob_message(
            to_jid="user@example.com",
            url="https://example.com/f",
            body="here is a file",
            message_type="chat",
        )

        assert len(sent_stanzas) == 1
        msg = sent_stanzas[0]
        x_node = msg.xml.find("{jabber:x:oob}x")
        assert x_node is not None
        url_node = x_node.find("{jabber:x:oob}url")
        assert url_node is not None
        assert url_node.text == "https://example.com/f"


def test_file_upload_service_upload_and_send(mock_client, tmp_path):
    test_file = tmp_path / "test.png"
    test_file.write_bytes(b"data")

    mock_client.upload_file = MagicMock(return_value="https://example.com/png")
    mock_client.send_oob_message = MagicMock()

    service = FileUploadService(mock_client)
    url = service.upload_and_send(
        file_path=str(test_file),
        to_jid="user@example.com",
        message_type="chat",
        caption="Check this out",
    )

    assert url == "https://example.com/png"
    mock_client.upload_file.assert_called_once_with(str(test_file), content_type="")
    mock_client.send_oob_message.assert_called_once_with(
        to_jid="user@example.com",
        url="https://example.com/png",
        body="Check this out",
        message_type="chat",
    )


def test_file_upload_service_file_too_large(mock_client, tmp_path, monkeypatch):
    test_file = tmp_path / "huge.bin"
    test_file.write_bytes(b"some data")

    monkeypatch.setattr("os.path.getsize", lambda p: 200 * 1024 * 1024)  # 200MB

    service = FileUploadService(mock_client)
    with pytest.raises(FileUploadError, match="File too large"):
        service.upload_and_send(
            file_path=str(test_file), to_jid="user", message_type="chat"
        )


def test_file_upload_service_singleton():
    set_file_upload_service(None)
    assert get_file_upload_service() is None

    mock_service = MagicMock(spec=FileUploadService)
    set_file_upload_service(mock_service)
    assert get_file_upload_service() is mock_service

    set_file_upload_service(None)
    assert get_file_upload_service() is None
