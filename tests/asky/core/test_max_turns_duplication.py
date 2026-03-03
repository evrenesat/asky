# """Test for duplicate output fix when reaching MAX_TURNS."""

# from unittest.mock import patch, MagicMock
# from asky.core.engine import ConversationEngine, ToolRegistry


# def test_no_duplicate_output_when_finishing_on_max_turn():
#     """Test that the answer is only printed once when finishing exactly on MAX_TURNS.

#     This tests the fix for the bug where if the LLM returns a final answer on exactly
#     turn MAX_TURNS, the answer would be printed twice - once in the normal completion
#     path and once in the graceful exit path.
#     """
#     # Mock model config
#     model_config = {
#         "id": "test-model",
#         "alias": "test",
#         "context_size": 4096,
#     }

#     # Create empty tool registry
#     registry = ToolRegistry()

#     # Track how many times the answer is printed
#     print_count = 0
#     final_answer_displayed = None

#     def mock_display_callback(turn, status_message=None, is_final=False, final_answer=None):
#         nonlocal print_count, final_answer_displayed
#         if is_final and final_answer:
#             print_count += 1
#             final_answer_displayed = final_answer

#     # Mock get_llm_msg to return tool calls for first 9 turns, then final answer on turn 10
#     call_count = 0

#     def mock_get_llm_msg(*args, **kwargs):
#         nonlocal call_count
#         call_count += 1

#         if call_count < 10:
#             # Return a tool call
#             return {
#                 "role": "assistant",
#                 "content": None,
#                 "tool_calls": [
#                     {
#                         "id": f"call_{call_count}",
#                         "type": "function",
#                         "function": {
#                             "name": "fake_tool",
#                             "arguments": '{"query": "test"}'
#                         }
#                     }
#                 ]
#             }
#         else:
#             # Turn 10: Return final answer (no tool calls)
#             return {
#                 "role": "assistant",
#                 "content": "This is the final answer on turn 10"
#             }

#     # Patch MAX_TURNS to 10 for this test
#     with patch('asky.core.engine.MAX_TURNS', 10):
#         with patch('asky.core.api_client.get_llm_msg', side_effect=mock_get_llm_msg):
#             # Create engine
#             engine = ConversationEngine(
#                 model_config=model_config,
#                 tool_registry=registry,
#                 summarize=False,
#                 verbose=False,
#             )

#             # Run with a display callback (simulating LIVE_BANNER=True)
#             messages = [
#                 {"role": "system", "content": "Test system prompt"},
#                 {"role": "user", "content": "Test query"}
#             ]

#             final_answer = engine.run(messages, display_callback=mock_display_callback)

#     # Verify the answer was only displayed once
#     assert print_count == 1, f"Expected answer to be displayed exactly once, but it was displayed {print_count} times"
#     assert final_answer == "This is the final answer on turn 10"
#     assert final_answer_displayed == "This is the final answer on turn 10"

#     # Verify we completed on exactly turn 10
#     assert call_count == 10, f"Expected exactly 10 LLM calls, got {call_count}"


# def test_graceful_exit_still_works_when_exceeding_turns():
#     """Test that the graceful exit path still works when tools keep being called."""
#     model_config = {
#         "id": "test-model",
#         "alias": "test",
#         "context_size": 4096,
#     }

#     registry = ToolRegistry()

#     # Track display calls
#     display_calls = []

#     def mock_display_callback(turn, status_message=None, is_final=False, final_answer=None):
#         if is_final and final_answer:
#             display_calls.append({
#                 'turn': turn,
#                 'answer': final_answer
#             })

#     # Mock get_llm_msg to always return tool calls (never finish naturally)
#     call_count = 0

#     def mock_get_llm_msg(*args, **kwargs):
#         nonlocal call_count
#         call_count += 1
#         use_tools = kwargs.get('use_tools', True)

#         if use_tools:
#             # Return a tool call
#             return {
#                 "role": "assistant",
#                 "content": None,
#                 "tool_calls": [
#                     {
#                         "id": f"call_{call_count}",
#                         "type": "function",
#                         "function": {
#                             "name": "fake_tool",
#                             "arguments": '{"query": "test"}'
#                         }
#                     }
#                 ]
#             }
#         else:
#             # Final call without tools - graceful exit
#             return {
#                 "role": "assistant",
#                 "content": "Gracefully exiting after max turns"
#             }

#     # Patch MAX_TURNS to 3 for faster test
#     with patch('asky.core.engine.MAX_TURNS', 3):
#         with patch('asky.core.api_client.get_llm_msg', side_effect=mock_get_llm_msg):
#             engine = ConversationEngine(
#                 model_config=model_config,
#                 tool_registry=registry,
#                 summarize=False,
#                 verbose=False,
#             )

#             messages = [
#                 {"role": "system", "content": "Test system prompt"},
#                 {"role": "user", "content": "Test query"}
#             ]

#             final_answer = engine.run(messages, display_callback=mock_display_callback)

#     # Verify graceful exit happened
#     assert len(display_calls) == 1, f"Expected exactly 1 display call, got {len(display_calls)}"
#     assert final_answer == "Gracefully exiting after max turns"

#     # Verify we made one extra call for graceful exit (3 normal + 1 graceful = 4)
#     assert call_count == 4, f"Expected 4 LLM calls (3 tool-using + 1 graceful), got {call_count}"
