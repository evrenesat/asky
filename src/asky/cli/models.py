"""Interactive model management CLI commands."""

import tomllib
from pathlib import Path
from typing import Optional, Dict, Any, List

from rich.console import Console
from rich.table import Table
from rich.prompt import Prompt, Confirm, FloatPrompt, IntPrompt

import tomlkit
from asky.config import MODELS, load_config
from . import openrouter

console = Console()

SHORTLIST_MODE_AUTO = "auto"
SHORTLIST_MODE_ON = "on"
SHORTLIST_MODE_OFF = "off"


def list_model_aliases() -> List[str]:
    """Return available model aliases in a stable order."""
    return sorted(MODELS.keys())


def update_general_config(key: str, value: str):
    """Update general.toml configuration using tomlkit."""
    config_path = Path.home() / ".config" / "asky" / "general.toml"

    if not config_path.exists():
        console.print(
            f"[yellow]Warning: {config_path} does not exist. Skipping update for {key}.[/yellow]"
        )
        return

    try:
        content = config_path.read_text()
        doc = tomlkit.parse(content)

        if "general" not in doc:
            doc.add("general", tomlkit.table())

        doc["general"][key] = value

        config_path.write_text(doc.as_string())
        console.print(f"[green]Updated {key} to '{value}' in general.toml[/green]")

    except Exception as e:
        console.print(f"[red]Failed to update general.toml: {e}[/red]")


def _shortlist_mode_from_value(value: Optional[bool]) -> str:
    """Map model shortlist setting to CLI choice token."""
    if value is True:
        return SHORTLIST_MODE_ON
    if value is False:
        return SHORTLIST_MODE_OFF
    return SHORTLIST_MODE_AUTO


def _shortlist_value_from_mode(mode: str) -> Optional[bool]:
    """Map CLI choice token back to stored shortlist setting."""
    if mode == SHORTLIST_MODE_ON:
        return True
    if mode == SHORTLIST_MODE_OFF:
        return False
    return None


