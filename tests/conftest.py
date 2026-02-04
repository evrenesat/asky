import pytest
import os
from pathlib import Path
from unittest.mock import patch


@pytest.fixture(autouse=True)
def mock_settings_env_vars(tmp_path):
    """Automatically mock HOME and environment variables to ensure test isolation."""
    # Create a fake home directory
    fake_home = tmp_path / "fake_home"
    fake_home.mkdir()

    # Patch Path.home() to return the fake home
    with patch("pathlib.Path.home", return_value=fake_home):
        # Also set HOME env separator for good measure, though Path.home mock likely covers most usage
        with patch.dict(
            os.environ,
            {"HOME": str(fake_home), "ASKY_DB_PATH": str(fake_home / "test.db")},
        ):
            yield
