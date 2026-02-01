import pytest
from unittest.mock import MagicMock, patch
from asearch.tools import _execute_custom_tool, dispatch_tool_call


@pytest.fixture
def mock_custom_tools():
    with patch("asearch.tools.CUSTOM_TOOLS") as mock:
        mock.get.side_effect = lambda name: {
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
        }.get(name)
        # Also need to mock 'in CUSTOM_TOOLS' check
        mock.__contains__.side_effect = lambda name: name in ["list_dir", "echo"]
        yield mock


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
    result = _execute_custom_tool("echo", args)

    mock_run.assert_called_once()
    cmd = mock_run.call_args[0][0]
    # "already quoted" (inner quotes removed) -> ""already quoted""
    assert cmd == 'echo "already quoted"'


@patch("subprocess.run")
def test_dispatch_custom_tool(mock_run, mock_custom_tools):
    mock_run.return_value = MagicMock(stdout="ok", stderr="", returncode=0)

    call = {"function": {"name": "echo", "arguments": '{"msg": "test"}'}}
    result = dispatch_tool_call(call, max_chars=1000, summarize=False)

    assert result["stdout"] == "ok"
    mock_run.assert_called_once()
