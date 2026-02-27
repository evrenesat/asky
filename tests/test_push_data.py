"""Tests for push_data module."""

import os
import types
from unittest.mock import Mock, patch

import pytest
import requests

from asky.plugins.hook_types import PostTurnRenderContext
from asky.plugins.push_data.executor import (
    _build_payload,
    _resolve_field_value,
    _resolve_headers,
    execute_push_data,
    get_enabled_endpoints,
)
from asky.plugins.push_data.plugin import PushDataPlugin


def _make_push_ctx(push_data, answer="The answer.", query_text="my query"):
    request = types.SimpleNamespace(query_text=query_text)
    cli_args = types.SimpleNamespace(push_data=push_data, lean=False, model=None)
    return PostTurnRenderContext(
        final_answer=answer,
        request=request,
        result=None,
        cli_args=cli_args,
    )


class TestPushDataPlugin:
    @patch("asky.plugins.push_data.executor.execute_push_data")
    def test_endpoint_only(self, mock_exec):
        mock_exec.return_value = {"success": True, "endpoint": "ep", "status_code": 200}
        plugin = PushDataPlugin()
        ctx = _make_push_ctx("myendpoint")
        plugin._on_post_turn_render(ctx)
        mock_exec.assert_called_once()
        assert mock_exec.call_args[0][0] == "myendpoint"
        assert mock_exec.call_args[1]["dynamic_args"] == {}

    @patch("asky.plugins.push_data.executor.execute_push_data")
    def test_endpoint_with_params(self, mock_exec):
        mock_exec.return_value = {"success": True, "endpoint": "ep", "status_code": 200}
        plugin = PushDataPlugin()
        ctx = _make_push_ctx("notion?title=My Doc&status=draft")
        plugin._on_post_turn_render(ctx)
        call_kwargs = mock_exec.call_args[1]
        assert mock_exec.call_args[0][0] == "notion"
        assert call_kwargs["dynamic_args"] == {"title": "My Doc", "status": "draft"}

    @patch("asky.plugins.push_data.executor.execute_push_data")
    def test_value_with_equals_in_val_preserved(self, mock_exec):
        mock_exec.return_value = {"success": True, "endpoint": "ep", "status_code": 200}
        plugin = PushDataPlugin()
        ctx = _make_push_ctx("ep?url=https://example.com/a=b")
        plugin._on_post_turn_render(ctx)
        assert mock_exec.call_args[1]["dynamic_args"]["url"] == "https://example.com/a=b"

    def test_skips_when_no_push_data(self):
        plugin = PushDataPlugin()
        ctx = _make_push_ctx(None)
        with patch("asky.plugins.push_data.executor.execute_push_data") as mock_exec:
            plugin._on_post_turn_render(ctx)
            mock_exec.assert_not_called()


class TestResolveFieldValue:
    """Tests for _resolve_field_value function."""

    def test_static_value(self):
        """Test resolving a static literal value."""
        result = _resolve_field_value("field", "literal_value", {}, {})
        assert result == "literal_value"

    def test_environment_variable(self):
        """Test resolving an environment variable."""
        with patch.dict(os.environ, {"MY_ENV_VAR": "env_value"}):
            result = _resolve_field_value("field_env", "MY_ENV_VAR", {}, {})
            assert result == "env_value"

    def test_environment_variable_missing(self):
        """Test error when environment variable not found."""
        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(ValueError, match="Environment variable 'MISSING' not found"):
                _resolve_field_value("field_env", "MISSING", {}, {})

    def test_dynamic_parameter(self):
        """Test resolving a dynamic parameter."""
        result = _resolve_field_value(
            "title", "${title}", {"title": "My Title"}, {}
        )
        assert result == "My Title"

    def test_dynamic_parameter_missing(self):
        """Test error when dynamic parameter is missing."""
        with pytest.raises(ValueError, match="Missing required parameter: title"):
            _resolve_field_value("title", "${title}", {}, {})

    def test_special_variable_query(self):
        """Test resolving special variable ${query}."""
        result = _resolve_field_value(
            "query_field", "${query}", {}, {"query": "my query"}
        )
        assert result == "my query"

    def test_special_variable_answer(self):
        """Test resolving special variable ${answer}."""
        result = _resolve_field_value(
            "answer_field", "${answer}", {}, {"answer": "my answer"}
        )
        assert result == "my answer"

    def test_special_variable_timestamp(self):
        """Test resolving special variable ${timestamp}."""
        result = _resolve_field_value(
            "ts", "${timestamp}", {}, {"timestamp": "2024-01-01T00:00:00"}
        )
        assert result == "2024-01-01T00:00:00"

    def test_special_variable_model(self):
        """Test resolving special variable ${model}."""
        result = _resolve_field_value(
            "model_field", "${model}", {}, {"model": "gpt-4"}
        )
        assert result == "gpt-4"

    def test_special_variable_missing(self):
        """Test error when special variable not available."""
        with pytest.raises(ValueError, match="Special variable 'query' not available"):
            _resolve_field_value("field", "${query}", {}, {})


