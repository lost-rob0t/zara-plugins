from __future__ import annotations

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ZaraVoicePiperPackagingTest(unittest.TestCase):
    def setUp(self) -> None:
        registry = json.loads((ROOT / "plugins.json").read_text(encoding="utf-8"))
        self.entry = next(
            plugin for plugin in registry["plugins"] if plugin["name"] == "zara-voice"
        )
        self.flake = (ROOT / "flake.nix").read_text(encoding="utf-8")

    def test_registry_declares_piper_runtime_dependency(self) -> None:
        dependencies = self.entry.get("python_dependencies", [])
        self.assertIn("piper-tts", dependencies)

    def test_piper_is_resolved_as_bounded_inference_only_python_module(self) -> None:
        self.assertIn('dependency == "piper-tts"', self.flake)
        self.assertIn("packages.toPythonModule", self.flake)
        self.assertIn("pkgs.piper-tts.override", self.flake)
        self.assertIn("withTrain = false;", self.flake)
        self.assertIn("withHTTP = false;", self.flake)
        self.assertIn("withAlignment = false;", self.flake)

    def test_runtime_layout_proves_packaged_piper_importability(self) -> None:
        self.assertIn("pluginPackages.zara-voice", self.flake)
        self.assertIn("import piper, onnxruntime, pathvalidate, zara_voice", self.flake)


if __name__ == "__main__":
    unittest.main()
