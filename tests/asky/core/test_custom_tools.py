import pytest
from unittest.mock import MagicMock, patch
from asky.tools import _execute_custom_tool


@pytest.fixture
def mock_custom_tools():
    with (
        patch("asky.tools.CUSTOM_TOOLS") as mock_tools,
        patch("asky.config.CUSTOM_TOOLS") as mock_config_tools,
        patch("asky.core.engine.CUSTOM_TOOLS") as mock_engine_tools,
    ):
        mock_data = {
            "list_dir": {
                "command": "ls {path}",
                "description": "List dir",
                "parameters": {
                    "type": "object",
                    "properties": {"path": {"type": "string", "default": "."}},
                },
            },
            "echo": {
                "command": "echo",
                "description": "Echo msg",
                "parameters": {
                    "type": "object",
                    "properties": {"msg": {"type": "string"}},
                },
            },
        }

        def get_side_effect(name):
            return mock_data.get(name)

        def contains_side_effect(name):
            return name in mock_data

        mock_tools.get.side_effect = get_side_effect
        mock_tools.__contains__.side_effect = contains_side_effect

        mock_config_tools.items.return_value = mock_data.items()
        mock_config_tools.get.side_effect = get_side_effect
        mock_config_tools.__contains__.side_effect = contains_side_effect

        mock_engine_tools.items.return_value = mock_data.items()
        mock_engine_tools.get.side_effect = get_side_effect
        mock_engine_tools.__contains__.side_effect = contains_side_effect

        yield mock_tools


@patch("subprocess.run")
def test_execute_custom_tool_placeholder_with_default(mock_run, mock_custom_tools):
    mock_run.return_value = MagicMock(stdout="file.txt\n", stderr="", returncode=0)

    # Do not pass 'path', it should use default "."
    args = {}
    result = _execute_custom_tool("list_dir", args)

    mock_run.assert_called_once()
    cmd = mock_run.call_args[0][0]
    assert cmd == 'ls "."'
    assert result["stdout"] == "file.txt"


@patch("subprocess.run")
def test_execute_custom_tool_placeholder(mock_run, mock_custom_tools):
    mock_run.return_value = MagicMock(stdout="file.txt\n", stderr="", returncode=0)

    args = {"path": "/tmp/test"}
    result = _execute_custom_tool("list_dir", args)

    # Check if arguments were quoted: "ls "/tmp/test""
    mock_run.assert_called_once()
    cmd = mock_run.call_args[0][0]
    assert cmd == 'ls "/tmp/test"'
    assert result["stdout"] == "file.txt"


@patch("subprocess.run")
def test_execute_custom_tool_append(mock_run, mock_custom_tools):
    mock_run.return_value = MagicMock(stdout="hello world\n", stderr="", returncode=0)

    args = {"msg": "hello world"}
    result = _execute_custom_tool("echo", args)

    mock_run.assert_called_once()
    cmd = mock_run.call_args[0][0]
    assert cmd == 'echo "hello world"'
    assert result["stdout"] == "hello world"


@patch("subprocess.run")
def test_execute_custom_tool_quoting(mock_run, mock_custom_tools):
    mock_run.return_value = MagicMock(stdout="fixed", stderr="", returncode=0)

    # If user passes "quoted" string, we should strip it and re-quote it
    args = {"msg": '"already quoted"'}
    _execute_custom_tool("echo", args)

    mock_run.assert_called_once()
    cmd = mock_run.call_args[0][0]
    # "already quoted" (inner quotes removed) -> ""already quoted""
    assert cmd == 'echo "already quoted"'


@patch("subprocess.run")
def test_dispatch_custom_tool(mock_run, mock_custom_tools):
    from asky.core import create_tool_registry

    mock_run.return_value = MagicMock(stdout="ok", stderr="", returncode=0)

    registry = create_tool_registry()
    call = {"function": {"name": "echo", "arguments": '{"msg": "test"}'}}

    result = registry.dispatch(call, summarize=False)
    print(result)
    assert result["stdout"] == "ok"
    mock_run.assert_called_once()


@patch("subprocess.run")
def test_custom_tool_disabled(mock_run, mock_custom_tools):
    """Test that a custom tool with enabled=False is not registered."""
    mock_custom_tools.items.return_value = {
        "disabled_tool": {
            "command": "echo disabled",
            "description": "Disabled tool",
            "enabled": False,
        }
    }.items()

    # We need to import create_default_tool_registry inside the test or setup
    # to ensure it uses the mocked CUSTOM_TOOLS
    from asky.core.tool_registry_factory import create_tool_registry

    registry = create_tool_registry()
    tool_names = registry.get_tool_names()

    assert "disabled_tool" not in tool_names
