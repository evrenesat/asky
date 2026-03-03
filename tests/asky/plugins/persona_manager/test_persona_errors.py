"""Unit tests for persona error handling."""

from pathlib import Path
from tempfile import TemporaryDirectory
from zipfile import ZipFile

import pytest

from asky.plugins.kvstore import PluginKVStore
from asky.plugins.manual_persona_creator.storage import create_persona
from asky.plugins.persona_manager.errors import (
    InvalidAliasError,
    InvalidPersonaPackageError,
    NoActiveSessionError,
    PersonaNotFoundError,
)
from asky.plugins.persona_manager.importer import import_persona_archive
from asky.plugins.persona_manager.resolver import (
    resolve_persona_name,
    set_persona_alias,
)


class TestPersonaNotFoundError:
    """Test PersonaNotFoundError exception."""

    def test_error_message_with_no_suggestions(self):
        """Test error message when no personas or aliases are available."""
        error = PersonaNotFoundError("nonexistent")
        
        assert "nonexistent" in str(error)
        assert "not found" in str(error)

    def test_error_message_with_available_personas(self):
        """Test error message includes available personas."""
        error = PersonaNotFoundError(
            "nonexistent",
            available_personas=["dev", "writer", "expert"]
        )
        
        error_msg = str(error)
        assert "nonexistent" in error_msg
        assert "Available personas:" in error_msg
        assert "dev" in error_msg
        assert "writer" in error_msg
        assert "expert" in error_msg

    def test_error_message_with_available_aliases(self):
        """Test error message includes available aliases."""
        error = PersonaNotFoundError(
            "nonexistent",
            available_aliases=[("d", "dev"), ("w", "writer")]
        )
        
        error_msg = str(error)
        assert "nonexistent" in error_msg
        assert "Available aliases:" in error_msg
        assert "d→dev" in error_msg
        assert "w→writer" in error_msg

    def test_error_message_with_both_personas_and_aliases(self):
        """Test error message includes both personas and aliases."""
        error = PersonaNotFoundError(
            "nonexistent",
            available_personas=["dev", "writer"],
            available_aliases=[("d", "dev")]
        )
        
        error_msg = str(error)
        assert "Available personas:" in error_msg
        assert "Available aliases:" in error_msg

    def test_error_attributes(self):
        """Test that error stores attributes correctly."""
        personas = ["dev", "writer"]
        aliases = [("d", "dev")]
        error = PersonaNotFoundError(
            "nonexistent",
            available_personas=personas,
            available_aliases=aliases
        )
        
        assert error.identifier == "nonexistent"
        assert error.available_personas == personas
        assert error.available_aliases == aliases


class TestInvalidAliasError:
    """Test InvalidAliasError exception."""

    def test_error_message_format(self):
        """Test error message format."""
        error = InvalidAliasError("myalias", "conflicts with existing persona")
        
        error_msg = str(error)
        assert "myalias" in error_msg
        assert "conflicts with existing persona" in error_msg
        assert "Invalid alias" in error_msg

    def test_error_attributes(self):
        """Test that error stores attributes correctly."""
        error = InvalidAliasError("myalias", "some reason")
        
        assert error.alias == "myalias"
        assert error.reason == "some reason"

    def test_conflict_with_persona_name(self):
        """Test error message for alias conflicting with persona name."""
        error = InvalidAliasError(
            "dev",
            "conflicts with existing persona name 'dev'"
        )
        
        error_msg = str(error)
        assert "dev" in error_msg
        assert "conflicts with existing persona" in error_msg


class TestInvalidPersonaPackageError:
    """Test InvalidPersonaPackageError exception."""

    def test_error_message_format(self):
        """Test error message format."""
        error = InvalidPersonaPackageError(
            "/path/to/package.zip",
            "missing required file: metadata.toml"
        )
        
        error_msg = str(error)
        assert "/path/to/package.zip" in error_msg
        assert "missing required file" in error_msg
        assert "Invalid persona package" in error_msg

    def test_error_attributes(self):
        """Test that error stores attributes correctly."""
        error = InvalidPersonaPackageError(
            "/path/to/package.zip",
            "validation failure"
        )
        
        assert error.path == "/path/to/package.zip"
        assert error.validation_failure == "validation failure"

    def test_missing_metadata_error(self):
        """Test error for missing metadata file."""
        error = InvalidPersonaPackageError(
            "package.zip",
            "missing required file(s): metadata.toml"
        )
        
        assert "metadata.toml" in str(error)

    def test_schema_version_error(self):
        """Test error for unsupported schema version."""
        error = InvalidPersonaPackageError(
            "package.zip",
            "unsupported schema version 2; expected 1"
        )
        
        error_msg = str(error)
        assert "schema version" in error_msg
        assert "expected 1" in error_msg


