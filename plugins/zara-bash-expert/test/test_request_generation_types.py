from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from zara_bash_expert import BashExpertAdapterError, create_plugin


ACTIVATION_ID = "act:" + ("f" * 32)


class NoDispatchRuntime:
    def __init__(self) -> None:
        self.resolved: list[str] = []
        self.requests: list[dict[str, object]] = []

    def resolve_capability(self, capability: str):
        self.resolved.append(capability)
        return object()

    def invoke_capability(self, _handle, request):
        self.requests.append(request)
        raise AssertionError("forged request generation must fail before host dispatch")


class BashExpertRequestGenerationTypeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.runtime = NoDispatchRuntime()
        self.plugin = create_plugin()
        self.plugin.start(self.runtime)

    def test_rejects_non_integer_expected_generations_before_host(self) -> None:
        cases = (
            (True, 1, "invalid-registry-generation"),
            (1.0, 1, "invalid-registry-generation"),
            (1, True, "invalid-runtime-generation"),
            (1, 1.0, "invalid-runtime-generation"),
        )
        for registry_generation, runtime_generation, error in cases:
            with self.subTest(
                registry_generation=registry_generation,
                runtime_generation=runtime_generation,
            ):
                with self.assertRaisesRegex(BashExpertAdapterError, error):
                    self.plugin.invoke(
                        "req:bash-strict-request-generation",
                        ACTIVATION_ID,
                        "inspect_startup",
                        registry_generation,
                        runtime_generation,
                        json.dumps({"path": ".bashrc"}),
                    )
        self.assertEqual(self.runtime.resolved, [])
        self.assertEqual(self.runtime.requests, [])


if __name__ == "__main__":
    unittest.main()
