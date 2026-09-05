import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from zara_coding.domain import CodingError, PrologRLMBridge


class PrologRLMSpecCompileTests(unittest.TestCase):
    def test_compile_spec_uses_fixed_trusted_registry_and_stdin_source(self):
        source = (
            "spec([subject(repository(demo)),"
            "require(head,assertion(repository_head,_{head:'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa'}))])."
        )
        calls = []

        def run(argv, **kwargs):
            calls.append((argv, kwargs))
            return subprocess.CompletedProcess(
                argv,
                0,
                stdout=(
                    "ok(frozen_spec{ref:spec_ref{series:zara_coding,version:1,"
                    "fingerprint:'deadbeef'}})\n"
                ),
                stderr="",
            )

        bridge = PrologRLMBridge(Path("/srv/prolog-rlm"), runner=run)
        result = bridge.compile_spec(source)

        self.assertEqual(result["status"], "ok")
        argv, kwargs = calls[0]
        self.assertEqual(kwargs["input"], source)
        self.assertFalse(kwargs["shell"])
        self.assertNotIn(source, " ".join(argv))
        self.assertIn("rlm_spec_lang.pl", " ".join(argv))
        self.assertIn("zara_coding_assertions.pl", " ".join(argv))
        goal = argv[argv.index("-g") + 1]
        self.assertIn("zara_coding_assertions:registry(R)", goal)
        self.assertIn("spec_source_compile(S,R,[series(zara_coding),version(1)],O)", goal)

    def test_compile_spec_preserves_canonical_rejection(self):
        def run(argv, **kwargs):
            return subprocess.CompletedProcess(
                argv,
                0,
                stdout="error(spec_lang_error{operation:compile,reason:unknown_assertion_kind(nope,1)})\n",
                stderr="",
            )

        bridge = PrologRLMBridge(Path("/srv/prolog-rlm"), runner=run)
        result = bridge.compile_spec(
            "spec([subject(repository(demo)),require(x,assertion(nope,_{}))])."
        )
        self.assertEqual(result["status"], "rejected")
        self.assertIn("unknown_assertion_kind", result["outcome"])

    def test_compile_spec_rejects_oversized_source_before_prolog(self):
        bridge = PrologRLMBridge(
            Path("/srv/prolog-rlm"),
            runner=lambda *args, **kwargs: self.fail("runner must not be called"),
        )
        with self.assertRaisesRegex(CodingError, "65536"):
            bridge.compile_spec("x" * (PrologRLMBridge.MAX_SPEC_CHARS + 1))

    def test_trusted_registry_source_is_static_and_non_dynamic(self):
        provider = ROOT / "prolog" / "zara_coding_assertions.pl"
        source = provider.read_text(encoding="utf-8")
        self.assertIn("registry([", source)
        self.assertIn("assertion_provider(repository_head", source)
        self.assertIn("assertion_provider(repository_clean", source)
        self.assertNotIn(":- dynamic", source)
        self.assertNotIn("assertz(", source)
        self.assertNotIn("consult(", source)
        self.assertNotIn("shell(", source)


if __name__ == "__main__":
    unittest.main()