class TestNoActiveSessionError:
    """Test NoActiveSessionError exception."""

    def test_error_message_format(self):
        """Test error message format."""
        error = NoActiveSessionError("persona load")
        
        error_msg = str(error)
        assert "persona load" in error_msg
        assert "active session" in error_msg
        assert "-ss" in error_msg or "-rs" in error_msg

    def test_error_attributes(self):
        """Test that error stores attributes correctly."""
        error = NoActiveSessionError("persona load")
        
        assert error.operation == "persona load"

    def test_error_includes_usage_hint(self):
        """Test that error message includes usage hint."""
        error = NoActiveSessionError("persona load")
        
        error_msg = str(error)
        assert "Use -ss" in error_msg or "create a session" in error_msg


class TestResolverErrorHandling:
    """Test error handling in resolver functions."""

    def test_set_alias_raises_error_for_nonexistent_persona(self):
        """Test that setting alias for nonexistent persona raises ValueError."""
        with TemporaryDirectory() as tmpdir:
            data_dir = Path(tmpdir)
            kvstore = PluginKVStore("test_persona_manager")
            
            with pytest.raises(ValueError, match="does not exist"):
                set_persona_alias("myalias", "nonexistent", kvstore, data_dir)

    def test_set_alias_raises_error_for_conflicting_name(self):
        """Test that setting alias that conflicts with persona name raises InvalidAliasError."""
        with TemporaryDirectory() as tmpdir:
            data_dir = Path(tmpdir)
            kvstore = PluginKVStore("test_persona_manager")
            
            create_persona(
                data_dir=data_dir,
                persona_name="dev",
                description="Developer persona",
                behavior_prompt="You are a developer",
            )
            
            create_persona(
                data_dir=data_dir,
                persona_name="writer",
                description="Writer persona",
                behavior_prompt="You are a writer",
            )
            
            with pytest.raises(InvalidAliasError, match="conflicts with existing persona"):
                set_persona_alias("dev", "writer", kvstore, data_dir)

    def test_resolve_returns_none_for_nonexistent_persona(self):
        """Test that resolving nonexistent persona returns None."""
        with TemporaryDirectory() as tmpdir:
            data_dir = Path(tmpdir)
            kvstore = PluginKVStore("test_persona_manager")
            
            result = resolve_persona_name("nonexistent", kvstore, data_dir)
            
            assert result is None


