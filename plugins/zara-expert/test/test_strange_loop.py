import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from zara_expert.domain import ExpertError
from zara_expert.plugin import ZaraExpertPlugin
from zara_expert.strange_loop import StrangeLoopConfig, StrangeLoopManager


class RecordingBackend:
    def __init__(self):
        self.calls = []

    def run(self, request):
        self.calls.append(dict(request))
        return {
            "ok": True,
            "results": ["tick-complete"],
            "trace": ["private-controller"],
        }


class RecordingRuntime:
    def __init__(self, configuration=None):
        self.configuration = configuration or {}
        self.registrations = []

    def register_symbol(self, symbol, kind, value, **metadata):
        self.registrations.append((symbol, kind, value, metadata))
        return len(self.registrations)


class StrangeLoopConfigTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.controller = self.root / "controller.pl"
        self.controller.write_text(
            "strange_loop_tick(_, _, _).\n"
            "strange_loop_status(ready).\n",
            encoding="utf-8",
        )

    def tearDown(self):
        self.temporary.cleanup()

    def test_disabled_defaults_are_provider_free(self):
        config = StrangeLoopConfig.from_mapping(None)
        self.assertFalse(config.enabled)
        self.assertTrue(config.background)
        self.assertEqual(config.max_iterations, 8)
        self.assertEqual(config.max_candidates, 16)

    def test_enabled_loop_requires_trusted_sources(self):
        with self.assertRaisesRegex(ExpertError, "requires trusted Prolog sources"):
            StrangeLoopConfig.from_mapping({"enabled": True})

    def test_unknown_config_key_fails_closed(self):
        with self.assertRaisesRegex(ExpertError, "unknown strange_loop"):
            StrangeLoopConfig.from_mapping(
                {
                    "enabled": False,
                    "surprise": True,
                }
            )

    def test_sources_must_exist_and_be_prolog(self):
        with self.assertRaisesRegex(ExpertError, "does not exist"):
            StrangeLoopConfig.from_mapping(
                {
                    "enabled": True,
                    "sources": [self.root / "missing.pl"],
                }
            )

    def test_plugin_uses_private_host_for_management_tick(self):
        backend = RecordingBackend()
        runtime = RecordingRuntime(
            {
                "plugins": {
                    "zara-expert": {
                        "strange_loop": {
                            "enabled": True,
                            "background": False,
                            "sources": [str(self.controller)],
                            "max_iterations": 3,
                            "max_candidates": 5,
                            "min_improvement": 0.25,
                        }
                    }
                }
            }
        )
        plugin = ZaraExpertPlugin(
            backend=backend,
            state_root=self.root / "state",
        )

        plugin.start(runtime)
        try:
            events = []
            plugin.register_strange_loop_hook(
                "after_tick",
                events.append,
            )
            result = plugin.strange_loop_tick()
            self.assertTrue(result["ok"])
            self.assertEqual(len(backend.calls), 1)

            request = backend.calls[0]
            self.assertEqual(request["namespace"], StrangeLoopManager.NAMESPACE)
            self.assertEqual(
                request["capability"].predicate,
                "strange_loop_tick",
            )
            self.assertEqual(request["arguments"], [3, 5, 0.25])
            self.assertEqual(events[0]["tick"], 1)
            self.assertTrue(events[0]["ok"])

            with self.assertRaisesRegex(ExpertError, "not registered"):
                plugin.query(
                    StrangeLoopManager.NAMESPACE,
                    "strange_loop_tick",
                    [3, 5, 0.25],
                )

            status = json.loads(plugin.status())
            self.assertTrue(status["strange_loop"]["enabled"])
            self.assertEqual(status["strange_loop"]["tick_count"], 1)
            self.assertEqual(status["strange_loop"]["model_calls"], 0)
        finally:
            plugin.stop()

    def test_loop_lifecycle_hooks_are_observers_not_authority(self):
        backend = RecordingBackend()
        runtime = RecordingRuntime(
            {
                "strange_loop": {
                    "enabled": True,
                    "background": False,
                    "sources": [str(self.controller)],
                }
            }
        )
        plugin = ZaraExpertPlugin(
            backend=backend,
            state_root=self.root / "state",
        )
        plugin.start(runtime)
        try:
            seen = []

            def broken(_event):
                raise RuntimeError("observer failed")

            plugin.register_strange_loop_hook("before_tick", broken)
            plugin.register_strange_loop_hook("after_tick", seen.append)
            plugin.strange_loop_tick()

            self.assertEqual(len(seen), 1)
            self.assertEqual(seen[0]["tick"], 1)
        finally:
            plugin.stop()


if __name__ == "__main__":
    unittest.main()
