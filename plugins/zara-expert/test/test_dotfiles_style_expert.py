import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from zara_expert.composition import CompositionError, InvocationFence, SharedSymbolicBudget
from zara_expert.dotfiles_style_expert import (
    STYLE_EXPERT_ID,
    STYLE_NAMESPACE,
    compose_dotfiles_style,
    register_dotfiles_style_expert,
)


def _hex_json(payload):
    text = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return "".join(f"{ord(char):06x}" for char in text)


def _rule(
    rule_id,
    scope,
    language,
    check,
    preferred,
    revision,
    source,
    kind,
    *,
    project_id="workspace:style-test",
    project_generation=7,
):
    return {
        "id": rule_id,
        "scope": scope,
        "language": language,
        "project_id": project_id,
        "project_generation": project_generation,
        "check": check,
        "preferred": preferred,
        "autofix": "none",
        "provenance": {"source": source, "kind": kind, "scope": scope},
        "revision": revision,
        "overrides": [],
    }


class FakeStyleExpertHost:
    def __init__(self, *, policy="style_policy(disabled,0,0)", payload=None, on_query=None):
        self.policy = policy
        self.payload = payload or {"rules": []}
        self.on_query = on_query
        self.calls = []
        self.registrations = []

    def preflight_registration(self, namespace, files, *, predicates):
        self.registrations.append(("preflight", namespace, tuple(files), dict(predicates)))

    def register(self, namespace, files, *, predicates):
        self.registrations.append(("register", namespace, tuple(files), dict(predicates)))

    def query(self, namespace, predicate, arguments):
        self.calls.append((namespace, predicate, arguments))
        if self.on_query is not None:
            self.on_query(len(self.calls), predicate)
        if predicate == "style_policy":
            return {"ok": True, "results": [self.policy], "trace": []}
        if predicate == "style_rules_json_hex":
            project_id, generation, language = arguments[:3]
            payload = {
                "project_id": project_id,
                "project_generation": generation,
                "language": language,
                **self.payload,
            }
            encoded = _hex_json(payload)
            return {
                "ok": True,
                "results": [
                    f"style_rules_json_hex('{project_id}',{generation},{language},{encoded})"
                ],
                "trace": [],
            }
        return {"ok": True, "results": [], "trace": []}


