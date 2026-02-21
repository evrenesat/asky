import pytest
from asky.banner import BannerState


def test_banner_state_get_token_str_same_alias():
    main_usage = {"main_model": {"input": 100, "output": 50}}
    summary_usage = {"main_model": {"input": 200, "output": 20}}

    state = BannerState(
        model_alias="main_model",
        model_id="test_id",
        sum_alias="main_model",
        sum_id="test_id",
        model_ctx=4096,
        sum_ctx=4096,
        max_turns=10,
        current_turn=1,
        db_count=0,
        main_token_usage=main_usage,
        sum_token_usage=summary_usage,
    )

    main_str = state.get_token_str("main_model")
    assert "in: 100" in main_str
    assert "out: 50" in main_str

    sum_str = state.get_token_str("main_model", is_summary=True)
    assert "in: 200" in sum_str
    assert "out: 20" in sum_str

    # Verify no mutation
    assert main_usage["main_model"]["input"] == 100
    assert summary_usage["main_model"]["input"] == 200
