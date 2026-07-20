"""
Server capability profiling.

Detects — once per server, then persists to disk — the facts a command
resolver needs to build correct shell commands *without* asking an LLM:

- init system (systemd / sysvinit)
- distro family + package manager
- presence of systemctl / journalctl / service

Profiles live in ``sessions/server_profiles.json`` (detect-and-own). Steady
state costs **zero** SSH round-trips: a profile is only (re)probed when it is
missing or when ``force=True`` is passed. The single probe runs as one SSH
command and returns ``key=value`` lines, so detection itself is one round-trip.
"""

import json
import threading
from dataclasses import dataclass, asdict
from datetime import datetime
from typing import Optional

from loguru import logger

from src.core.config import SESSIONS_DIR


PROFILE_STORE = SESSIONS_DIR / "server_profiles.json"

# distro family -> package manager
_PKG_MGR = {
    "debian": "apt", "ubuntu": "apt", "raspbian": "apt", "mint": "apt",
    "centos": "yum", "rhel": "yum", "rocky": "yum", "alma": "yum", "almalinux": "yum",
    "fedora": "dnf",
    "alpine": "apk",
    "arch": "pacman", "manjaro": "pacman",
    "opensuse": "zypper", "sles": "zypper",
}

# Single combined probe. Emits `key=value` lines; one SSH round-trip.
PROBE_COMMAND = (
    "if command -v systemctl >/dev/null 2>&1 && systemctl --version >/dev/null 2>&1; "
    "then echo init=systemd; elif [ -d /etc/init.d ]; then echo init=sysvinit; "
    "else echo init=unknown; fi; "
    "command -v systemctl >/dev/null 2>&1 && echo systemctl=1 || echo systemctl=0; "
    "command -v journalctl >/dev/null 2>&1 && echo journalctl=1 || echo journalctl=0; "
    "command -v service >/dev/null 2>&1 && echo service=1 || echo service=0; "
    ". /etc/os-release 2>/dev/null; echo distro=${ID:-unknown}"
)


@dataclass
class ServerProfile:
    """Cached capabilities of a single monitored server."""
    server_id: str
    init_system: str = "unknown"     # systemd | sysvinit | unknown
    distro: str = "unknown"          # debian | ubuntu | centos | ...
    pkg_mgr: str = "unknown"         # apt | yum | dnf | ...
    has_systemctl: bool = False
    has_journalctl: bool = False
    has_service: bool = False
    detected_at: Optional[str] = None

    @property
    def signature(self) -> str:
        """Compact capability key. Scopes the resolver cache so a command
        resolved against one profile is never replayed on a different one."""
        return f"{self.init_system}:{self.distro}:{int(self.has_journalctl)}"

    @property
    def is_systemd(self) -> bool:
        return self.init_system == "systemd"


def _parse_probe(output: str) -> dict:
    parsed: dict[str, str] = {}
    for line in output.splitlines():
        line = line.strip()
        if "=" in line:
            key, _, value = line.partition("=")
            parsed[key.strip()] = value.strip()
    return parsed


class ProfileDetector:
    """Detects and persists :class:`ServerProfile` objects."""

    def __init__(self):
        self._lock = threading.Lock()
        self._profiles: dict[str, ServerProfile] = {}
        self._loaded = False

    def _load(self) -> None:
        if self._loaded:
            return
        if PROFILE_STORE.exists():
            try:
                with open(PROFILE_STORE, "r", encoding="utf-8") as f:
                    raw = json.load(f)
                for sid, data in raw.items():
                    self._profiles[sid] = ServerProfile(**data)
            except Exception as e:
                logger.error(f"Failed to load server profiles: {e}")
        self._loaded = True

    def _save(self) -> None:
        PROFILE_STORE.parent.mkdir(parents=True, exist_ok=True)
        tmp = PROFILE_STORE.with_suffix(".json.tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(
                {sid: asdict(p) for sid, p in self._profiles.items()},
                f, indent=2, ensure_ascii=False,
            )
        tmp.replace(PROFILE_STORE)

    def get_cached(self, server_id: str) -> Optional[ServerProfile]:
        with self._lock:
            self._load()
            return self._profiles.get(server_id)

    async def detect(
        self,
        server_id: str,
        ssh,
        distro_hint: Optional[str] = None,
        force: bool = False,
    ) -> ServerProfile:
        """Return the cached profile, or probe the server once and cache it.

        ``ssh`` is anything exposing ``async execute(server_id, command) ->
        result`` with ``.stdout`` (the project's ``SSHManager``). ``distro_hint``
        is used only if ``/etc/os-release`` yields nothing useful.
        """
        with self._lock:
            self._load()
            if not force and server_id in self._profiles:
                return self._profiles[server_id]

        result = await ssh.execute(server_id, PROBE_COMMAND, timeout=15.0)
        fields = _parse_probe(result.stdout or "")

        distro = fields.get("distro", "unknown")
        if distro in ("", "unknown") and distro_hint:
            distro = distro_hint.lower()

        profile = ServerProfile(
            server_id=server_id,
            init_system=fields.get("init", "unknown"),
            distro=distro,
            pkg_mgr=_PKG_MGR.get(distro, "unknown"),
            has_systemctl=fields.get("systemctl") == "1",
            has_journalctl=fields.get("journalctl") == "1",
            has_service=fields.get("service") == "1",
            detected_at=datetime.now().isoformat(timespec="seconds"),
        )

        # Fallback if the probe came back empty (e.g. connection hiccup).
        if profile.init_system == "unknown" and not fields:
            logger.warning(f"Profile probe empty for {server_id}; using init detection fallback")
            init_sys = await ssh.detect_init_system(server_id)
            profile.init_system = getattr(init_sys, "value", "unknown")

        with self._lock:
            self._profiles[server_id] = profile
            self._save()

        logger.info(
            f"Profiled {server_id}: init={profile.init_system} "
            f"distro={profile.distro} journalctl={profile.has_journalctl}"
        )
        return profile

    def forget(self, server_id: str) -> None:
        """Drop a cached profile so it is re-probed next time (e.g. after a
        server is migrated systemd<->sysvinit)."""
        with self._lock:
            self._load()
            if server_id in self._profiles:
                del self._profiles[server_id]
                self._save()


_detector: Optional[ProfileDetector] = None


def get_profile_detector() -> ProfileDetector:
    global _detector
    if _detector is None:
        _detector = ProfileDetector()
    return _detector