class DotfilesStyleExpertTests(unittest.TestCase):
    def setUp(self):
        self.cancelled = False
        self.current_generation = 7
        self.project_rule = _rule(
            "dotfiles.project.expert_runtime.hidden_model_fallback",
            "project_global",
            "any",
            "expert_runtime.hidden_model_fallback",
            False,
            "dotfiles-project-style-v1",
            ".zara/experts/AGENTS.md",
            "authored",
        )
        self.language_rule = _rule(
            "dotfiles.nix.formatting.formatter",
            "project_language",
            "nix",
            "formatting.formatter",
            "nixfmt-rfc-style",
            "dotfiles-nix-style-v1",
            ".prolog/kb/literate_sync.pl",
            "durable_kb",
        )

    def _fence(self):
        return InvocationFence(
            workspace_id="workspace:style-test",
            workspace_generation=7,
            is_cancelled=lambda: self.cancelled,
            is_current_generation=lambda workspace_id, generation: (
                workspace_id == "workspace:style-test"
                and generation == self.current_generation
            ),
        )

    @staticmethod
    def _resolver(rules, context):
        decisions = []
        for rule in rules:
            decisions.append(
                {
                    "check": rule["check"],
                    "winner": rule["id"],
                    "winner_scope": rule["scope"],
                    "winner_revision": rule["revision"],
                    "winner_provenance": rule["provenance"],
                    "shadowed": [],
                    "shadowed_provenance": [],
                }
            )
        return {
            "effective": list(rules),
            "decisions": decisions,
            "project_id": context["project_id"],
            "project_generation": context["project_generation"],
            "language": context["language"],
            "usage": {"model_calls": 0},
        }

    def test_registers_only_fixed_style_transport_predicates(self):
        host = FakeStyleExpertHost()
        with tempfile.TemporaryDirectory() as tmp:
            producer = Path(tmp) / "expert.pl"
            producer.write_text("% producer fixture\n", encoding="utf-8")
            register_dotfiles_style_expert(host, producer)

        self.assertEqual(len(host.registrations), 2)
        for _, namespace, files, predicates in host.registrations:
            self.assertEqual(namespace, STYLE_NAMESPACE)
            self.assertEqual(
                predicates,
                {"style_policy": 3, "style_rules_json_hex": 4},
            )
            self.assertEqual(len(files), 2)
            self.assertTrue(files[0].endswith("expert.pl"))
            self.assertTrue(files[1].endswith("style_transport_bridge.pl"))

    def test_composes_real_style_rule_payload_under_same_zero_model_budget(self):
        host = FakeStyleExpertHost(payload={"rules": [self.project_rule, self.language_rule]})
        budget = SharedSymbolicBudget(max_model_calls=0)
        result = compose_dotfiles_style(
            host,
            "nix",
            resolver=self._resolver,
            budget=budget,
            fence=self._fence(),
        )

        self.assertEqual(result.expert_id, STYLE_EXPERT_ID)
        self.assertEqual(result.rules, (self.project_rule, self.language_rule))
        self.assertEqual(result.resolution.effective, (self.project_rule, self.language_rule))
        self.assertIn("style-expert:provider_policy=disabled", result.evidence)
        self.assertIn("style-expert:model_calls=0", result.evidence)
        self.assertIn(
            "style:formatting.formatter:winner:dotfiles.nix.formatting.formatter@dotfiles-nix-style-v1",
            result.evidence,
        )
        self.assertIn("Dotfiles StyleExpert", result.explanation)
        self.assertEqual(budget.max_model_calls, 0)
        self.assertEqual(budget.model_calls_used, 0)
        self.assertEqual(budget.evidence_used, len(result.evidence))
        self.assertTrue(all(call[0] == STYLE_NAMESPACE for call in host.calls))

    def test_accepts_canonical_user_and_project_scope_bindings(self):
        user_global = _rule(
            "user.global.response.concise",
            "user_global",
            "any",
            "response.concise",
            True,
            "user-global-v1",
            "user:style",
            "user_preference",
            project_id="any",
            project_generation="any",
        )
        user_language = _rule(
            "user.nix.formatting.width",
            "user_language",
            "nix",
            "formatting.width",
            88,
            "user-nix-v1",
            "user:nix-style",
            "user_preference",
            project_id="any",
            project_generation="any",
        )
        rules = (user_global, user_language, self.project_rule, self.language_rule)
        host = FakeStyleExpertHost(payload={"rules": list(rules)})
        budget = SharedSymbolicBudget(max_model_calls=0)

        result = compose_dotfiles_style(
            host,
            "nix",
            resolver=self._resolver,
            budget=budget,
            fence=self._fence(),
        )

        self.assertEqual(result.rules, rules)
        self.assertEqual(result.resolution.effective, rules)
        self.assertEqual(budget.model_calls_used, 0)
        self.assertEqual(budget.evidence_used, len(result.evidence))

    def test_rejects_user_scope_forged_as_project_bound_before_resolver(self):
        cases = (
            ("user_global", "any"),
            ("user_language", "nix"),
        )
        for scope, language in cases:
            with self.subTest(scope=scope):
                forged = _rule(
                    f"forged.{scope}",
                    scope,
                    language,
                    "response.concise",
                    True,
                    "forged-v1",
                    "forged:source",
                    "user_preference",
                )
                host = FakeStyleExpertHost(payload={"rules": [forged]})
                resolver_called = False

                def resolver(_rules, _context):
                    nonlocal resolver_called
                    resolver_called = True
                    return {}

                with self.assertRaisesRegex(CompositionError, "scope binding mismatch"):
                    compose_dotfiles_style(
                        host,
                        "nix",
                        resolver=resolver,
                        budget=SharedSymbolicBudget(max_model_calls=0),
                        fence=self._fence(),
                    )
                self.assertFalse(resolver_called)

    def test_composition_fails_closed_when_shared_evidence_budget_is_exhausted(self):
        host = FakeStyleExpertHost(payload={"rules": [self.project_rule]})
        budget = SharedSymbolicBudget(max_evidence=1, max_model_calls=0)

        with self.assertRaisesRegex(CompositionError, "expert evidence budget exceeded"):
            compose_dotfiles_style(
                host,
                "nix",
                resolver=self._resolver,
                budget=budget,
                fence=self._fence(),
            )

        self.assertEqual(budget.evidence_used, 0)
        self.assertEqual(budget.model_calls_used, 0)
        self.assertEqual(len(host.calls), 2)

    def test_policy_must_disable_providers_and_keep_both_ledgers_zero(self):
        cases = (
            "style_policy(enabled,0,0)",
            "style_policy(disabled,1,0)",
            "style_policy(disabled,0,1)",
        )
        for policy in cases:
            with self.subTest(policy=policy):
                host = FakeStyleExpertHost(policy=policy, payload={"rules": [self.project_rule]})
                with self.assertRaisesRegex(CompositionError, "zero-model policy"):
                    compose_dotfiles_style(
                        host,
                        "nix",
                        resolver=self._resolver,
                        budget=SharedSymbolicBudget(max_model_calls=0),
                        fence=self._fence(),
                    )
                self.assertEqual(len(host.calls), 1)

    def test_malformed_transport_payload_fails_before_overlay_resolver(self):
        host = FakeStyleExpertHost(payload={"rules": "not-a-list"})
        resolver_called = False

        def resolver(_rules, _context):
            nonlocal resolver_called
            resolver_called = True
            return {}

        with self.assertRaisesRegex(CompositionError, "style rules payload"):
            compose_dotfiles_style(
                host,
                "nix",
                resolver=resolver,
                budget=SharedSymbolicBudget(max_model_calls=0),
                fence=self._fence(),
            )
        self.assertFalse(resolver_called)

    def test_generation_change_during_registered_predicate_read_fails_closed(self):
        def advance(call_count, predicate):
            if call_count == 2 and predicate == "style_rules_json_hex":
                self.current_generation = 8

        host = FakeStyleExpertHost(
            payload={"rules": [self.project_rule]},
            on_query=advance,
        )
        with self.assertRaisesRegex(CompositionError, "stale workspace generation"):
            compose_dotfiles_style(
                host,
                "nix",
                resolver=self._resolver,
                budget=SharedSymbolicBudget(max_model_calls=0),
                fence=self._fence(),
            )
        self.assertEqual(len(host.calls), 2)

    def test_unsupported_language_fails_without_host_or_resolver_fallback(self):
        host = FakeStyleExpertHost(payload={"rules": [self.project_rule]})
        with self.assertRaisesRegex(CompositionError, "unsupported Dotfiles StyleExpert language"):
            compose_dotfiles_style(
                host,
                "python",
                resolver=self._resolver,
                budget=SharedSymbolicBudget(max_model_calls=0),
                fence=self._fence(),
            )
        self.assertEqual(host.calls, [])


if __name__ == "__main__":
    unittest.main()