def add_model_command():
    """Interactively add a new model definition."""
    console.print("[bold]Add New Model Definition[/bold]\n")

    # Step 1: Select API provider
    config = load_config()
    apis = list(config.get("api", {}).keys())

    if not apis:
        console.print(
            "[red]No APIs configured. Please configure [api] sections in your config first.[/red]"
        )
        return

    console.print("[bold]Step 1: Select API Provider[/bold]")
    for i, api in enumerate(apis, 1):
        console.print(f"  {i}. {api}")

    api_choice = IntPrompt.ask("Select provider", default=1, show_default=True)
    if api_choice < 1 or api_choice > len(apis):
        console.print("[red]Invalid selection[/red]")
        return

    selected_api = apis[api_choice - 1]

    # Step 2: Model selection (search or enter full name)
    console.print("\n[bold]Step 2: Select Model[/bold]")

    # Fetch models if using OpenRouter
    models = []
    if selected_api == "openrouter":
        console.print("Fetching available models from OpenRouter...")
        try:
            models = openrouter.fetch_models()
            console.print(f"Found {len(models)} models")
        except Exception as e:
            console.print(f"[yellow]Warning: Could not fetch models: {e}[/yellow]")

    selected_model_data = {}
    model_id = ""
    context_size = 4096
    supported_params = []

    if models:
        search_query = Prompt.ask("Search for model (or enter full model ID)")
        results = openrouter.search_models(search_query, models)

        if results:
            console.print(f"\nFound {len(results)} matches:")
            # Limit display to 20
            display_limit = 20
            for i, m in enumerate(results[:display_limit], 1):
                name = m.get("name") or m.get("id")
                console.print(f"  {i}. {m.get('id')} - {name}")

            if len(results) > display_limit:
                console.print(f"  ... and {len(results) - display_limit} more")

            choice_default = 1
            choice = IntPrompt.ask(
                "Select model (0 to enter custom ID)", default=choice_default
            )

            if choice > 0 and choice <= len(results):
                selected_model_data = results[choice - 1]
                model_id = selected_model_data.get("id")
                context_size = selected_model_data.get("context_length", 4096)
                supported_params = selected_model_data.get("supported_parameters", [])
            else:
                model_id = search_query if choice == 0 else ""
        else:
            console.print("[yellow]No matches found.[/yellow]")
            model_id = search_query
            # If explicit ID entered, assume generic defaults or ask
            supported_params = list(openrouter.KNOWN_PARAMETERS.keys())

    if not model_id:
        model_id = Prompt.ask("Enter model ID")
        supported_params = list(openrouter.KNOWN_PARAMETERS.keys())

    context_size = IntPrompt.ask("Context size", default=int(context_size or 4096))

    shortlist_mode = Prompt.ask(
        "Pre-LLM source shortlisting for this model",
        choices=[SHORTLIST_MODE_AUTO, SHORTLIST_MODE_ON, SHORTLIST_MODE_OFF],
        default=SHORTLIST_MODE_AUTO,
    )
    shortlist_enabled = _shortlist_value_from_mode(shortlist_mode)

    # Step 3: Configure parameters
    console.print("\n[bold]Step 3: Configure Parameters[/bold]")
    console.print("Press Enter to skip (use default value)\n")

    parameters = {}

    # If using OpenRouter, we know which params are supported.
    # If not, we offer all known params.
    candidates = (
        supported_params
        if supported_params
        else list(openrouter.KNOWN_PARAMETERS.keys())
    )

    for param in candidates:
        if param not in openrouter.KNOWN_PARAMETERS:
            continue

        param_info = openrouter.KNOWN_PARAMETERS[param]
        default_val = param_info.get("default")
        param_type = param_info.get("type")

        hint = f"({param_type}"
        if "min" in param_info:
            hint += f", min={param_info['min']}"
        if "max" in param_info:
            hint += f", max={param_info['max']}"
        if default_val is not None:
            hint += f", default={default_val}"
        hint += ")"

        value = Prompt.ask(f"  {param} {hint}", default="", show_default=False)
        if value:
            try:
                if param_type == "float":
                    parameters[param] = float(value)
                elif param_type == "int":
                    parameters[param] = int(value)
            except ValueError:
                console.print(f"[yellow]Invalid value, skipping {param}[/yellow]")

    # Step 4: Nickname
    console.print("\n[bold]Step 4: Set Nickname[/bold]")
    default_nick = model_id.split("/")[-1]
    # Simple sanitization
    default_nick = default_nick.replace(".", "-").replace(":", "-")
    nickname = Prompt.ask("Enter nickname for CLI flag (-m)", default=default_nick)

    # Confirm and save
    console.print("\n[bold]Summary:[/bold]")
    console.print(f"  Nickname: {nickname}")
    console.print(f"  Model ID: {model_id}")
    console.print(f"  API: {selected_api}")
    console.print(f"  Context Size: {context_size}")
    console.print(f"  Source Shortlist: {shortlist_mode}")
    if parameters:
        console.print(f"  Parameters: {parameters}")

    if Confirm.ask("\nSave this model?", default=True):
        save_model_config(
            nickname,
            {
                "id": model_id,
                "api": selected_api,
                "context_size": context_size,
                "source_shortlist_enabled": shortlist_enabled,
                "parameters": parameters if parameters else None,
            },
        )
        console.print(f"\n[green]Model '{nickname}' saved successfully![/green]")
        console.print(
            f"You can now use this model with: [bold]asky -m {nickname}[/bold]"
        )
    else:
        console.print("[yellow]Cancelled[/yellow]")
        return

    # Offer to set as default/summarization
    if Confirm.ask("\nSet as default main model?", default=False):
        update_general_config("default_model", nickname)

    if Confirm.ask("Set as summarization model?", default=False):
        update_general_config("summarization_model", nickname)


