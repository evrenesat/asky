"""Plugin runtime exception hierarchy."""


class PluginError(Exception):
    """Base plugin runtime error."""


class PluginManifestError(PluginError):
    """Raised when plugin manifest parsing/validation fails."""


class PluginImportError(PluginError):
    """Raised when plugin module/class import fails."""


class PluginDependencyError(PluginError):
    """Raised when plugin dependency graph is invalid."""


class PluginActivationError(PluginError):
    """Raised when plugin activation fails."""
