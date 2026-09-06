import json
import subprocess
import sys
import tempfile
import types
import unittest
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from zara_coding.domain import CodingError, RepositoryInspector


@dataclass(frozen=True)
class PluginMetadata:
    name: str
    version: str = ""
    api_version: str = "1"
    description: str = ""


class ServicePlugin:
    pass


zara = types.ModuleType("zara")
zara_plugins = types.ModuleType("zara.plugins")
zara_plugins.PluginMetadata = PluginMetadata
zara_plugins.ServicePlugin = ServicePlugin
sys.modules.setdefault("zara", zara)
sys.modules.setdefault("zara.plugins", zara_plugins)

from zara_coding.plugin import ZaraCodingPlugin


class BranchCreateTests(unittest.TestCase):
    def test_domain_creates_branch_with_atomic_head_fence(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repo = root / "repo"
            repo.mkdir()
            calls = []
            expected_head = "a" * 40

            def run(argv, **kwargs):
                calls.append((argv, kwargs))
                args = tuple(argv[3:])
                if args == ("rev-parse", "--show-toplevel"):
                    output = f"{repo.resolve()}\n"
                else:
                    output = ""
                return subprocess.CompletedProcess(argv, 0, stdout=output, stderr="")

            inspector = RepositoryInspector((root,), runner=run)
            evidence = inspector.create_branch(repo, "feature/safe", expected_head)

            self.assertEqual(evidence, {"branch": "feature/safe", "head": expected_head})
            argv_calls = [call[0][3:] for call in calls]
            self.assertIn(["check-ref-format", "refs/heads/feature/safe"], argv_calls)
            self.assertNotIn(["rev-parse", "HEAD"], argv_calls)
            update_calls = [call for call in calls if call[0][3:] == ["update-ref", "--stdin"]]
            self.assertEqual(len(update_calls), 1)
            _, kwargs = update_calls[0]
            self.assertEqual(
                kwargs["input"],
                "start\n"
                f"verify HEAD {expected_head}\n"
                f"create refs/heads/feature/safe {expected_head}\n"
                "prepare\n"
                "commit\n",
            )
            self.assertTrue(all(call[1]["shell"] is False for call in calls))

    def test_domain_fails_closed_when_atomic_transaction_rejects_stale_head(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repo = root / "repo"
            repo.mkdir()
            calls = []
            expected_head = "a" * 40

            def run(argv, **kwargs):
                calls.append((argv, kwargs))
                args = tuple(argv[3:])
                if args == ("rev-parse", "--show-toplevel"):
                    return subprocess.CompletedProcess(argv, 0, stdout=f"{repo.resolve()}\n", stderr="")
                if args == ("update-ref", "--stdin"):
                    raise subprocess.CalledProcessError(1, argv)
                return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

            inspector = RepositoryInspector((root,), runner=run)
            with self.assertRaisesRegex(CodingError, "git operation failed: update-ref --stdin"):
                inspector.create_branch(repo, "feature/stale", expected_head)
            self.assertNotIn(["rev-parse", "HEAD"], [call[0][3:] for call in calls])

    def test_domain_fails_closed_when_branch_already_exists(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repo = root / "repo"
            repo.mkdir()
            expected_head = "a" * 40

            def run(argv, **kwargs):
                args = tuple(argv[3:])
                if args == ("rev-parse", "--show-toplevel"):
                    return subprocess.CompletedProcess(argv, 0, stdout=f"{repo.resolve()}\n", stderr="")
                if args == ("update-ref", "--stdin"):
                    raise subprocess.CalledProcessError(1, argv)
                return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

            inspector = RepositoryInspector((root,), runner=run)
            with self.assertRaisesRegex(CodingError, "git operation failed"):
                inspector.create_branch(repo, "existing", expected_head)

    @patch("zara_coding.plugin.shutil.which", return_value="/usr/bin/git")
    @patch("zara_coding.plugin.RepositoryInspector.create_branch")
    def test_plugin_branch_create_requires_canonical_approval(self, create_branch, _which):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repo = root / "repo"
            repo.mkdir()
            expected_head = "b" * 40
            create_branch.return_value = {"branch": "feature/safe", "head": expected_head}
            plugin = ZaraCodingPlugin()
            plugin.start(type("Runtime", (), {"configuration": {"plugins": {"zara-coding": {"allowed_roots": [str(root)]}}}})())
            tools = {tool.name: tool for tool in plugin.tools()}
            self.assertTrue(bool((tools["coding.git.branch.create"].metadata or {}).get("zara_requires_approval", False)))
            evidence = json.loads(plugin.git_branch_create(str(repo), "feature/safe", expected_head))
            self.assertEqual(evidence["branch"], "feature/safe")
            create_branch.assert_called_once_with(repo, "feature/safe", expected_head)


if __name__ == "__main__":
    unittest.main()
