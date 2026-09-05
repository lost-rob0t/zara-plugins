import json
import subprocess
import sys
import types
import unittest
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from zara_coding.domain import PrologRLMBridge
from zara_coding.repository_evidence import build_repository_evidence
from zara_coding.spec_verify import verify_repository_spec


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


class WorktreeLockedAssertionTests(unittest.TestCase):
    def test_repository_evidence_projects_bounded_worktree_lock_state(self):
        evidence = build_repository_evidence(
            {"root": "/srv/demo", "head": "a" * 40, "branch": "main", "dirty": False},
            worktrees=[
                {
                    "path": "/srv/worktrees/task-17",
                    "head": "b" * 40,
                    "branch": None,
                    "detached": True,
                    "locked": "coding-task:17",
                    "prunable": None,
                }
            ],
        )

        self.assertEqual(
            evidence["values"]["worktree_locked"],
            [{"path": "/srv/worktrees/task-17", "head": "b" * 40, "locked": True}],
        )

    def test_verify_payload_contains_only_structured_worktree_lock_evidence(self):
        calls = []

        def run(argv, **kwargs):
            calls.append((argv, kwargs))
            return subprocess.CompletedProcess(argv, 0, stdout="ok(verification_report{status:passed})\n", stderr="")

        bridge = PrologRLMBridge(Path("/srv/prolog-rlm"), runner=run)
        evidence = build_repository_evidence(
            {"root": "/srv/demo", "head": "a" * 40, "branch": "main", "dirty": False},
            worktrees=[
                {
                    "path": "/srv/worktrees/task-17",
                    "head": "b" * 40,
                    "branch": None,
                    "detached": True,
                    "locked": "coding-task:17",
                    "prunable": None,
                }
            ],
        )

        verify_repository_spec(bridge, "ok(frozen_spec{requirements:[]})", evidence)

        _, kwargs = calls[0]
        _, evidence_input = kwargs["input"].split(".\n", 1)
        payload = json.loads(evidence_input)
        self.assertEqual(
            payload["worktrees"],
            [{"path": "/srv/worktrees/task-17", "head": "b" * 40, "locked": True}],
        )
        self.assertNotIn("coding-task:17", evidence_input)

    @patch("zara_coding.plugin.verify_repository_spec_pure")
    @patch("zara_coding.plugin.build_repository_evidence")
    def test_verify_tool_collects_current_worktree_inventory_with_repository_snapshot(self, build_evidence, verify):
        plugin = ZaraCodingPlugin()
        plugin.inspector = Mock()
        plugin.prolog_rlm = Mock()
        snapshot = {"root": "/srv/demo", "head": "a" * 40, "branch": "main", "dirty": False, "changed_paths": []}
        worktrees = [
            {
                "path": "/srv/worktrees/task-17",
                "head": "b" * 40,
                "branch": None,
                "detached": True,
                "locked": "coding-task:17",
                "prunable": None,
            }
        ]
        plugin.inspector.inspect.return_value = snapshot
        plugin.inspector.worktrees.return_value = worktrees
        evidence = {"source_class": "repository", "trust_class": "observed", "freshness": "current"}
        build_evidence.return_value = evidence
        verify.return_value = {"status": "ok", "outcome": "ok(verification_report{status:passed})"}

        frozen = "ok(frozen_spec{requirements:[]})"
        result = json.loads(plugin.verify_repository_spec("/srv/demo", frozen))

        self.assertEqual(result["status"], "ok")
        plugin.inspector.inspect.assert_called_once_with(Path("/srv/demo"))
        plugin.inspector.worktrees.assert_called_once_with(Path("/srv/demo"), limit=100)
        build_evidence.assert_called_once_with(snapshot, worktrees=worktrees)
        verify.assert_called_once_with(plugin.prolog_rlm, frozen, evidence)

    def test_prolog_registry_and_bridge_define_worktree_locked_as_observed_verification_only(self):
        provider = (ROOT / "prolog" / "zara_coding_assertions.pl").read_text(encoding="utf-8")
        adapter = (ROOT / "prolog" / "zara_coding_verify.pl").read_text(encoding="utf-8")

        self.assertIn("worktree_locked,", provider)
        self.assertIn("worktree_locked_args", provider)
        self.assertIn("worktree_locked_evaluator", provider)
        self.assertIn("collector:_{id:none,version:1}", provider)
        self.assertIn("repository_value(worktree_locked", adapter)
        self.assertIn("worktrees", adapter)
        self.assertNotIn("assertz(", adapter)
        self.assertNotIn("shell(", adapter)


if __name__ == "__main__":
    unittest.main()
