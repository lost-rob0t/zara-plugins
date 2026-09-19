from __future__ import annotations

import os
import stat as stat_module
import tempfile
from contextlib import contextmanager
from pathlib import Path

from .domain import HostPolicy, SSHError


class ParamikoSFTPBackend:
    def __init__(self, policies: dict[str, HostPolicy]) -> None:
        self.policies = dict(policies)

    def status(self) -> dict[str, object]:
        try:
            import paramiko
        except ImportError:
            return {"status": "unavailable", "reason": "paramiko-not-installed"}
        if not self.policies:
            return {"status": "unavailable", "reason": "ssh-hosts-not-configured"}
        return {"status": "ready", "transport": "ssh-sftp"}

    def _policy(self, alias: str) -> HostPolicy:
        try:
            return self.policies[alias]
        except KeyError as error:
            raise SSHError("unknown host alias") from error

    @contextmanager
    def _sftp(self, alias: str):
        try:
            import paramiko
        except ImportError as error:
            raise SSHError("paramiko-not-installed") from error

        policy = self._policy(alias)
        client = paramiko.SSHClient()
        client.load_system_host_keys()
        if policy.known_hosts is not None:
            known_hosts = Path(policy.known_hosts).expanduser()
            if not known_hosts.is_file():
                raise SSHError("configured known_hosts file is unavailable")
            client.load_host_keys(str(known_hosts))
        client.set_missing_host_key_policy(paramiko.RejectPolicy())

        identity_file = None
        if policy.identity_file is not None:
            identity_path = Path(policy.identity_file).expanduser()
            if not identity_path.is_file():
                raise SSHError("configured identity file is unavailable")
            identity_file = str(identity_path)

        timeout = float(policy.timeout_seconds)
        try:
            client.connect(
                hostname=policy.hostname,
                port=policy.port,
                username=policy.username,
                key_filename=identity_file,
                timeout=timeout,
                banner_timeout=timeout,
                auth_timeout=timeout,
                allow_agent=True,
                look_for_keys=identity_file is None,
            )
            sftp = client.open_sftp()
            sftp.get_channel().settimeout(timeout)
            try:
                yield sftp
            finally:
                sftp.close()
        except SSHError:
            raise
        except Exception as error:
            raise SSHError("ssh-transport-failed") from error
        finally:
            client.close()

    def stat(self, host_alias: str, remote_path: str) -> dict[str, object]:
        with self._sftp(host_alias) as sftp:
            value = sftp.stat(remote_path)
            return {
                "path": remote_path,
                "size": int(value.st_size),
                "is_file": stat_module.S_ISREG(value.st_mode),
            }

    def list_dir(
        self,
        host_alias: str,
        remote_path: str,
        limit: int,
    ) -> list[dict[str, object]]:
        with self._sftp(host_alias) as sftp:
            values = sftp.listdir_attr(remote_path)
            return [
                {
                    "name": value.filename,
                    "size": int(value.st_size),
                    "is_file": stat_module.S_ISREG(value.st_mode),
                }
                for value in values[:limit]
            ]

    def fetch(
        self,
        host_alias: str,
        remote_path: str,
        local_path: Path,
    ) -> dict[str, object]:
        local_path = Path(local_path)
        temporary = tempfile.NamedTemporaryFile(
            prefix=".zara-ssh-",
            dir=local_path.parent,
            delete=False,
        )
        temporary_path = Path(temporary.name)
        temporary.close()
        try:
            with self._sftp(host_alias) as sftp:
                sftp.get(remote_path, str(temporary_path))
            os.replace(temporary_path, local_path)
            return {"accepted": True}
        except Exception:
            temporary_path.unlink(missing_ok=True)
            raise