class TestImporterErrorHandling:
    """Test error handling in importer functions."""

    def test_import_raises_error_for_nonexistent_file(self):
        """Test that importing nonexistent file raises InvalidPersonaPackageError."""
        with TemporaryDirectory() as tmpdir:
            data_dir = Path(tmpdir)
            
            with pytest.raises(InvalidPersonaPackageError, match="not found"):
                import_persona_archive(
                    data_dir=data_dir,
                    archive_path="/nonexistent/package.zip"
                )

    def test_import_raises_error_for_missing_metadata(self):
        """Test that importing package without metadata raises InvalidPersonaPackageError."""
        with TemporaryDirectory() as tmpdir:
            data_dir = Path(tmpdir)
            zip_path = Path(tmpdir) / "invalid.zip"
            
            with ZipFile(zip_path, "w") as zf:
                zf.writestr("behavior_prompt.md", "Test prompt")
                zf.writestr("chunks.json", "[]")
            
            with pytest.raises(InvalidPersonaPackageError, match="missing required file"):
                import_persona_archive(
                    data_dir=data_dir,
                    archive_path=str(zip_path)
                )

    def test_import_raises_error_for_missing_prompt(self):
        """Test that importing package without prompt raises InvalidPersonaPackageError."""
        with TemporaryDirectory() as tmpdir:
            data_dir = Path(tmpdir)
            zip_path = Path(tmpdir) / "invalid.zip"
            
            with ZipFile(zip_path, "w") as zf:
                zf.writestr("metadata.toml", '[persona]\nname = "test"\nschema_version = 1')
                zf.writestr("chunks.json", "[]")
            
            with pytest.raises(InvalidPersonaPackageError, match="missing required file"):
                import_persona_archive(
                    data_dir=data_dir,
                    archive_path=str(zip_path)
                )

    def test_import_raises_error_for_missing_chunks(self):
        """Test that importing package without chunks raises InvalidPersonaPackageError."""
        with TemporaryDirectory() as tmpdir:
            data_dir = Path(tmpdir)
            zip_path = Path(tmpdir) / "invalid.zip"
            
            with ZipFile(zip_path, "w") as zf:
                zf.writestr("metadata.toml", '[persona]\nname = "test"\nschema_version = 1')
                zf.writestr("behavior_prompt.md", "Test prompt")
            
            with pytest.raises(InvalidPersonaPackageError, match="missing required file"):
                import_persona_archive(
                    data_dir=data_dir,
                    archive_path=str(zip_path)
                )

    def test_import_raises_error_for_invalid_metadata(self):
        """Test that importing package with invalid metadata raises InvalidPersonaPackageError."""
        with TemporaryDirectory() as tmpdir:
            data_dir = Path(tmpdir)
            zip_path = Path(tmpdir) / "invalid.zip"
            
            with ZipFile(zip_path, "w") as zf:
                zf.writestr("metadata.toml", "invalid toml content [[[")
                zf.writestr("behavior_prompt.md", "Test prompt")
                zf.writestr("chunks.json", "[]")
            
            with pytest.raises(Exception):
                import_persona_archive(
                    data_dir=data_dir,
                    archive_path=str(zip_path)
                )

    def test_import_raises_error_for_path_traversal(self):
        """Test that importing package with path traversal raises InvalidPersonaPackageError."""
        with TemporaryDirectory() as tmpdir:
            data_dir = Path(tmpdir)
            zip_path = Path(tmpdir) / "malicious.zip"
            
            with ZipFile(zip_path, "w") as zf:
                zf.writestr("metadata.toml", '[persona]\nname = "test"\nschema_version = 1')
                zf.writestr("behavior_prompt.md", "Test prompt")
                zf.writestr("chunks.json", "[]")
                zf.writestr("../../../etc/passwd", "malicious content")
            
            with pytest.raises(InvalidPersonaPackageError, match="path traversal"):
                import_persona_archive(
                    data_dir=data_dir,
                    archive_path=str(zip_path)
                )

    def test_import_raises_error_for_absolute_path(self):
        """Test that importing package with absolute path raises InvalidPersonaPackageError."""
        with TemporaryDirectory() as tmpdir:
            data_dir = Path(tmpdir)
            zip_path = Path(tmpdir) / "malicious.zip"
            
            with ZipFile(zip_path, "w") as zf:
                zf.writestr("metadata.toml", '[persona]\nname = "test"\nschema_version = 1')
                zf.writestr("behavior_prompt.md", "Test prompt")
                zf.writestr("chunks.json", "[]")
                zf.writestr("/etc/passwd", "malicious content")
            
            with pytest.raises(InvalidPersonaPackageError, match="absolute path"):
                import_persona_archive(
                    data_dir=data_dir,
                    archive_path=str(zip_path)
                )

    def test_import_raises_error_for_unsupported_schema_version(self):
        """Test that importing package with unsupported schema raises InvalidPersonaPackageError."""
        with TemporaryDirectory() as tmpdir:
            data_dir = Path(tmpdir)
            zip_path = Path(tmpdir) / "invalid.zip"
            
            with ZipFile(zip_path, "w") as zf:
                zf.writestr("metadata.toml", '[persona]\nname = "test"\nschema_version = 999')
                zf.writestr("behavior_prompt.md", "Test prompt")
                zf.writestr("chunks.json", "[]")
            
            with pytest.raises(InvalidPersonaPackageError, match="schema version"):
                import_persona_archive(
                    data_dir=data_dir,
                    archive_path=str(zip_path)
                )

    def test_import_raises_error_for_invalid_chunks_format(self):
        """Test that importing package with invalid chunks format raises InvalidPersonaPackageError."""
        with TemporaryDirectory() as tmpdir:
            data_dir = Path(tmpdir)
            zip_path = Path(tmpdir) / "invalid.zip"
            
            with ZipFile(zip_path, "w") as zf:
                zf.writestr("metadata.toml", '[persona]\nname = "test"\nschema_version = 1')
                zf.writestr("behavior_prompt.md", "Test prompt")
                zf.writestr("chunks.json", '{"not": "an array"}')
            
            with pytest.raises(InvalidPersonaPackageError, match="must be a JSON array"):
                import_persona_archive(
                    data_dir=data_dir,
                    archive_path=str(zip_path)
                )
