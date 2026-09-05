from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from scripts.zara_compat import (
    CompatibilityError,
    exercise_service_lifecycle,
    fake_dependency_environment,
    load_registry,
    plugin_paths,
    require_metadata,
    require_tool_names,
    temporary_runtime_environment,
    validate_zara_source,
)


ROOT = Path(__file__).resolve().parents[1]


class ZaraCompatibilityGateTest(unittest.TestCase):
    def test_registry_enumeration_tracks_every_published_plugin(self) -> None:
        entries = load_registry(ROOT / "plugins.json")
        names = {entry["name"] for entry in entries}

        self.assertIn("zara-agent-zero", names)
        self.assertIn("zara-starintel-server", names)
        self.assertEqual(len(names), len(entries))

    def test_metadata_mismatch_names_the_plugin_and_contract(self) -> None:
        actual = SimpleNamespace(
            name="wrong-name",
            version="9.9.9",
            api_version="1",
            plugin_type="service",
        )

        with self.assertRaisesRegex(
            CompatibilityError,
            "zara-example.*metadata name.*wrong-name",
        ):
            require_metadata(
                {
                    "name": "zara-example",
                    "version": "1.2.3",
                    "api_version": "1",
                    "plugin_type": "service",
                },
                actual,
            )

    def test_tool_names_must_be_unique_within_plugin(self) -> None:
        tools = [SimpleNamespace(name="example.read"), SimpleNamespace(name="example.read")]

        with self.assertRaisesRegex(
            CompatibilityError,
            "zara-example.*duplicate tool name.*example.read",
        ):
            require_tool_names("zara-example", tools, {})

    def test_tool_names_must_be_unique_across_plugins(self) -> None:
        seen: dict[str, str] = {}
        require_tool_names("zara-first", [SimpleNamespace(name="shared.read")], seen)

        with self.assertRaisesRegex(
            CompatibilityError,
            "zara-second.*tool name.*shared.read.*zara-first",
        ):
            require_tool_names("zara-second", [SimpleNamespace(name="shared.read")], seen)

    def test_zara_source_must_contain_the_real_plugin_api(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(
                CompatibilityError,
                "zara.plugins API source",
            ):
                validate_zara_source(Path(directory))

    def test_source_and_installed_runtime_paths_are_distinct(self) -> None:
        entry = {
            "name": "zara-example",
            "path": "plugins/zara-example",
            "entrypoint": "zara-plugin/example.py",
        }
        root = Path("/source")

        source_entrypoint, source_library = plugin_paths(root, entry)
        self.assertEqual(source_entrypoint, Path("/source/plugins/zara-example/zara-plugin/example.py"))
        self.assertEqual(source_library, Path("/source/plugins/zara-example/lib"))

        runtime_entrypoint, runtime_library = plugin_paths(
            root,
            entry,
            runtime_root=Path("/nix/store/runtime/share/zara/runtime"),
        )
        self.assertEqual(
            runtime_entrypoint,
            Path("/nix/store/runtime/share/zara/runtime/zara-example/entrypoint.py"),
        )
        self.assertEqual(
            runtime_library,
            Path("/nix/store/runtime/share/zara/runtime/zara-example/lib"),
        )

    def test_temporary_runtime_environment_confines_all_mutable_xdg_state(self) -> None:
        names = (
            "HOME",
            "XDG_CONFIG_HOME",
            "XDG_DATA_HOME",
            "XDG_CACHE_HOME",
            "XDG_STATE_HOME",
        )
        previous = {name: os.environ.get(name) for name in names}

        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            with temporary_runtime_environment(home):
                self.assertEqual(os.environ["HOME"], str(home))
                for name in names[1:]:
                    path = Path(os.environ[name])
                    self.assertTrue(path.is_dir())
                    self.assertTrue(path.is_relative_to(home))

        for name, value in previous.items():
            self.assertEqual(os.environ.get(name), value)

    def test_fake_dependencies_are_scoped_to_the_plugin_that_needs_them(self) -> None:
        variable = "ZARA_DISCORD_TOKEN"
        previous = os.environ.pop(variable, None)
        try:
            with fake_dependency_environment("zara-browser"):
                self.assertNotIn(variable, os.environ)

            with fake_dependency_environment("zara-discord"):
                self.assertTrue(os.environ.get(variable))

            self.assertNotIn(variable, os.environ)
        finally:
            if previous is not None:
                os.environ[variable] = previous

    def test_service_lifecycle_always_stops_and_shuts_down_runtime(self) -> None:
        calls: list[str] = []

        class Service:
            def start(self, runtime) -> None:
                calls.append("start")
                self.runtime = runtime

            def stop(self) -> None:
                calls.append("stop")

        class Runtime:
            def _shutdown(self) -> None:
                calls.append("shutdown")

        exercise_service_lifecycle(Service(), Runtime())
        self.assertEqual(calls, ["start", "stop", "shutdown"])

    def test_service_lifecycle_cleans_up_after_start_failure(self) -> None:
        calls: list[str] = []

        class Service:
            def start(self, runtime) -> None:
                calls.append("start")
                raise RuntimeError("boom")

            def stop(self) -> None:
                calls.append("stop")

        class Runtime:
            def _shutdown(self) -> None:
                calls.append("shutdown")

        with self.assertRaisesRegex(RuntimeError, "boom"):
            exercise_service_lifecycle(Service(), Runtime())
        self.assertEqual(calls, ["start", "stop", "shutdown"])


if __name__ == "__main__":
    unittest.main()