def edit_model_command(model_alias: Optional[str] = None):
    """Interactively edit an existing model definition."""
    # List existing models if no alias provided
    if not model_alias:
        # Load current defaults
        config = load_config()
        general = config.get("general", {})
        def_model = general.get("default_model")
        sum_model = general.get("summarization_model")

        console.print("[bold]Existing Models:[/bold]")
        console.print(
            f"  [green]* Main Model: {def_model}[/green]   [blue]* Summarization Model: {sum_model}[/blue]\n"
        )

        table = Table(show_header=True)
        table.add_column("No.")
        table.add_column("Alias")
        table.add_column("ID")

        aliases = list_model_aliases()
        for i, alias in enumerate(aliases, 1):
            model = MODELS[alias]

            # Format alias with indicators
            alias_display = alias
            if alias == def_model:
                alias_display = f"[green]{alias} *[/green]"
            if alias == sum_model:
                # If both, append blue * too
                if alias == def_model:
                    alias_display += f" [blue]*[/blue]"
                else:
                    alias_display = f"[blue]{alias} *[/blue]"

            table.add_row(str(i), alias_display, model.get("id", ""))

        console.print(table)

        choice_input = Prompt.ask("Enter model alias (or number) to edit")

        # Check if number
        try:
            choice_idx = int(choice_input)
            if 1 <= choice_idx <= len(aliases):
                model_alias = aliases[choice_idx - 1]
            else:
                model_alias = choice_input
        except ValueError:
            model_alias = choice_input

    if model_alias not in MODELS:
        console.print(f"[red]Model '{model_alias}' not found[/red]")
        return

    current_config = MODELS[model_alias]
    console.print(f"\n[bold]Editing Model: {model_alias}[/bold]")
    console.print(f"Current ID: {current_config.get('id')}")
    console.print(f"Current API: {current_config.get('api')}")
    console.print(f"Current Context Size: {current_config.get('context_size')}")
    console.print(
        "Current Source Shortlist: "
        f"{_shortlist_mode_from_value(current_config.get('source_shortlist_enabled'))}"
    )

    context_size = IntPrompt.ask(
        "Context size",
        default=int(current_config.get("context_size", 4096)),
    )

    shortlist_mode = Prompt.ask(
        "Pre-LLM source shortlisting for this model",
        choices=[SHORTLIST_MODE_AUTO, SHORTLIST_MODE_ON, SHORTLIST_MODE_OFF],
        default=_shortlist_mode_from_value(
            current_config.get("source_shortlist_enabled")
        ),
    )
    shortlist_enabled = _shortlist_value_from_mode(shortlist_mode)

    console.print("\n[bold]Configure Parameters[/bold]")

    # Merge existing parameters
    parameters = current_config.get("parameters", {}).copy()

    # Offer options
    options = list(openrouter.KNOWN_PARAMETERS.keys())

    # Sequential parameter editing
    console.print(
        "\n[bold]Configuration (Press Enter to keep current, type 'none' to unset)[/bold]"
    )

    for param_to_edit in options:
        param_info = openrouter.KNOWN_PARAMETERS[param_to_edit]
        default_val = param_info.get("default")
        curr_val = parameters.get(param_to_edit)

        # Display current state interaction
        # If currently set, that's the default. If not set, check default?
        # User said: "traverse all parameters with their set values if they set."
        # If not set, maybe show default from OpenRouter but mark it as (default)?
        # Or leave it empty?
        # Let's use the 'current effective value' as default prompt if set,
        # or the system default if not set?
        # If not set in parameters, it is effectively the system default or None.

        # Implementation: Default prompt is standard default, unless overridden.
        # But if user didn't override, we shouldn't force an override.
        # So prompts should show "Current: [value]" or default to "" if not set?
        # User: "hit enter if they don't want to change the existing value."
        # If I map Enter -> "Keep as is", then I need to know "what is is".

        # Let's show current value in the prompt text, but prompt default is empty string means 'keep'?
        # Or better: Prompt default IS the current value.

        prompt_default = str(curr_val) if curr_val is not None else ""

        param_type = param_info.get("type")
        hint = f"({param_type}"
        if "min" in param_info:
            hint += f", min={param_info['min']}"
        if "max" in param_info:
            hint += f", max={param_info['max']}"
        if default_val is not None:
            # If current value is NOT set, show default info
            if curr_val is None:
                hint += f", default={default_val}"
        hint += ")"

        # Special visual for set values
        label = param_to_edit
        if curr_val is not None:
            label = f"[green]{param_to_edit}[/green]"

        val_input = Prompt.ask(f"  {label} {hint}", default=prompt_default)

        if val_input == prompt_default:
            # No change
            continue

        if val_input.lower() in ["none", "unset", "null", ""]:
            # Explicit unset if they typed 'none' or cleared it (if default was not empty)
            # If prompt_default was empty (unset) and they entered empty, we hit 'no change' above.
            # If prompt_default was SET and they entered empty -> Prompt returns default!
            # So Prompt.ask(default="foo") returns "foo" on empty input.
            # To UNSET, they MUST type "none" etc.
            if param_to_edit in parameters:
                del parameters[param_to_edit]
                console.print(f"    [yellow]Unset {param_to_edit}[/yellow]")
        else:
            # Try to set
            try:
                if param_type == "float":
                    parameters[param_to_edit] = float(val_input)
                elif param_type == "int":
                    parameters[param_to_edit] = int(val_input)
            except ValueError:
                console.print(
                    f"    [red]Invalid value for {param_to_edit}, skipping change[/red]"
                )

    if Confirm.ask("\nSave changes?", default=True):
        new_config = {
            "id": current_config.get("id"),
            "api": current_config.get(
                "api"
            ),  # Note: api might be resolved in MODELS, prefer 'api_ref' if kept?
            # Actually, MODELS is hydrated, so 'api' key might be the full dict or just string depending on hydration?
            # Hydration copies keys, checks 'api' key exists in CONFIG['api'].
            # 'api' field in model is the string ref.
            "context_size": context_size,
            "source_shortlist_enabled": shortlist_enabled,
            "parameters": parameters if parameters else None,
        }
        # Re-using the api string key is tricky if hydration replaced/augmented it.
        # Check original config or trust that 'api' string key is preserved.
        # In `loader.py`, `_hydrate_models` preserves `api` field (string) and adds `base_url`, `api_key`.

        save_model_config(model_alias, new_config)

        console.print(f"\n[green]Model '{model_alias}' updated successfully![/green]")

        if Confirm.ask("\nSet as default main model?", default=False):
            update_general_config("default_model", model_alias)

        if Confirm.ask("Set as summarization model?", default=False):
            update_general_config("summarization_model", model_alias)


