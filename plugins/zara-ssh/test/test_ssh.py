import hashlib
import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from zara_ssh.backend import ParamikoSFTPBackend
from zara_ssh.domain import HostPolicy, SSHDomain, SSHError
from zara_ssh.plugin import ZaraSSHPlugin


class FakeBackend:
    def __init__(self, payload=b"track-bytes"):
        self.payload = payload
        self.fetch_calls = []

    def status(self):
        return {"status": "ready", "backend": "fake"}

    def stat(self, host_alias, remote_path):
        return {
            "path": remote_path,
            "size": len(self.payload),
            "is_file": True,
        }

    def list_dir(self, host_alias, remote_path, limit):
        return [
            {"name": "song.flac", "size": len(self.payload), "is_file": True}
        ][:limit]

    def fetch(self, host_alias, remote_path, local_path):
        self.fetch_calls.append((host_alias, remote_path, str(local_path)))
        Path(local_path).write_bytes(self.payload)
        return {"accepted": True}


class FakeRuntime:
    def __init__(self):
        self.registrations = []

    def register_symbol(self, symbol, kind, value, **kwargs):
        self.registrations.append((symbol, kind, value, kwargs))
        return len(self.registrations)


class SSHDomainTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.local_root = Path(self.temp.name) / "downloads"
        self.local_root.mkdir()
        self.backend = FakeBackend()
        self.domain = SSHDomain(
            self.backend,
            {
                "media": HostPolicy(
                    alias="media",
                    hostname="musicbox",
                    username="zara",
                    port=22,
                    remote_roots=("/srv/music",),
                    local_roots=(self.local_root,),
                    max_transfer_bytes=1024,
                )
            },
        )

    def tearDown(self):
        self.temp.cleanup()

    def test_host_inventory_is_bounded_and_secret_free(self):
        hosts = self.domain.hosts()
        self.assertEqual(hosts[0]["alias"], "media")
        self.assertEqual(hosts[0]["hostname"], "musicbox")
        self.assertEqual(hosts[0]["username"], "zara")
        self.assertNotIn("key", repr(hosts).lower())

    def test_remote_stat_and_list_are_root_confined(self):
        stat = self.domain.file_stat("media", "/srv/music/album/song.flac")
        self.assertTrue(stat["is_file"])
        listing = self.domain.file_list("media", "/srv/music/album", limit=10)
        self.assertEqual(listing["entries"][0]["name"], "song.flac")
        for path in ("/etc/passwd", "/srv/music/../secret"):
            with self.subTest(path=path):
                with self.assertRaises(SSHError):
                    self.domain.file_stat("media", path)

    def test_fetch_verifies_size_and_digest(self):
        target = self.local_root / "song.flac"
        result = self.domain.file_fetch(
            "media",
            "/srv/music/album/song.flac",
            str(target),
        )
        self.assertTrue(result["verified"])
        self.assertEqual(result["bytes"], len(self.backend.payload))
        self.assertEqual(
            result["sha256"],
            hashlib.sha256(self.backend.payload).hexdigest(),
        )
        self.assertEqual(target.read_bytes(), self.backend.payload)

    def test_fetch_rejects_local_escape_and_existing_destination(self):
        with self.assertRaises(SSHError):
            self.domain.file_fetch(
                "media",
                "/srv/music/song.flac",
                str(Path(self.temp.name) / "outside.flac"),
            )
        target = self.local_root / "existing.flac"
        target.write_bytes(b"old")
        with self.assertRaisesRegex(SSHError, "exists"):
            self.domain.file_fetch("media", "/srv/music/song.flac", str(target))

    def test_fetch_rejects_oversized_remote_file_before_backend_copy(self):
        backend = FakeBackend(payload=b"x" * 2048)
        domain = SSHDomain(backend, self.domain.policies)
        with self.assertRaisesRegex(SSHError, "transfer limit"):
            domain.file_fetch(
                "media",
                "/srv/music/song.flac",
                str(self.local_root / "large.flac"),
            )
        self.assertEqual(backend.fetch_calls, [])

    def test_paramiko_backend_rejects_unknown_hosts_and_uses_key_only_auth(self):
        policy = self.domain.policies["media"]
        backend = ParamikoSFTPBackend({"media": policy})
        client = mock.MagicMock()
        sftp = mock.MagicMock()
        channel = mock.MagicMock()
        attrs = mock.MagicMock()
        attrs.st_size = len(self.backend.payload)
        attrs.st_mode = 0o100644
        sftp.stat.return_value = attrs
        sftp.get_channel.return_value = channel
        client.open_sftp.return_value = sftp
        reject_policy = object()

        with mock.patch("paramiko.SSHClient", return_value=client), mock.patch(
            "paramiko.RejectPolicy",
            return_value=reject_policy,
        ):
            result = backend.stat("media", "/srv/music/song.flac")

        self.assertTrue(result["is_file"])
        client.load_system_host_keys.assert_called_once_with()
        client.set_missing_host_key_policy.assert_called_once_with(reject_policy)
        connect = client.connect.call_args.kwargs
        self.assertEqual(connect["hostname"], "musicbox")
        self.assertEqual(connect["username"], "zara")
        self.assertTrue(connect["allow_agent"])
        self.assertTrue(connect["look_for_keys"])
        self.assertNotIn("password", connect)
        channel.settimeout.assert_called_once_with(15.0)

    def test_configured_missing_known_hosts_fails_before_connect(self):
        policy = HostPolicy(
            alias="media",
            hostname="musicbox",
            username="zara",
            port=22,
            remote_roots=("/srv/music",),
            local_roots=(self.local_root,),
            known_hosts=Path(self.temp.name) / "missing-known-hosts",
        )
        backend = ParamikoSFTPBackend({"media": policy})
        client = mock.MagicMock()
        with mock.patch("paramiko.SSHClient", return_value=client):
            with self.assertRaisesRegex(SSHError, "known_hosts"):
                backend.stat("media", "/srv/music/song.flac")
        client.connect.assert_not_called()

    def test_plugin_surface_and_runtime_symbols(self):
        plugin = ZaraSSHPlugin(self.backend, policies=self.domain.policies)
        names = {tool.name for tool in plugin.tools()}
        self.assertTrue({
            "ssh.status",
            "ssh.hosts",
            "ssh.file.stat",
            "ssh.file.list",
            "ssh.file.fetch",
        }.issubset(names))
        runtime = FakeRuntime()
        plugin.start(runtime)
        registered = {
            (symbol, kind, kwargs["capabilities"])
            for symbol, kind, _, kwargs in runtime.registrations
        }
        self.assertIn(("ssh:file-fetch", "command", ("ssh.file.fetch",)), registered)

    def test_prolog_contract_names_file_fetch_as_write_effect(self):
        source = (ROOT / "prolog" / "zara_ssh_tools.pl").read_text(encoding="utf-8")
        self.assertIn(
            "ssh_tool('file_fetch', 'ssh:file-fetch', 'ssh.file.fetch', write).",
            source,
        )


if __name__ == "__main__":
    unittest.main()
