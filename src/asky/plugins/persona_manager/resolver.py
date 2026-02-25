"""Persona identifier resolution with alias support."""

from pathlib import Path
from typing import List, Optional

from asky.plugins.kvstore import PluginKVStore
from asky.plugins.manual_persona_creator.storage import (
    list_persona_names,
    persona_exists,
)
from asky.plugins.persona_manager.errors import InvalidAliasError


def resolve_persona_name(
    identifier: str,
    kvstore: PluginKVStore,
    data_dir: Path,
) -> Optional[str]:
    """
    Resolve persona identifier (name or alias) to actual persona name.
    
    Resolution order:
    1. Check if identifier is an alias (lookup in KVStore)
    2. Check if identifier is a persona name (direct lookup)
    3. Return None if not found
    
    Args:
        identifier: Persona name or alias to resolve
        kvstore: Plugin KVStore for alias lookups
        data_dir: Data directory where personas are stored
        
    Returns:
        Resolved persona name, or None if not found
    """
    if not identifier or not identifier.strip():
        return None
    
    normalized_identifier = identifier.strip()
    
    alias_key = f"alias:{normalized_identifier}"
    resolved_name = kvstore.get(alias_key)
    
    if resolved_name and persona_exists(data_dir, resolved_name):
        return resolved_name
    
    if persona_exists(data_dir, normalized_identifier):
        return normalized_identifier
    
    return None


def list_available_personas(data_dir: Path) -> List[str]:
    """
    List all available persona names in deterministic order.
    
    Args:
        data_dir: Data directory where personas are stored
        
    Returns:
        Sorted list of persona names
    """
    return list_persona_names(data_dir)


def get_persona_aliases(
    persona_name: str,
    kvstore: PluginKVStore,
) -> List[str]:
    """
    Get all aliases for a specific persona.
    
    Args:
        persona_name: The persona name to find aliases for
        kvstore: Plugin KVStore for alias lookups
        
    Returns:
        List of aliases pointing to this persona
    """
    all_alias_keys = kvstore.list_keys(prefix="alias:")
    
    aliases = []
    for key in all_alias_keys:
        target_persona = kvstore.get(key)
        if target_persona == persona_name:
            alias_name = key[len("alias:"):]
            aliases.append(alias_name)
    
    return sorted(aliases)


def set_persona_alias(
    alias: str,
    persona_name: str,
    kvstore: PluginKVStore,
    data_dir: Path,
) -> None:
    """
    Create or update a persona alias.
    
    Args:
        alias: The alias name to create
        persona_name: The target persona name
        kvstore: Plugin KVStore for alias storage
        data_dir: Data directory where personas are stored
        
    Raises:
        ValueError: If persona doesn't exist
        InvalidAliasError: If alias conflicts with existing persona name
    """
    if not persona_exists(data_dir, persona_name):
        raise ValueError(f"Persona '{persona_name}' does not exist")
    
    if persona_exists(data_dir, alias):
        raise InvalidAliasError(
            alias,
            f"conflicts with existing persona name '{alias}'"
        )
    
    alias_key = f"alias:{alias}"
    kvstore.set(alias_key, persona_name)


def remove_persona_alias(
    alias: str,
    kvstore: PluginKVStore,
) -> bool:
    """
    Remove a persona alias.
    
    Args:
        alias: The alias name to remove
        kvstore: Plugin KVStore for alias storage
        
    Returns:
        True if alias was removed, False if it didn't exist
    """
    alias_key = f"alias:{alias}"
    return kvstore.delete(alias_key)


def list_all_aliases(kvstore: PluginKVStore) -> List[tuple[str, str]]:
    """
    List all persona aliases.
    
    Args:
        kvstore: Plugin KVStore for alias lookups
        
    Returns:
        List of (alias, persona_name) tuples, sorted by alias
    """
    all_alias_keys = kvstore.list_keys(prefix="alias:")
    
    aliases = []
    for key in all_alias_keys:
        alias_name = key[len("alias:"):]
        persona_name = kvstore.get(key)
        if persona_name:
            aliases.append((alias_name, persona_name))
    
    return sorted(aliases, key=lambda x: x[0])
