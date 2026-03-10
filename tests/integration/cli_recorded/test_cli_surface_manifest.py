import argparse
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from asky.cli.main import parse_args
from asky.cli.main import main as cli_main
from asky.plugins.push_data.plugin import PushDataPlugin
from asky.plugins.playwright_browser.plugin import PlaywrightBrowserPlugin
from asky.plugins.email_sender.plugin import EmailSenderPlugin
from asky.plugins.xmpp_daemon.plugin import XMPPDaemonPlugin

from tests.integration.cli_recorded.cli_surface import (
    BEHAVIORAL_SURFACES,
    CONFIG_COMMANDS,
    COVERAGE_OWNERSHIP,
    GROUPED_COMMANDS,
    HIDDEN_INTERNAL_FLAGS,
    PERSONA_SUBCOMMANDS,
    PLUGIN_FLAGS,
    PUBLIC_TOP_LEVEL_FLAGS,
)


def test_cli_surface_parity_main_flags():
    parser_instance = None

    def mock_parse_args(self, args=None, namespace=None):
        nonlocal parser_instance
        parser_instance = self
        return argparse.Namespace()

    with patch("argparse.ArgumentParser.parse_args", mock_parse_args):
        try:
            parse_args(argv=[], plugin_manager=None)
        except SystemExit:
            pass

    assert parser_instance is not None

    all_flags = set()
    for action in parser_instance._actions:
        if isinstance(action, argparse._HelpAction):
            continue
        if not action.option_strings:
            continue
        for opt in action.option_strings:
            all_flags.add(opt)

    public_flags = {
        f for f in all_flags
        if f not in HIDDEN_INTERNAL_FLAGS and f not in {"-me", "--help-all"}
    }

    missing_in_manifest = public_flags - PUBLIC_TOP_LEVEL_FLAGS
    missing_in_parser = PUBLIC_TOP_LEVEL_FLAGS - public_flags

    assert not missing_in_manifest, f"New public flags found in main.py not in manifest: {missing_in_manifest}"
    assert not missing_in_parser, f"Flags in manifest not found in main.py parser: {missing_in_parser}"


def test_cli_surface_parity_persona_subcommands():
    parser_instance = None

    def capture_parser(self, args=None, namespace=None):
        nonlocal parser_instance
        parser_instance = self
        raise SystemExit(0)

    with (
        patch.object(sys, "argv", ["asky", "persona", "--help"]),
        patch("argparse.ArgumentParser.parse_args", capture_parser),
        pytest.raises(SystemExit),
    ):
        cli_main()

    assert parser_instance is not None

    subcmds = set()
    for action in parser_instance._actions:
        if isinstance(action, argparse._SubParsersAction):
            subcmds.update(f"persona {name}" for name in action.choices)

    missing_in_manifest = subcmds - PERSONA_SUBCOMMANDS
    missing_in_parser = PERSONA_SUBCOMMANDS - subcmds

    assert not missing_in_manifest, f"New persona subcommands not in manifest: {missing_in_manifest}"
    assert not missing_in_parser, f"Persona subcommands in manifest not found: {missing_in_parser}"


def test_cli_surface_parity_plugin_contributions():
    plugins = [
        PushDataPlugin,
        PlaywrightBrowserPlugin,
        EmailSenderPlugin,
        XMPPDaemonPlugin,
    ]

    all_plugin_flags = set()
    for plugin_cls in plugins:
        contribs = plugin_cls.get_cli_contributions()
        for contrib in contribs:
            for flag in contrib.flags:
                all_plugin_flags.add(flag)

    missing_in_manifest = all_plugin_flags - PLUGIN_FLAGS
    missing_in_parser = PLUGIN_FLAGS - all_plugin_flags

    assert not missing_in_manifest, f"New plugin flags not in manifest: {missing_in_manifest}"
    assert not missing_in_parser, f"Plugin flags in manifest not found: {missing_in_parser}"


def test_cli_surface_ownership_completeness():
    """Verify that every declared surface item has an owning integration test."""
    all_surface_items = (
        PUBLIC_TOP_LEVEL_FLAGS
        | GROUPED_COMMANDS
        | CONFIG_COMMANDS
        | PERSONA_SUBCOMMANDS
        | PLUGIN_FLAGS
        | BEHAVIORAL_SURFACES
    )
    owned_items = set(COVERAGE_OWNERSHIP)
    unowned_items = all_surface_items - owned_items
    extra_owned_items = owned_items - all_surface_items

    assert not unowned_items, f"Surface items without an owner: {sorted(unowned_items)}"
    assert not extra_owned_items, f"Unknown ownership entries in manifest: {sorted(extra_owned_items)}"


def test_cli_surface_ownership_targets_exist():
    owner_files = {path for path in COVERAGE_OWNERSHIP.values()}
    missing_files = []
    for owner in sorted(owner_files):
        owner_path = Path(__file__).with_name(owner)
        if not owner_path.exists():
            missing_files.append(owner)
    assert not missing_files, f"Ownership entries must point to existing test files: {missing_files}"
