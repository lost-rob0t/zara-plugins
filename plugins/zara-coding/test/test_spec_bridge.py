import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from zara_coding.domain import CodingError, PrologRLMBridge


class PrologRLMSpecBridgeTests(unittest.TestCase):
    def test_spec_catalog_uses_canonical_language_with_no_plugin_owned_assertions(self):
        calls = []

        def run(argv, **kwargs):
            calls.append((argv, kwargs))
            return subprocess.CompletedProcess(
                argv,
                0,
                stdout="ok(spec_language_catalog{schema_version:1,symbols:[spec_symbol{name:spec}],assertions:[]})\n",
                stderr="",
            )

        bridge = PrologRLMBridge(Path("/srv/prolog-rlm"), runner=run)
        result = bridge.spec_catalog()
        self.assertEqual(result["status"], "ok")
        self.assertIn("assertions:[]", result["outcome"])
        argv, kwargs = calls[0]
        self.assertIn("rlm_spec_lang.pl", argv[argv.index("-s") + 1])
        goal = argv[argv.index("-g") + 1]
        self.assertIn("spec_language_catalog([],O)", goal)
        self.assertFalse(kwargs["shell"])
        self.assertNotIn("input", kwargs)

    def test_spec_catalog_runtime_failure_does_not_claim_catalog(self):
        def run(argv, **kwargs):
            raise subprocess.TimeoutExpired(argv, 5)

        bridge = PrologRLMBridge(Path("/srv/prolog-rlm"), runner=run)
        with self.assertRaisesRegex(CodingError, "SPEC catalog failed"):
            bridge.spec_catalog()

    def test_normalize_spec_sends_source_only_over_stdin(self):
        source = "spec([subject(project(demo)),require(done,assertion(test_passes,_{name:unit}))])."
        calls = []

        def run(argv, **kwargs):
            calls.append((argv, kwargs))
            return subprocess.CompletedProcess(
                argv,
                0,
                stdout="ok(spec{schema_version:1,subject:project(demo),requirements:[]})\n",
                stderr="",
            )

        bridge = PrologRLMBridge(Path("/srv/prolog-rlm"), runner=run)
        result = bridge.normalize_spec(source)
        self.assertEqual(result["status"], "ok")
        self.assertTrue(result["outcome"].startswith("ok("))
        argv, kwargs = calls[0]
        self.assertNotIn(source, " ".join(argv))
        self.assertEqual(kwargs["input"], source)
        self.assertFalse(kwargs["shell"])
        self.assertIn("rlm_spec_lang.pl", argv[argv.index("-s") + 1])
        self.assertIn("read_string(user_input", argv[argv.index("-g") + 1])

    def test_normalize_spec_preserves_prolog_rejection_as_evidence(self):
        def run(argv, **kwargs):
            return subprocess.CompletedProcess(
                argv,
                0,
                stdout="error(spec_lang_error{operation:normalize,reason:forbidden_functor(shell/1)})\n",
                stderr="",
            )

        bridge = PrologRLMBridge(Path("/srv/prolog-rlm"), runner=run)
        result = bridge.normalize_spec("spec([subject(x),invariant(shell('nope'))]).")
        self.assertEqual(result["status"], "rejected")
        self.assertIn("forbidden_functor", result["outcome"])

    def test_normalize_spec_rejects_empty_source_before_spawning_prolog(self):
        bridge = PrologRLMBridge(
            Path("/srv/prolog-rlm"),
            runner=lambda *args, **kwargs: self.fail("runner must not be called"),
        )
        with self.assertRaisesRegex(CodingError, "non-empty"):
            bridge.normalize_spec("")

    def test_normalize_spec_rejects_oversized_source_before_spawning_prolog(self):
        bridge = PrologRLMBridge(
            Path("/srv/prolog-rlm"),
            runner=lambda *args, **kwargs: self.fail("runner must not be called"),
        )
        with self.assertRaisesRegex(CodingError, "65536"):
            bridge.normalize_spec("x" * (PrologRLMBridge.MAX_SPEC_CHARS + 1))

    def test_normalize_spec_runtime_failure_is_not_reported_as_rejection(self):
        def run(argv, **kwargs):
            raise subprocess.TimeoutExpired(argv, 5)

        bridge = PrologRLMBridge(Path("/srv/prolog-rlm"), runner=run)
        with self.assertRaisesRegex(CodingError, "SPEC normalization failed"):
            bridge.normalize_spec("spec([subject(x),require(a,assertion(k,_{}))]).")


if __name__ == "__main__":
    unittest.main()
