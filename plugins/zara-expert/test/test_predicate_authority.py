import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from zara_expert.domain import ExpertError, ExpertHost


class RecordingBackend:
    def __init__(self):
        self.calls = []

    def run(self, request):
        self.calls.append(dict(request))
        return {"ok": True, "results": [], "trace": []}


class PredicateAuthorityTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.backend = RecordingBackend()
        self.host = ExpertHost(self.backend, state_root=Path(self.temporary.name))
        self.host.register(
            "alpha",
            [],
            predicates={"thing": 1, "verify": 2, "can_handle": 1},
        )

    def tearDown(self):
        self.temporary.cleanup()

    def test_unregistered_predicate_fails_before_backend(self):
        with self.assertRaisesRegex(ExpertError, "not registered"):
            self.host.query("alpha", "shell", ["echo pwned"])
        self.assertEqual(self.backend.calls, [])

    def test_meta_module_directive_and_builtin_names_are_not_authority(self):
        variable = {"var": "X"}
        for predicate in ("call", "once", "system", "open", "process_create", "consult", "assertz", "retract"):
            with self.subTest(predicate=predicate):
                with self.assertRaises(ExpertError):
                    self.host.query("alpha", predicate, [variable])
        for predicate in ("user:thing", ":-", "thing/1", "thing(X)"):
            with self.subTest(predicate=predicate):
                with self.assertRaises(ExpertError):
                    self.host.query("alpha", predicate, [variable])
        self.assertEqual(self.backend.calls, [])

    def test_arity_is_owned_by_registration(self):
        with self.assertRaisesRegex(ExpertError, "arity"):
            self.host.query("alpha", "verify", ["build"])
        with self.assertRaisesRegex(ExpertError, "arity"):
            self.host.query("alpha", "thing", ["a", "b"])
        self.assertEqual(self.backend.calls, [])

    def test_argument_string_is_data_not_prolog_source(self):
        payload = "x),halt,thing(y"
        self.host.query("alpha", "thing", [payload])
        request = self.backend.calls[-1]
        self.assertEqual(request["predicate"], "thing")
        self.assertEqual(request["arguments"], [payload])
        self.assertNotIn("goal", request)

    def test_registered_query_uses_structured_descriptor(self):
        variable = {"var": "Result"}
        self.host.query("alpha", "verify", ["build", variable])
        request = self.backend.calls[-1]
        self.assertEqual(request["predicate"], "verify")
        self.assertEqual(request["arguments"], ["build", variable])
        self.assertEqual(request["arity"], 2)
        self.assertNotIn("goal", request)

    def test_explain_uses_same_registered_authority_path(self):
        variable = {"var": "Result"}
        self.host.explain("alpha", "verify", ["build", variable])
        request = self.backend.calls[-1]
        self.assertEqual(request["operation"], "explain")
        self.assertEqual(request["predicate"], "verify")
        self.assertEqual(request["arity"], 2)
        self.assertNotIn("goal", request)

    def test_deep_or_oversized_arguments_fail_before_backend(self):
        with self.assertRaises(ExpertError):
            self.host.query("alpha", "thing", ["x" * 4097])
        with self.assertRaises(ExpertError):
            self.host.query("alpha", "thing", [[[[[["x"]]]]]])
        self.assertEqual(self.backend.calls, [])


if __name__ == "__main__":
    unittest.main()
