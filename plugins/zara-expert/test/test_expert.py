import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from zara_expert.domain import ExpertError, ExpertHost


class FakeBackend:
    def __init__(self):
        self.calls = []
        self.responses = {}

    def run(self, request):
        self.calls.append(dict(request))
        response = self.responses.get((request["namespace"], request["operation"]))
        if isinstance(response, Exception):
            raise response
        if response is None:
            return {"ok": True, "results": [], "trace": []}
        return response


class ExpertHostTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.backend = FakeBackend()
        self.host = ExpertHost(
            self.backend,
            state_root=self.root,
            query_timeout_seconds=1.0,
            max_results=4,
        )

    def tearDown(self):
        self.temporary.cleanup()

    def test_two_plugins_are_namespace_isolated(self):
        self.host.register("alpha", [self.root / "alpha.pl"])
        self.host.register("beta", [self.root / "beta.pl"])
        self.backend.responses[("alpha", "query")] = {
            "ok": True,
            "results": [{"value": "alpha"}],
            "trace": ["alpha:fact"],
        }
        self.backend.responses[("beta", "query")] = {
            "ok": True,
            "results": [{"value": "beta"}],
            "trace": ["beta:fact"],
        }

        self.assertEqual(self.host.query("alpha", "thing(X)")["results"][0]["value"], "alpha")
        self.assertEqual(self.host.query("beta", "thing(X)")["results"][0]["value"], "beta")
        self.assertNotEqual(
            self.backend.calls[0]["state_files"],
            self.backend.calls[1]["state_files"],
        )

    def test_query_limits_are_always_forwarded(self):
        self.host.register("alpha", [])
        self.host.query("alpha", "can_handle(test)")
        request = self.backend.calls[-1]
        self.assertEqual(request["timeout_seconds"], 1.0)
        self.assertEqual(request["max_results"], 4)

    def test_session_and_persistent_facts_are_distinct(self):
        self.host.register("alpha", [])
        self.host.assert_fact("alpha", "seen(test)", persistent=False)
        self.host.assert_fact("alpha", "trusted(test)", persistent=True)

        session_file, persistent_file = self.host.state_files("alpha")
        self.assertIn("seen(test).", session_file.read_text(encoding="utf-8"))
        self.assertNotIn("trusted(test).", session_file.read_text(encoding="utf-8"))
        self.assertIn("trusted(test).", persistent_file.read_text(encoding="utf-8"))
        self.assertNotIn("seen(test).", persistent_file.read_text(encoding="utf-8"))

    def test_retract_is_scoped_and_idempotent(self):
        self.host.register("alpha", [])
        self.host.assert_fact("alpha", "seen(test)")
        self.host.assert_fact("beta", "seen(test)")
        self.assertTrue(self.host.retract_fact("alpha", "seen(test)"))
        self.assertFalse(self.host.retract_fact("alpha", "seen(test)"))
        self.assertIn("seen(test).", self.host.state_files("beta")[0].read_text(encoding="utf-8"))

    def test_malformed_or_executable_terms_fail_before_backend(self):
        self.host.register("alpha", [])
        for term in (
            "thing(X). halt",
            "shell('rm -rf /')",
            ":- initialization(halt)",
            "assertz(pwned)",
            "consult('/tmp/x')",
            "x(a);halt",
        ):
            with self.subTest(term=term):
                with self.assertRaises(ExpertError):
                    self.host.query("alpha", term)
        self.assertEqual(self.backend.calls, [])

    def test_fact_mutation_requires_ground_fact_syntax(self):
        self.host.register("alpha", [])
        for fact in ("seen(X)", "seen(a),other(b)", "seen(a):-other(a)"):
            with self.subTest(fact=fact):
                with self.assertRaises(ExpertError):
                    self.host.assert_fact("alpha", fact)

    def test_unregistered_namespace_fails_closed(self):
        with self.assertRaisesRegex(ExpertError, "not registered"):
            self.host.query("missing", "thing(test)")

    def test_backend_failure_is_namespaced_and_does_not_corrupt_state(self):
        self.host.register("alpha", [])
        self.host.assert_fact("alpha", "safe(test)")
        before = self.host.state_files("alpha")[0].read_text(encoding="utf-8")
        self.backend.responses[("alpha", "query")] = ExpertError("backend-failed")
        with self.assertRaisesRegex(ExpertError, "backend-failed"):
            self.host.query("alpha", "safe(test)")
        self.assertEqual(before, self.host.state_files("alpha")[0].read_text(encoding="utf-8"))

    def test_explain_returns_structured_evidence(self):
        self.host.register("alpha", [])
        self.backend.responses[("alpha", "explain")] = {
            "ok": True,
            "results": [{"goal": "verify(build, ok)", "proved": True}],
            "trace": ["rule:verify/2", "fact:build_ok"],
        }
        result = self.host.explain("alpha", "verify(build, ok)")
        self.assertTrue(result["results"][0]["proved"])
        self.assertEqual(result["trace"], ["rule:verify/2", "fact:build_ok"])


if __name__ == "__main__":
    unittest.main()