class TestResolveHeaders:
    """Tests for _resolve_headers function."""

    def test_static_headers(self):
        """Test resolving static headers."""
        headers_config = {
            "Content-Type": "application/json",
            "X-Custom": "value",
        }
        result = _resolve_headers(headers_config)
        assert result == {
            "Content-Type": "application/json",
            "X-Custom": "value",
        }

    def test_environment_headers(self):
        """Test resolving headers from environment variables."""
        with patch.dict(os.environ, {"AUTH_TOKEN": "secret123"}):
            headers_config = {
                "Authorization_env": "AUTH_TOKEN",
                "Content-Type": "application/json",
            }
            result = _resolve_headers(headers_config)
            assert result == {
                "Authorization": "secret123",
                "Content-Type": "application/json",
            }

    def test_environment_header_missing(self):
        """Test error when environment variable for header not found."""
        with patch.dict(os.environ, {}, clear=True):
            headers_config = {"Auth_env": "MISSING_VAR"}
            with pytest.raises(ValueError, match="Environment variable 'MISSING_VAR' not found"):
                _resolve_headers(headers_config)


class TestBuildPayload:
    """Tests for _build_payload function."""

    def test_mixed_field_types(self):
        """Test building payload with mixed field types."""
        fields_config = {
            "static_field": "literal",
            "dynamic_field": "${title}",
            "special_field": "${query}",
        }
        dynamic_args = {"title": "My Title"}
        special_vars = {"query": "my query"}

        result = _build_payload(fields_config, dynamic_args, special_vars)

        assert result == {
            "static_field": "literal",
            "dynamic_field": "My Title",
            "special_field": "my query",
        }

    def test_all_special_variables(self):
        """Test payload with all special variables."""
        fields_config = {
            "q": "${query}",
            "a": "${answer}",
            "ts": "${timestamp}",
            "m": "${model}",
        }
        special_vars = {
            "query": "test query",
            "answer": "test answer",
            "timestamp": "2024-01-01",
            "model": "gpt-4",
        }

        result = _build_payload(fields_config, {}, special_vars)

        assert result == {
            "q": "test query",
            "a": "test answer",
            "ts": "2024-01-01",
            "m": "gpt-4",
        }


