import types
from unittest.mock import MagicMock, patch

import pytest

from asky.plugins.email_sender.plugin import EmailSenderPlugin
from asky.plugins.email_sender.sender import markdown_to_html, send_email
from asky.plugins.hook_types import PostTurnRenderContext


def _make_ctx(recipients, answer="The answer.", title="", query_text="my query"):
    request = types.SimpleNamespace(query_text=query_text)
    cli_args = types.SimpleNamespace(sendmail=recipients)
    return PostTurnRenderContext(
        final_answer=answer,
        request=request,
        result=None,
        cli_args=cli_args,
        answer_title=title,
    )


def test_markdown_to_html():
    md = "# Hello\n\nThis is **bold** and a [link](https://example.com)"
    html = markdown_to_html(md)

    assert "Hello</h1>" in html
    assert "<strong>bold</strong>" in html or "<b>bold</b>" in html
    assert 'href="https://example.com"' in html
    assert "<!DOCTYPE html>" in html


@patch("smtplib.SMTP")
@patch("asky.plugins.email_sender.sender.SMTP_USER", "test@user.com")
@patch("asky.plugins.email_sender.sender.SMTP_PASSWORD", "password")
@patch("asky.plugins.email_sender.sender.SMTP_HOST", "smtp.test.com")
@patch("asky.plugins.email_sender.sender.SMTP_PORT", 587)
@patch("asky.plugins.email_sender.sender.SMTP_USE_SSL", False)
@patch("asky.plugins.email_sender.sender.SMTP_USE_TLS", True)
def test_send_email_success(mock_smtp):
    mock_server = MagicMock()
    mock_smtp.return_value.__enter__.return_value = mock_server

    recipients = ["rec1@test.com", "rec2@test.com"]
    subject = "Test Subject"
    content = "Test content"

    result = send_email(recipients, subject, content)

    assert result is True
    mock_server.starttls.assert_called_once()
    mock_server.login.assert_called_with("test@user.com", "password")
    mock_server.send_message.assert_called_once()

    call_msg = mock_server.send_message.call_args[0][0]
    assert call_msg["Subject"] == subject
    assert "rec1@test.com, rec2@test.com" in call_msg["To"]


@patch("smtplib.SMTP")
@patch("asky.plugins.email_sender.sender.SMTP_USER", None)
def test_send_email_missing_creds(mock_smtp):
    result = send_email(["test@test.com"], "Sub", "Cont")
    assert result is False
    mock_smtp.assert_not_called()


@patch("smtplib.SMTP")
@patch("asky.plugins.email_sender.sender.SMTP_USER", "test@user.com")
@patch("asky.plugins.email_sender.sender.SMTP_PASSWORD", "password")
@patch("asky.plugins.email_sender.sender.SMTP_USE_SSL", False)
def test_send_email_failure(mock_smtp):
    mock_server = MagicMock()
    mock_server.login.side_effect = Exception("Auth failed")
    mock_smtp.return_value.__enter__.return_value = mock_server

    result = send_email(["test@test.com"], "Sub", "Cont")
    assert result is False


@patch("asky.plugins.email_sender.sender.send_email")
def test_plugin_uses_answer_title_as_subject(mock_send):
    plugin = EmailSenderPlugin()
    ctx = _make_ctx("rec@test.com", title="My Report Title")
    plugin._on_post_turn_render(ctx)
    mock_send.assert_called_once()
    _, subject, _ = mock_send.call_args[0]
    assert subject == "My Report Title"


@patch("asky.plugins.email_sender.sender.send_email")
def test_plugin_falls_back_to_query_text_when_no_title(mock_send):
    plugin = EmailSenderPlugin()
    ctx = _make_ctx("rec@test.com", title="", query_text="summarize the report")
    plugin._on_post_turn_render(ctx)
    mock_send.assert_called_once()
    _, subject, _ = mock_send.call_args[0]
    assert subject == "summarize the report"


@patch("asky.plugins.email_sender.sender.send_email")
def test_plugin_splits_comma_separated_recipients(mock_send):
    plugin = EmailSenderPlugin()
    ctx = _make_ctx("a@x.com, b@x.com, c@x.com", title="Title")
    plugin._on_post_turn_render(ctx)
    recipients, _, _ = mock_send.call_args[0]
    assert recipients == ["a@x.com", "b@x.com", "c@x.com"]


def test_plugin_skips_when_no_sendmail():
    plugin = EmailSenderPlugin()
    ctx = _make_ctx(None)
    with patch("asky.plugins.email_sender.sender.send_email") as mock_send:
        plugin._on_post_turn_render(ctx)
        mock_send.assert_not_called()
