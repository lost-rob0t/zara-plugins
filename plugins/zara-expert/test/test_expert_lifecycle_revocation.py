import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from zara_expert.domain import ExpertError, ExpertHost
from zara_expert.language_family import registered_predicates
from zara_expert.plugin import ZaraExpertPlugin


class RecordingBackend:
    def __init__(self):
        self.calls = []

    def run(self, request):
        self.calls.append(dict(request))
        return {
            "ok": True,
            "results": ["evidence:compiler"],
            "trace": ["source:canonical"],
        }


class RecordingRuntime:
    def __init__(self, configuration=None):
        self.configuration = configuration or {}
        self.registrations = []

    def register_symbol(self, symbol, kind, value, **metadata):
        self.registrations.append((symbol, kind, value, metadata))
        return len(self.registrations)


class ExpertLifecycleRevocationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.backend = RecordingBackend()

    def tearDown(self):
        self.temporary.cleanup()

    def _brain(self, name):
        path = self.root / f"{name}.pl"
        exports = [
            *(f"{predicate}/{arity}" for predicate, arity in registered_predicates().items()),
            "provider_policy/1",
            "max_model_calls/1",
            "model_calls/1",
        ]
        module_name = name.replace("-", "_")
        path.write_text(
            f":- module({module_name}, [{', '.join(exports)}]).\n"
            "provider_policy(disabled).\n"
            "max_model_calls(0).\n"
            "model_calls(0).\n",
            encoding="utf-8",
        )
        return path

    def test_host_clear_revokes_capabilities_but_preserves_durable_state(self):
        source = self._brain("python-host")
        host = ExpertHost(self.backend, state_root=self.root / "state")
        host.register(
            "python-expert",
            [source],
            predicates={"language_evidence": 3},
        )
        host.assert_fact("python-expert", "remembered(value)", persistent=True)
        host.query(
            "python-expert",
            "language_evidence",
            ["print('ok')", "generation-1", {"var": "Evidence"}],
        )

        self.assertEqual(host.clear_registrations(), ("python-expert",))
        with self.assertRaisesRegex(ExpertError, "is not registered"):
            host.query(
                "python-expert",
                "language_evidence",
                ["print('late')", "generation-1", {"var": "Evidence"}],
            )

        _, persistent_path = host.state_files("python-expert")
        self.assertIn("remembered(value).", persistent_path.read_text(encoding="utf-8"))
        self.assertEqual(host.clear_registrations(), ())

    def test_plugin_stop_fences_captured_handler_and_allows_clean_restart(self):
        first_source = self._brain("python-first")
        second_source = self._brain("python-second")
        runtime = RecordingRuntime(
            {"language_expert_sources": {"python": [str(first_source)]}}
        )
        plugin = ZaraExpertPlugin(
            backend=self.backend,
            state_root=self.root / "plugin-state",
        )
        plugin.start(runtime)
        stale_handler = plugin.language_expert_handler("python")

        first = stale_handler(
            expert_operation="inspect",
            source="print('first')",
            source_generation="generation-1",
        )
        self.assertEqual(first["usage"]["model_calls"], 0)
        calls_before_stop = len(self.backend.calls)

        plugin.stop()
        with self.assertRaisesRegex(ExpertError, "is not registered"):
            stale_handler(
                expert_operation="inspect",
                source="print('late')",
                source_generation="generation-1",
            )
        self.assertEqual(len(self.backend.calls), calls_before_stop)
        status = json.loads(plugin.status())
        self.assertEqual(status["language_family"], [])
        self.assertEqual(status["model_calls"], 0)

        runtime.configuration = {
            "language_expert_sources": {"python": [str(second_source)]}
        }
        plugin.start(runtime)
        fresh_handler = plugin.language_expert_handler("python")
        second = fresh_handler(
            expert_operation="inspect",
            source="print('second')",
            source_generation="generation-2",
        )
        self.assertEqual(second["usage"]["model_calls"], 0)
        self.assertEqual(
            self.backend.calls[-1]["knowledge_bases"],
            (str(second_source.resolve()),),
        )


if __name__ == "__main__":
    unittest.main()