def save_model_config(nickname: str, config: Dict[str, Any]):
    """Save a model configuration to user's models.toml using tomlkit."""
    config_path = Path.home() / ".config" / "asky" / "models.toml"

    if not config_path.exists():
        config_path.touch()

    try:
        content = config_path.read_text()
        doc = tomlkit.parse(content)

        # Ensure 'models' listing style is supported.
        # Typically structure is [models.nickname].
        # In tomlkit, if we access doc["models"], it refers to the table 'models' if it exists.
        # But if we want [models.impl], we usually treat 'models' as a table containing subtables.

        if "models" not in doc:
            doc.add("models", tomlkit.table())

        models_table = doc["models"]

        # Prepare new model data
        # We want it to be an inline table or standard table?
        # Using [models.nickname] implies nickname is a subtable of models.

        # Build the model dict
        model_data = tomlkit.table()
        model_data["id"] = config["id"]
        if "api" in config:
            model_data["api"] = config["api"]
        model_data["context_size"] = config["context_size"]
        shortlist_enabled = config.get("source_shortlist_enabled")
        if shortlist_enabled is not None:
            model_data["source_shortlist_enabled"] = bool(shortlist_enabled)

        if config.get("parameters"):
            params = tomlkit.table()
            for k, v in config["parameters"].items():
                params[k] = v
            model_data["parameters"] = params

        # Update or Set
        # If duplicated, tomlkit handles replacement in memory.
        models_table[nickname] = model_data

        config_path.write_text(doc.as_string())

    except Exception as e:
        console.print(f"[red]Failed to save model config: {e}[/red]")
