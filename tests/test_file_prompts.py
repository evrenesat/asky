import os
import pytest
from pathlib import Path
from unittest.mock import patch
from asky.cli.utils import load_custom_prompts, expand_query_text


def test_load_custom_prompts_valid_file(tmp_path):
    prompt_file = tmp_path / "test_prompt.txt"
    content = "This is a prompt from a file."
    prompt_file.write_text(content, encoding="utf-8")

    test_prompts = {"test": f"file://{prompt_file}"}

    with (
        patch("asky.cli.utils.USER_PROMPTS", test_prompts),
        patch("pathlib.Path.home", return_value=tmp_path),
    ):
        load_custom_prompts()
        assert test_prompts["test"] == content


def test_load_custom_prompts_file_not_found(capsys, tmp_path):
    non_existent = tmp_path / "non_existent_file.txt"
    test_prompts = {"test": f"file://{non_existent}"}

    with (
        patch("asky.cli.utils.USER_PROMPTS", test_prompts),
        patch("pathlib.Path.home", return_value=tmp_path),
    ):
        load_custom_prompts()
        assert test_prompts["test"] == f"file://{non_existent}"
        captured = capsys.readouterr()
        assert "not found" in captured.out


def test_load_custom_prompts_file_too_large(tmp_path, capsys):
    prompt_file = tmp_path / "large_file.txt"
    prompt_file.write_text("a" * 200, encoding="utf-8")  # 200 bytes

    test_prompts = {"test": f"file://{prompt_file}"}

    with (
        patch("asky.cli.utils.USER_PROMPTS", test_prompts),
        patch("asky.cli.utils.MAX_PROMPT_FILE_SIZE", 100),
        patch("pathlib.Path.home", return_value=tmp_path),
    ):
        load_custom_prompts()
        assert test_prompts["test"] == f"file://{prompt_file}"
        captured = capsys.readouterr()
        assert "too large" in captured.out


def test_load_custom_prompts_empty_file(tmp_path, capsys):
    prompt_file = tmp_path / "empty_file.txt"
    prompt_file.write_text("", encoding="utf-8")

    test_prompts = {"test": f"file://{prompt_file}"}

    with (
        patch("asky.cli.utils.USER_PROMPTS", test_prompts),
        patch("pathlib.Path.home", return_value=tmp_path),
    ):
        load_custom_prompts()
        assert test_prompts["test"] == f"file://{prompt_file}"
        captured = capsys.readouterr()
        assert "empty" in captured.out


def test_load_custom_prompts_binary_file(tmp_path, capsys):
    prompt_file = tmp_path / "binary_file.bin"
    with open(prompt_file, "wb") as f:
        f.write(b"\x80\x81\x82")  # Invalid UTF-8

    test_prompts = {"test": f"file://{prompt_file}"}

    with (
        patch("asky.cli.utils.USER_PROMPTS", test_prompts),
        patch("pathlib.Path.home", return_value=tmp_path),
    ):
        load_custom_prompts()
        assert test_prompts["test"] == f"file://{prompt_file}"
        captured = capsys.readouterr()
        assert "not a valid text file" in captured.out


def test_expand_query_with_file_prompt(tmp_path):
    prompt_file = tmp_path / "test_prompt.txt"
    content = "This is a prompt from a file."
    prompt_file.write_text(content, encoding="utf-8")

    test_prompts = {"test": f"file://{prompt_file}"}

    with (
        patch("asky.cli.utils.USER_PROMPTS", test_prompts),
        patch("pathlib.Path.home", return_value=tmp_path),
    ):
        load_custom_prompts()
        expanded = expand_query_text("/test something")
        assert content in expanded
        assert "something" in expanded