class TestExecutePushData:
    """Tests for execute_push_data function."""

    @patch("asky.plugins.push_data.executor.requests.post")
    @patch("asky.config._CONFIG")
    def test_successful_post(self, mock_config, mock_post):
        """Test successful POST request."""
        mock_config.get.return_value = {
            "test_endpoint": {
                "url": "https://example.com/webhook",
                "method": "post",
                "headers": {"Content-Type": "application/json"},
                "fields": {
                    "query": "${query}",
                    "answer": "${answer}",
                },
            }
        }

        mock_response = Mock()
        mock_response.status_code = 200
        mock_post.return_value = mock_response

        result = execute_push_data(
            "test_endpoint",
            query="test query",
            answer="test answer",
        )

        assert result["success"] is True
        assert result["status_code"] == 200
        assert result["endpoint"] == "test_endpoint"
        mock_post.assert_called_once()

    @patch("asky.plugins.push_data.executor.requests.get")
    @patch("asky.config._CONFIG")
    def test_successful_get(self, mock_config, mock_get):
        """Test successful GET request."""
        mock_config.get.return_value = {
            "test_endpoint": {
                "url": "https://example.com/api",
                "method": "get",
                "fields": {"q": "${query}"},
            }
        }

        mock_response = Mock()
        mock_response.status_code = 200
        mock_get.return_value = mock_response

        result = execute_push_data(
            "test_endpoint",
            query="test query",
        )

        assert result["success"] is True
        assert result["status_code"] == 200
        mock_get.assert_called_once()

    @patch("asky.config._CONFIG")
    def test_endpoint_not_found(self, mock_config):
        """Test error when endpoint not found in configuration."""
        mock_config.get.return_value = {}

        with pytest.raises(ValueError, match="Push data endpoint 'missing' not found"):
            execute_push_data("missing")

    @patch("asky.config._CONFIG")
    def test_missing_url(self, mock_config):
        """Test error when endpoint missing url field."""
        mock_config.get.return_value = {
            "test_endpoint": {
                "method": "post",
            }
        }

        with pytest.raises(ValueError, match="missing 'url' field"):
            execute_push_data("test_endpoint")

    @patch("asky.config._CONFIG")
    def test_invalid_method(self, mock_config):
        """Test error when endpoint has invalid method."""
        mock_config.get.return_value = {
            "test_endpoint": {
                "url": "https://example.com",
                "method": "put",
            }
        }

        with pytest.raises(ValueError, match="invalid method: put"):
            execute_push_data("test_endpoint")

    @patch("asky.plugins.push_data.executor.requests.post")
    @patch("asky.config._CONFIG")
    def test_http_error(self, mock_config, mock_post):
        """Test handling HTTP errors."""
        mock_config.get.return_value = {
            "test_endpoint": {
                "url": "https://example.com/webhook",
                "method": "post",
                "fields": {},
            }
        }

        mock_post.side_effect = requests.RequestException("Network error")

        result = execute_push_data("test_endpoint")

        assert result["success"] is False
        assert "error" in result
        assert "Network error" in result["error"]

    @patch("asky.config._CONFIG")
    def test_missing_dynamic_parameter(self, mock_config):
        """Test error when required dynamic parameter is missing."""
        mock_config.get.return_value = {
            "test_endpoint": {
                "url": "https://example.com",
                "method": "post",
                "fields": {"title": "${title}"},
            }
        }

        result = execute_push_data("test_endpoint", dynamic_args={})

        assert result["success"] is False
        assert "Missing required parameter: title" in result["error"]

    @patch("asky.plugins.push_data.executor.requests.post")
    @patch("asky.config._CONFIG")
    def test_with_dynamic_args(self, mock_config, mock_post):
        """Test passing dynamic arguments."""
        mock_config.get.return_value = {
            "test_endpoint": {
                "url": "https://example.com/webhook",
                "method": "post",
                "fields": {
                    "title": "${title}",
                    "priority": "${priority}",
                    "query": "${query}",
                },
            }
        }

        mock_response = Mock()
        mock_response.status_code = 200
        mock_post.return_value = mock_response

        result = execute_push_data(
            "test_endpoint",
            dynamic_args={"title": "My Title", "priority": "high"},
            query="test query",
        )

        assert result["success"] is True
        # Verify the payload was built correctly
        call_kwargs = mock_post.call_args[1]
        assert call_kwargs["json"]["title"] == "My Title"
        assert call_kwargs["json"]["priority"] == "high"
        assert call_kwargs["json"]["query"] == "test query"


class TestGetEnabledEndpoints:
    """Tests for get_enabled_endpoints function."""

    @patch("asky.config._CONFIG")
    def test_no_endpoints(self, mock_config):
        """Test when no push_data endpoints configured."""
        mock_config.get.return_value = {}
        result = get_enabled_endpoints()
        assert result == {}

    @patch("asky.config._CONFIG")
    def test_all_disabled(self, mock_config):
        """Test when all endpoints are disabled."""
        mock_config.get.return_value = {
            "endpoint1": {"enabled": False},
            "endpoint2": {"enabled": False},
        }
        result = get_enabled_endpoints()
        assert result == {}

    @patch("asky.config._CONFIG")
    def test_mixed_enabled(self, mock_config):
        """Test filtering enabled endpoints."""
        mock_config.get.return_value = {
            "enabled1": {"enabled": True, "url": "https://example.com/1"},
            "disabled1": {"enabled": False, "url": "https://example.com/2"},
            "enabled2": {"enabled": True, "url": "https://example.com/3"},
        }
        result = get_enabled_endpoints()
        assert len(result) == 2
        assert "enabled1" in result
        assert "enabled2" in result
        assert "disabled1" not in result

    @patch("asky.config._CONFIG")
    def test_default_enabled_false(self, mock_config):
        """Test that endpoints without 'enabled' field default to disabled."""
        mock_config.get.return_value = {
            "no_enabled_field": {"url": "https://example.com"},
        }
        result = get_enabled_endpoints()
        assert result == {}
