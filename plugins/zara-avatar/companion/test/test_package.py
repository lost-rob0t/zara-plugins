import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
import xml.etree.ElementTree as ET

BASE = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("stage_assets", BASE / "stage_assets.py")
STAGE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(STAGE)
ANDROID = "{http://schemas.android.com/apk/res/android}"

class PackageTests(unittest.TestCase):
    def test_permissions_are_overlay_only_and_service_is_private(self):
        root = ET.parse(BASE / "app/src/main/AndroidManifest.xml").getroot()
        names = {item.attrib[ANDROID + "name"] for item in root.findall("uses-permission")}
        self.assertEqual(names, {"android.permission.SYSTEM_ALERT_WINDOW", "android.permission.FOREGROUND_SERVICE",
            "android.permission.FOREGROUND_SERVICE_SPECIAL_USE", "android.permission.POST_NOTIFICATIONS"})
        services = root.findall("application/service")
        self.assertEqual(len(services), 1)
        self.assertEqual(services[0].attrib[ANDROID + "exported"], "false")
        self.assertEqual(services[0].attrib[ANDROID + "foregroundServiceType"], "specialUse")
        self.assertEqual(root.find("application").attrib[ANDROID + "label"], "Zara Companion")

    def fixture(self, parent):
        renderer = parent / "renderer"
        packages = {}
        for package, names in STAGE.FILES.items():
            root = renderer / "node_modules" / package
            root.mkdir(parents=True)
            (root / "package.json").write_text(json.dumps({"version": "1.0.0"}))
            packages["node_modules/" + package] = {"version": "1.0.0", "integrity": "sha512-test-fixture-only"}
            for name in names:
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                content = "fixture"
                if name.endswith("GLTFLoader.js"):
                    content = "export {} from 'three';"
                elif package == "@pixiv/three-vrm" and name.endswith("three-vrm.module.js"):
                    content = 'export {} from "three";'
                path.write_text(content)
        (renderer / "package-lock.json").write_text(json.dumps({"packages": packages}))
        return renderer

    def test_assets_use_fixed_local_imports_and_license_receipt(self):
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory); renderer = self.fixture(parent)
            STAGE.stage(parent / "output", renderer)
            root = parent / "output/companion"
            html = (root / "index.html").read_text()
            self.assertIn("script-src 'self'", html)
            self.assertNotIn('type="importmap"', html)
            self.assertNotIn("https://", html)
            self.assertNotIn("unsafe-eval", html)
            self.assertIn("../../../build/three.module.js",
                (root / "vendor/three/examples/jsm/loaders/GLTFLoader.js").read_text())
            self.assertIn("../three/build/three.module.js",
                (root / "vendor/three-vrm/three-vrm.module.js").read_text())
            self.assertTrue((root / "vendor/three/LICENSE").is_file())
            self.assertTrue((root / "vendor/three-vrm/LICENSE").is_file())
            self.assertEqual(len(json.loads((root / "dependencies.json").read_text())), 7)

    def test_missing_or_wrong_dependency_fails_without_replacing_assets(self):
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory); renderer = self.fixture(parent)
            output = parent / "output/companion"; output.mkdir(parents=True)
            marker = output / "keep"; marker.write_text("old")
            (renderer / "node_modules/three/build/three.core.js").unlink()
            with self.assertRaises(ValueError): STAGE.stage(parent / "output", renderer)
            self.assertEqual(marker.read_text(), "old")
            (renderer / "node_modules/three/package.json").write_text('{"version":"wrong"}')
            with self.assertRaises(ValueError): STAGE.stage(parent / "output", renderer)

if __name__ == "__main__": unittest.main()
