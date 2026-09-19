from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path

from langchain_core.tools import StructuredTool
from zara.plugins import PluginMetadata, ServicePlugin

from .backend import ParamikoSFTPBackend
from .domain import HostPolicy, SSHDomain, SSHError


PLUGIN_VERSION = "0.1.0"
APPROVAL_METADATA = {"zara_requires_approval": True}


class UnavailableSSHBackend:
    reason = "ssh-hosts-not-configured"

    def status(self) -> dict[str, object]:
        return {"status": "unavailable", "reason": self.reason}

    def __getattr__(self, name):
        raise SSHError(self.reason)


class ZaraSSHPlugin(ServicePlugin):
    metadata = PluginMetadata(
        name="zara-ssh",
        version=PLUGIN_VERSION,
        api_version="1",
        description="Bounded SSH/SFTP remote file transport with strict host verification",
    )

    _SYMBOLS = (
        ("ssh:hosts", "ssh.hosts", "List configured non-secret SSH host aliases."),
        ("ssh:file-stat", "ssh.file.stat", "Inspect one root-confined remote path."),
        ("ssh:file-list", "ssh.file.list", "List one bounded root-confined remote directory."),
        ("ssh:file-fetch", "ssh.file.fetch", "Fetch one root-confined remote file into an allowlisted local root."),
    )

    def __init__(
        self,
        backend=None,
        *,
        policies: Mapping[str, HostPolicy] | None = None,
    ) -> None:
        self._injected_backend = backend
        self._injected_policies = None if policies is None else dict(policies)
        selected_policies = self._injected_policies or {}
        selected_backend = backend or UnavailableSSHBackend()
        self.domain = SSHDomain(selected_backend, selected_policies)

    def start(self, runtime) -> None:
        if self._injected_policies is None:
            section = self._section(runtime.configuration)
            policies = self._policies(section)
            backend = ParamikoSFTPBackend(policies) if policies else UnavailableSSHBackend()
            self.domain = SSHDomain(
                backend,
                policies,
                max_list_entries=self._positive_int(
                    section.get("max_list_entries", 100),
                    "max_list_entries",
                    maximum=1000,
                ),
            )

        registrar = getattr(runtime, "register_symbol", None)
        if not callable(registrar):
            return

        methods = {
            "ssh.hosts": self.hosts,
            "ssh.file.stat": self.file_stat,
            "ssh.file.list": self.file_list,
            "ssh.file.fetch": self.file_fetch,
        }
        for symbol, capability, docs in self._SYMBOLS:
            registrar(
                symbol,
                "command",
                methods[capability],
                docs=docs,
                capabilities=(capability,),
                source="prolog/zara_ssh_tools.pl",
            )

    def stop(self) -> None:
        return None

    @staticmethod
    def _json(value: object) -> str:
        return json.dumps(value, ensure_ascii=False, sort_keys=True)

    def status(self) -> str:
        return self._json(self.domain.status())

    def hosts(self) -> str:
        return self._json(self.domain.hosts())

    def file_stat(self, host_alias: str, remote_path: str) -> str:
        return self._json(self.domain.file_stat(host_alias, remote_path))

    def file_list(self, host_alias: str, remote_path: str, limit: int = 50) -> str:
        return self._json(self.domain.file_list(host_alias, remote_path, limit=limit))

    def file_fetch(self, host_alias: str, remote_path: str, local_path: str) -> str:
        return self._json(self.domain.file_fetch(host_alias, remote_path, local_path))

    def tools(self):
        return (
            StructuredTool.from_function(
                func=self.status,
                name="ssh.status",
                description="Report bounded SSH/SFTP transport readiness.",
            ),
            StructuredTool.from_function(
                func=self.hosts,
                name="ssh.hosts",
                description="List configured SSH host aliases without credentials or key material.",
            ),
            StructuredTool.from_function(
                func=self.file_stat,
                name="ssh.file.stat",
                description="Inspect one remote path beneath the host's configured roots.",
            ),
            StructuredTool.from_function(
                func=self.file_list,
                name="ssh.file.list",
                description="List a bounded remote directory beneath the host's configured roots.",
            ),
            StructuredTool.from_function(
                func=self.file_fetch,
                name="ssh.file.fetch",
                description="Fetch one remote file into a configured local root and verify size plus SHA-256.",
                metadata=APPROVAL_METADATA,
            ),
        )

    @staticmethod
    def _section(configuration: object) -> Mapping[str, object]:
        if not isinstance(configuration, Mapping):
            return {}
        plugins = configuration.get("plugins")
        if not isinstance(plugins, Mapping):
            return {}
        section = plugins.get("zara-ssh")
        if section is None:
            return {}
        if not isinstance(section, Mapping):
            raise SSHError("zara-ssh configuration must be a mapping")
        return section

    @classmethod
    def _policies(cls, section: Mapping[str, object]) -> dict[str, HostPolicy]:
        hosts = section.get("hosts", {})
        if not isinstance(hosts, Mapping):
            raise SSHError("zara-ssh hosts must be a mapping")
        if len(hosts) > 64:
            raise SSHError("zara-ssh host policy limit exceeded")
        policies = {}
        for alias, value in hosts.items():
            if not isinstance(alias, str) or not isinstance(value, Mapping):
                raise SSHError("zara-ssh host entries must be named mappings")
            hostname = cls._string(value.get("hostname"), "hostname")
            username = cls._string(value.get("username"), "username")
            port = cls._positive_int(value.get("port", 22), "port", maximum=65535)
            remote_roots = cls._strings(value.get("remote_roots"), "remote_roots")
            local_roots = tuple(
                Path(path).expanduser()
                for path in cls._strings(value.get("local_roots"), "local_roots")
            )
            known_hosts_value = value.get("known_hosts")
            identity_value = value.get("identity_file")
            policies[alias] = HostPolicy(
                alias=alias,
                hostname=hostname,
                username=username,
                port=port,
                remote_roots=remote_roots,
                local_roots=local_roots,
                max_transfer_bytes=cls._positive_int(
                    value.get("max_transfer_bytes", 1024 * 1024 * 1024),
                    "max_transfer_bytes",
                    maximum=64 * 1024 * 1024 * 1024,
                ),
                known_hosts=None
                if known_hosts_value in (None, "")
                else Path(cls._string(known_hosts_value, "known_hosts")).expanduser(),
                identity_file=None
                if identity_value in (None, "")
                else Path(cls._string(identity_value, "identity_file")).expanduser(),
                timeout_seconds=cls._finite_number(
                    value.get("timeout_seconds", 15.0),
                    "timeout_seconds",
                    minimum=0.1,
                    maximum=300.0,
                ),
            )
        return policies

    @staticmethod
    def _string(value: object, name: str) -> str:
        if not isinstance(value, str) or not value.strip() or value != value.strip():
            raise SSHError(f"zara-ssh {name} must be a canonical non-empty string")
        if len(value.encode("utf-8")) > 4096 or any(ord(character) < 0x20 for character in value):
            raise SSHError(f"zara-ssh {name} is invalid")
        return value

    @classmethod
    def _strings(cls, value: object, name: str) -> tuple[str, ...]:
        if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
            raise SSHError(f"zara-ssh {name} must be a list")
        normalized = tuple(cls._string(item, name) for item in value)
        if not normalized:
            raise SSHError(f"zara-ssh {name} must not be empty")
        return normalized

    @staticmethod
    def _positive_int(value: object, name: str, *, maximum: int) -> int:
        if type(value) is not int or not 1 <= value <= maximum:
            raise SSHError(f"zara-ssh {name} must be an integer between 1 and {maximum}")
        return value

    @staticmethod
    def _finite_number(
        value: object,
        name: str,
        *,
        minimum: float,
        maximum: float,
    ) -> float:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise SSHError(f"zara-ssh {name} must be numeric")
        normalized = float(value)
        if not minimum <= normalized <= maximum:
            raise SSHError(
                f"zara-ssh {name} must be between {minimum} and {maximum}"
            )
        return normalized


def create_plugin():
    return ZaraSSHPlugin()
