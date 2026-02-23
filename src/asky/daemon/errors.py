"""User-visible daemon exceptions."""

from __future__ import annotations


class DaemonUserError(RuntimeError):
    """Error intended to be shown directly in daemon-facing interfaces."""

    def __init__(self, message: str, *, hint: str = ""):
        self.message = str(message or "").strip() or "Unknown daemon error."
        self.hint = str(hint or "").strip()
        super().__init__(self.user_message)

    @property
    def user_message(self) -> str:
        if self.hint:
            return f"{self.message} {self.hint}".strip()
        return self.message
