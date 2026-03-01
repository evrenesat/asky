"""Service for uploading and sharing files via XMPP (XEP-0363)."""

from __future__ import annotations

import logging
import os
from typing import Optional, TYPE_CHECKING

from asky.daemon.errors import DaemonUserError

if TYPE_CHECKING:
    from asky.plugins.xmpp_daemon.xmpp_client import AskyXMPPClient

logger = logging.getLogger(__name__)

UPLOAD_TIMEOUT_SECONDS = 60
UPLOAD_MAX_FILE_SIZE_BYTES = 100 * 1024 * 1024  # 100 MB hard guard


class FileUploadError(Exception):
    """Wraps all upload failures with a human-readable message."""


class FileUploadService:
    """Service for uploading files and sharing them via OOB messages."""

    def __init__(self, client: AskyXMPPClient) -> None:
        self._client = client

    def upload_and_send(
        self,
        *,
        file_path: str,
        to_jid: str,
        message_type: str,
        filename: str = "",
        content_type: str = "",
        caption: str = "",
    ) -> str:
        """Upload a local file and deliver its URL to an XMPP recipient.

        Returns:
            The download URL of the uploaded file.
        """
        if not os.path.exists(file_path):
            raise FileUploadError(f"File not found: {file_path}")

        file_size = os.path.getsize(file_path)
        if file_size > UPLOAD_MAX_FILE_SIZE_BYTES:
            raise FileUploadError(
                f"File too large: {file_size / (1024 * 1024):.1f}MB exceeds {UPLOAD_MAX_FILE_SIZE_BYTES / (1024 * 1024):.0f}MB limit."
            )

        if not filename:
            filename = os.path.basename(file_path)

        # slixmpp xep_0363 does its own content-type detection if empty,
        # but we can pass it through if provided.

        try:
            url = self._client.upload_file(file_path, content_type=content_type)

            body = caption if caption else f"Shared file: {filename}"
            self._client.send_oob_message(
                to_jid=to_jid,
                url=url,
                body=body,
                message_type=message_type,
            )
            return url
        except DaemonUserError as e:
            raise FileUploadError(str(e)) from e
        except Exception as e:
            logger.debug("FileUploadService failed: %s", e, exc_info=True)
            raise FileUploadError(f"XMPP file upload failed: {str(e)}") from e


_service: Optional[FileUploadService] = None


def set_file_upload_service(service: Optional[FileUploadService]) -> None:
    """Set the global file upload service singleton."""
    global _service
    _service = service


def get_file_upload_service() -> Optional[FileUploadService]:
    """Return the global file upload service singleton, if set."""
    return _service
