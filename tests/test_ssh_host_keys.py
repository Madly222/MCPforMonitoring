"""SSH host keys: trusted on first use, refused when they change. Uses a real local SSH server."""

import asyncio

import asyncssh
import pytest

import src.core.ssh_manager as sm
from src.core.config import ClaudeConfig, MCPServerConfig, SecretsConfig, ServerConfig
from tests.conftest import FakeConfig


class _Server(asyncssh.SSHServer):
    def begin_auth(self, username):
        return True

    def password_auth_supported(self):
        return True

    def validate_password(self, username, password):
        return password == "secret"


async def _start(key, port=0):
    return await asyncssh.create_server(_Server, "127.0.0.1", port, server_host_keys=[key], reuse_address=True)


async def _stop(server):
    server.close()
    await server.wait_closed()


@pytest.fixture
def env(tmp_path, monkeypatch):
    def configure(policy="tofu"):
        secrets = SecretsConfig(mcp_server=MCPServerConfig(ssh_host_keys=policy), claude=ClaudeConfig())
        monkeypatch.setattr(sm, "get_config", lambda: FakeConfig(secrets))

    monkeypatch.setattr(sm, "KNOWN_HOSTS_FILE", tmp_path / "known_hosts")
    configure()
    return configure


def _server_config(port):
    return ServerConfig(id="s1", host="127.0.0.1", port=port, user="monitor",
                        auth_type="password", auth_value="secret")


async def _connect(port):
    conn = await sm.SSHConnectionPool()._create_connection(_server_config(port))
    conn.close()
    await conn.wait_closed()


def test_first_connection_saves_the_key_and_later_ones_check_it(env):
    async def scenario():
        key = asyncssh.generate_private_key("ssh-ed25519")
        server = await _start(key)
        port = server.sockets[0].getsockname()[1]
        try:
            await _connect(port)
            saved = sm.KNOWN_HOSTS_FILE.read_text(encoding="utf-8")
            assert saved.startswith(f"[127.0.0.1]:{port} ssh-ed25519 ")
            await _connect(port)  # same key: accepted
            assert sm.KNOWN_HOSTS_FILE.read_text(encoding="utf-8") == saved  # not added twice
        finally:
            await _stop(server)

        impostor = await _start(asyncssh.generate_private_key("ssh-ed25519"), port)
        try:
            with pytest.raises(asyncssh.HostKeyNotVerifiable) as exc:
                await _connect(port)
            assert "remove its line" in sm._friendly_ssh_error(str(exc.value))
        finally:
            await _stop(impostor)

    asyncio.run(scenario())


def test_checking_can_be_turned_off(env):
    env("off")

    async def scenario():
        server = await _start(asyncssh.generate_private_key("ssh-ed25519"))
        port = server.sockets[0].getsockname()[1]
        try:
            await _connect(port)
        finally:
            await _stop(server)
        assert not sm.KNOWN_HOSTS_FILE.exists()

    asyncio.run(scenario())


def test_known_hosts_patterns(tmp_path):
    kh = sm.KnownHosts(tmp_path / "known_hosts")
    kh.add("192.0.2.10", 22, asyncssh.generate_private_key("ssh-ed25519"))

    assert kh.has("192.0.2.10", 22)
    assert not kh.has("192.0.2.10", 2222)
    assert not kh.has("192.0.2.1", 22)
