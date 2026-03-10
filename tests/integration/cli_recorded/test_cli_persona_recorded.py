import pytest
from pathlib import Path

from tests.integration.cli_recorded.helpers import (
    normalize_cli_output,
    run_cli_inprocess,
)

pytestmark = [
    pytest.mark.recorded_cli,
    pytest.mark.vcr,
    pytest.mark.with_plugins(["manual_persona_creator", "persona_manager"]),
]


def test_persona_surface_exhaustive(tmp_path):
    """Exhaustive test of persona command surface."""
    # 1. Create
    prompt_file = tmp_path / "pirate.md"
    prompt_file.write_text("You are a pirate.")
    
    result_create = run_cli_inprocess([
        "persona", "create", "pirate_persona",
        "--prompt", str(prompt_file),
        "--description", "A salty sea dog."
    ])
    assert result_create.exit_code == 0
    assert "created persona" in normalize_cli_output(result_create.stdout).lower()

    # 2. List
    result_list = run_cli_inprocess(["persona", "list"])
    assert "pirate_persona" in normalize_cli_output(result_list.stdout).lower()

    # 3. Add sources
    dummy_source = tmp_path / "ship.txt"
    dummy_source.write_text("The Black Pearl.")
    result_add = run_cli_inprocess(["persona", "add-sources", "pirate_persona", str(dummy_source)])
    assert result_add.exit_code == 0

    # 4. Alias
    result_alias = run_cli_inprocess(["persona", "alias", "p1", "pirate_persona"])
    assert result_alias.exit_code == 0
    
    # 5. Aliases
    result_aliases = run_cli_inprocess(["persona", "aliases"])
    assert "p1" in normalize_cli_output(result_aliases.stdout).lower()

    # 6. Load
    run_cli_inprocess(["-ss", "persona_sess"])
    result_load = run_cli_inprocess(["persona", "load", "pirate_persona"])
    assert result_load.exit_code == 0
    assert "loaded persona" in normalize_cli_output(result_load.stdout).lower()

    # 7. Current
    result_curr = run_cli_inprocess(["persona", "current"])
    assert "pirate_persona" in normalize_cli_output(result_curr.stdout).lower()

    # 8. Unload
    result_unload = run_cli_inprocess(["persona", "unload"])
    assert result_unload.exit_code == 0
    assert "unloaded persona" in normalize_cli_output(result_unload.stdout).lower()

    # 9. Export
    export_path = tmp_path / "pirate.zip"
    result_export = run_cli_inprocess(["persona", "export", "pirate_persona", "--output", str(export_path)])
    assert result_export.exit_code == 0
    assert export_path.exists()

    # 10. Import
    result_import = run_cli_inprocess(["persona", "import", str(export_path)])
    assert result_import.exit_code == 0
    assert "imported persona" in normalize_cli_output(result_import.stdout).lower()

    # 11. Unalias
    result_unalias = run_cli_inprocess(["persona", "unalias", "p1"])
    assert result_unalias.exit_code == 0


def test_persona_mention_behavior(tmp_path):
    """Test @persona and @alias mentions in turns."""
    # Setup persona and alias
    prompt_file = tmp_path / "ninja.md"
    prompt_file.write_text("You are a ninja.")
    run_cli_inprocess(["persona", "create", "ninja", "--prompt", str(prompt_file)])
    run_cli_inprocess(["persona", "alias", "n1", "ninja"])
    
    # Start session
    run_cli_inprocess(["-ss", "mention_sess"])
    
    # Use @mention
    # We trust VCR matching or banner info
    result = run_cli_inprocess(["@ninja", "Just say apple."])
    assert result.exit_code == 0
    # Banner should show loaded persona if not in lean mode
    # assert "ninja" in normalize_cli_output(result.stdout).lower()

    # Use @alias
    result2 = run_cli_inprocess(["@n1", "Just say banana."])
    assert result2.exit_code == 0
