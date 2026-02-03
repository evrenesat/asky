import pytest
from unittest.mock import patch, MagicMock

from asky.email_sender import markdown_to_html, send_email


def test_markdown_to_html():
    md = "# Hello\n\nThis is **bold** and a [link](https://example.com)"
    html = markdown_to_html(md)

    assert "Hello</h1>" in html
    assert "<strong>bold</strong>" in html or "<b>bold</b>" in html
    assert 'href="https://example.com"' in html
    assert "<!DOCTYPE html>" in html


@patch("smtplib.SMTP")
@patch("asky.email_sender.SMTP_USER", "test@user.com")
@patch("asky.email_sender.SMTP_PASSWORD", "password")
@patch("asky.email_sender.SMTP_HOST", "smtp.test.com")
@patch("asky.email_sender.SMTP_PORT", 587)
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

    # Verify message construction
    call_msg = mock_server.send_message.call_args[0][0]
    assert call_msg["Subject"] == subject
    assert "rec1@test.com, rec2@test.com" in call_msg["To"]


@patch("smtplib.SMTP")
@patch("asky.email_sender.SMTP_USER", None)
def test_send_email_missing_creds(mock_smtp):
    result = send_email(["test@test.com"], "Sub", "Cont")
    assert result is False
    mock_smtp.assert_not_called()


@patch("smtplib.SMTP")
@patch("asky.email_sender.SMTP_USER", "test@user.com")
@patch("asky.email_sender.SMTP_PASSWORD", "password")
def test_send_email_failure(mock_smtp):
    mock_server = MagicMock()
    mock_server.login.side_effect = Exception("Auth failed")
    mock_smtp.return_value.__enter__.return_value = mock_server

    result = send_email(["test@test.com"], "Sub", "Cont")
    assert result is False
