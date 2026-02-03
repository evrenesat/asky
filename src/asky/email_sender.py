"""Email sending functionality for asky."""

import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import List, Optional

import markdown

from asky.config import (
    SMTP_HOST,
    SMTP_PORT,
    SMTP_USE_SSL,
    SMTP_USE_TLS,
    SMTP_USER,
    SMTP_PASSWORD,
    EMAIL_FROM_ADDRESS,
)

logger = logging.getLogger(__name__)


def markdown_to_html(md_content: str) -> str:
    """Convert markdown string to HTML."""
    # Use standard extensions for better compatibility
    extensions = [
        "extra",
        "codehilite",
        "tables",
        "toc",
    ]
    html_body = markdown.markdown(md_content, extensions=extensions)

    # Basic HTML wrapper with some styling for email clients
    html_template = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <style>
            body {{
                font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
                font-size: 16px;
                line-height: 1.6;
                color: #333;
                max-width: 800px;
                margin: 20px auto;
            }}
            pre {{
                background: #f6f8fa;
                padding: 16px;
                overflow: auto;
                border-radius: 6px;
                border: 1px solid #ddd;
            }}
            code {{
                font-family: SFMono-Regular, Consolas, "Liberation Mono", Menlo, monospace;
                background: #f4f4f4;
                padding: 2px 4px;
                border-radius: 3px;
                font-size: 0.9em;
            }}
            table {{
                border-collapse: collapse;
                width: 100%;
                margin: 16px 0;
            }}
            th, td {{
                border: 1px solid #dfe2e5;
                padding: 8px 12px;
                text-align: left;
            }}
            tr:nth-child(even) {{
                background-color: #f6f8fa;
            }}
            blockquote {{
                margin: 0;
                padding: 0 1em;
                color: #6a737d;
                border-left: 0.25em solid #dfe2e5;
            }}
            h1, h2, h3 {{
                border-bottom: 1px solid #eaecef;
                padding-bottom: .3em;
            }}
        </style>
    </head>
    <body>
        <div class="content">
            {html_body}
        </div>
    </body>
    </html>
    """
    return html_template


def send_email(
    to_addresses: List[str],
    subject: str,
    markdown_content: str,
) -> bool:
    """
    Send an HTML email with the rendered markdown content.
    Returns True on success, False on failure.
    """
    if not SMTP_USER or not SMTP_PASSWORD:
        logger.error(
            "SMTP credentials not configured. Please set ASKY_SMTP_USER and ASKY_SMTP_PASSWORD."
        )
        print("Error: SMTP credentials missing. Check your configuration.")
        return False

    try:
        html_content = markdown_to_html(markdown_content)

        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = EMAIL_FROM_ADDRESS
        msg["To"] = ", ".join(to_addresses)

        # Attach plain text version (though here it's just the markdown)
        msg.attach(MIMEText(markdown_content, "plain"))
        # Attach HTML version
        msg.attach(MIMEText(html_content, "html"))

        print(f"[Connecting to SMTP server {SMTP_HOST}:{SMTP_PORT}...]")

        if SMTP_USE_SSL:
            # Direct SSL/TLS connection (typically port 465)
            with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT) as server:
                server.login(SMTP_USER, SMTP_PASSWORD)
                server.send_message(msg)
        else:
            # Standard SMTP with optional STARTTLS (typically port 587)
            with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
                if SMTP_USE_TLS:
                    server.starttls()
                server.login(SMTP_USER, SMTP_PASSWORD)
                server.send_message(msg)

        print(f"[Email sent successfully to {len(to_addresses)} recipient(s).]")
        return True

    except Exception as e:
        logger.error(f"Failed to send email: {e}")
        print(f"Error sending email: {e}")
        return False
