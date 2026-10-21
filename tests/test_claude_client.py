"""ClaudeClient._ask: request shape and how replies are read."""

import asyncio
from types import SimpleNamespace

import pytest

from src.core.claude_client import ClaudeClient
from src.core.config import ClaudeConfig, MCPServerConfig, SecretsConfig
from tests.conftest import FakeConfig


class FakeMessages:
    def __init__(self, response):
        self.response = response
        self.calls = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        return self.response


def make_client(response, **claude_overrides):
    secrets = SecretsConfig(
        mcp_server=MCPServerConfig(),
        claude=ClaudeConfig(api_key="test", **claude_overrides),
    )
    client = ClaudeClient.__new__(ClaudeClient)
    client.config = FakeConfig(secrets)
    client._cache = {}
    client._request_times = []
    messages = FakeMessages(response)
    client._client = SimpleNamespace(messages=messages)
    return client, messages


def reply(*blocks, stop_reason="end_turn"):
    return SimpleNamespace(content=list(blocks), stop_reason=stop_reason)


def text(value):
    return SimpleNamespace(type="text", text=value)


THINKING = SimpleNamespace(type="thinking", thinking="")


def test_text_is_read_past_the_thinking_block():
    client, _ = make_client(reply(THINKING, text('{"ok": '), text("true}")))

    assert asyncio.run(client._ask("sys", "hi")) == '{"ok": true}'


def test_request_carries_model_effort_and_max_tokens():
    client, messages = make_client(reply(text("x")), model="claude-opus-5-5", effort="low", max_tokens=16000)

    asyncio.run(client._ask("sys", "hi"))

    call = messages.calls[0]
    assert call["model"] == "claude-opus-5-5"
    assert call["max_tokens"] == 16000
    assert call["output_config"] == {"effort": "low"}
    assert call["system"] == "sys"
    assert call["messages"] == [{"role": "user", "content": "hi"}]


def test_effort_can_be_turned_off():
    client, messages = make_client(reply(text("x")), effort=None)

    asyncio.run(client._ask("sys", "hi"))

    assert "output_config" not in messages.calls[0]


@pytest.mark.parametrize("stop_reason", ["refusal", "max_tokens"])
def test_incomplete_replies_raise(stop_reason):
    client, _ = make_client(reply(THINKING, stop_reason=stop_reason))

    with pytest.raises(RuntimeError):
        asyncio.run(client._ask("sys", "hi"))
