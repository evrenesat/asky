import pytest
from rich.console import Console
from asky.banner import BannerState, get_banner


@pytest.fixture
def mock_state():
    return BannerState(
        model_alias="test-model",
        model_id="tm-123",
        sum_alias="sum-model",
        sum_id="sm-123",
        model_ctx=4096,
        sum_ctx=4096,
        max_turns=20,
        current_turn=1,
        db_count=100,
        session_name="test-session",
        session_msg_count=5,
        total_sessions=10,
        main_token_usage={"test-model": {"input": 100, "output": 200}},
        sum_token_usage={},
        tool_usage={"search": 1},
        compact_banner=True,
    )


def test_compact_banner_rendering(mock_state):
    """Test that compact banner renders without error and contains expected elements."""
    panel = get_banner(mock_state)

    # Render to string
    console = Console()
    with console.capture() as capture:
        console.print(panel)
    output = capture.get()

    # Check for emojis
    assert "🤖" in output
    assert "📝" in output
    assert "🛠️" in output
    assert "🔄" in output

    # Check for content
    assert "test-model" in output
    assert "tm-123" in output
    assert "sum-model" in output
    assert "sm-123" in output
    assert "test-session" in output

    # Verify order: Turns -> Tools (approximately)
    # We expect Turns (rotated arrow) to appear before Tools (hammer/wrench)
    assert output.find("🔄") < output.find("🛠️")
    assert output.find("💾") < output.find("🛠️")
    assert output.find("🗂️") < output.find("🛠️")


def test_compact_banner_research_mode(mock_state):
    """Test compact banner with research mode enabled."""
    mock_state.research_mode = True
    mock_state.embedding_texts = 10
    mock_state.embedding_api_calls = 2

    panel = get_banner(mock_state)

    console = Console()
    with console.capture() as capture:
        console.print(panel)
    output = capture.get()

    assert "🧠" in output
    assert "10 txt" in output


def test_full_banner_uses_conversation_label():
    """Full banner should label totals row as Conversation."""
    state = BannerState(
        model_alias="test-model",
        model_id="tm-123",
        sum_alias="sum-model",
        sum_id="sm-123",
        model_ctx=4096,
        sum_ctx=4096,
        max_turns=20,
        current_turn=1,
        db_count=100,
        total_sessions=10,
        main_token_usage={"test-model": {"input": 100, "output": 200}},
    )

    panel = get_banner(state)

    console = Console()
    with console.capture() as capture:
        console.print(panel)
    output = capture.get()

    assert "Conversation" in output
