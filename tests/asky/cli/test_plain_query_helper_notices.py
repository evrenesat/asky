
import pytest
from unittest.mock import MagicMock, patch
from asky.api import AskyTurnResult, PreloadResolution, SessionResolution

@pytest.fixture
def mock_chat_deps():
    with patch("asky.cli.chat.AskyClient") as mock_client, \
         patch("asky.cli.chat.Console") as mock_console, \
         patch("asky.cli.chat.MODELS", {"gpt4": {"id": "gpt-4"}}):
        client = mock_client.return_value
        console = mock_console.return_value
        yield client, console

def test_cli_shows_helper_notices_in_green_after_answer(mock_chat_deps):
    """
    Ensures helper notices are rendered in green after the answer, 
    even if an initial_notice_callback was provided (which handles non-helper notices).
    """
    client, console = mock_chat_deps
    
    # In the real flow, initial_notice_callback handles early notices and clears them.
    # Helper notices are re-injected later.
    
    def side_effect(request, **kwargs):
        initial_cb = kwargs.get("initial_notice_callback")
        if initial_cb:
            initial_cb("Normal early notice")
            
        return AskyTurnResult(
            final_answer="The answer",
            query_summary="",
            answer_summary="",
            messages=[],
            model_alias="gpt4",
            notices=[
                "Your prompt enriched: context",
                "New memory: user likes python. MemID#42"
            ],
            preload=PreloadResolution(),
            session=SessionResolution()
        )
        
    client.run_turn.side_effect = side_effect
    
    from asky.cli.chat import run_chat
    args = MagicMock()
    args.verbose = False
    args.lean = False
    args.model = "gpt4"
    args.summarize = False
    args.terminal_lines = None
    args.sticky_session = None
    args.resume_session = None
    args.research = False
    args.shortlist = None
    
    run_chat(args, "query")
    
    # 1. Normal notice should be printed by the callback (standard rendering)
    assert any("[Normal early notice]" in str(call) for call in console.print.call_args_list)
    
    # 2. Helper notices should be printed in bold green (post-answer rendering)
    green_calls = [
        call for call in console.print.call_args_list 
        if any("[bold green]" in str(arg) for arg in call[0])
    ]
    
    assert len(green_calls) == 2
    assert "Your prompt enriched: context" in str(green_calls[0])
    assert "New memory: user likes python. MemID#42" in str(green_calls[1])

def test_cli_skips_helper_notices_when_not_present(mock_chat_deps):
    client, console = mock_chat_deps
    
    client.run_turn.return_value = AskyTurnResult(
        final_answer="The answer",
        query_summary="",
        answer_summary="",
        messages=[],
        model_alias="gpt4",
        notices=["Random normal notice"],
        preload=PreloadResolution(),
        session=SessionResolution()
    )
    
    from asky.cli.chat import run_chat
    args = MagicMock()
    args.verbose = False
    args.lean = False
    args.model = "gpt4"
    args.summarize = False
    args.terminal_lines = None
    args.sticky_session = None
    args.resume_session = None
    args.research = False
    args.shortlist = None
    
    run_chat(args, "query")
    
    # Helper green notices should not be present
    green_calls = [
        call for call in console.print.call_args_list 
        if any("[bold green]" in str(arg) for arg in call[0])
    ]
    assert len(green_calls) == 0
    # Normal notice should be printed
    assert any("[Random normal notice]" in str(call) for call in console.print.call_args_list)
