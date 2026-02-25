"""Persona management exception hierarchy."""

from __future__ import annotations

from typing import List, Optional


class PersonaError(Exception):
    """Base error for persona management operations."""


class PersonaNotFoundError(PersonaError):
    """Raised when a persona name or alias cannot be resolved."""

    def __init__(
        self,
        identifier: str,
        *,
        available_personas: Optional[List[str]] = None,
        available_aliases: Optional[List[tuple[str, str]]] = None,
    ) -> None:
        """
        Initialize PersonaNotFoundError with suggestions.
        
        Args:
            identifier: The persona name or alias that was not found
            available_personas: List of available persona names
            available_aliases: List of (alias, persona_name) tuples
        """
        self.identifier = identifier
        self.available_personas = available_personas or []
        self.available_aliases = available_aliases or []
        
        message = f"Persona '{identifier}' not found"
        
        if self.available_personas:
            personas_str = ", ".join(self.available_personas)
            message += f"\nAvailable personas: {personas_str}"
        
        if self.available_aliases:
            aliases_str = ", ".join(f"{alias}→{persona}" for alias, persona in self.available_aliases)
            message += f"\nAvailable aliases: {aliases_str}"
        
        super().__init__(message)


class InvalidAliasError(PersonaError):
    """Raised when an alias operation fails validation."""

    def __init__(self, alias: str, reason: str) -> None:
        """
        Initialize InvalidAliasError with reason.
        
        Args:
            alias: The alias that failed validation
            reason: Human-readable reason for the failure
        """
        self.alias = alias
        self.reason = reason
        super().__init__(f"Invalid alias '{alias}': {reason}")


class InvalidPersonaPackageError(PersonaError):
    """Raised when a persona package fails validation during import."""

    def __init__(self, path: str, validation_failure: str) -> None:
        """
        Initialize InvalidPersonaPackageError with validation details.
        
        Args:
            path: Path to the invalid persona package
            validation_failure: Specific validation rule that failed
        """
        self.path = path
        self.validation_failure = validation_failure
        super().__init__(
            f"Invalid persona package at '{path}': {validation_failure}"
        )


class PersonaAlreadyLoadedError(PersonaError):
    """Raised when attempting to load a persona that is already active."""

    def __init__(self, persona_name: str, session_id: str) -> None:
        """
        Initialize PersonaAlreadyLoadedError.
        
        Args:
            persona_name: The persona that is already loaded
            session_id: The session where the persona is active
        """
        self.persona_name = persona_name
        self.session_id = session_id
        super().__init__(
            f"Persona '{persona_name}' is already loaded in session {session_id}"
        )


class NoActiveSessionError(PersonaError):
    """Raised when a persona operation requires an active session but none exists."""

    def __init__(self, operation: str) -> None:
        """
        Initialize NoActiveSessionError.
        
        Args:
            operation: The operation that requires a session
        """
        self.operation = operation
        super().__init__(
            f"Operation '{operation}' requires an active session. "
            "Use -ss <name> to create a session or -rs <name> to resume one"
        )
