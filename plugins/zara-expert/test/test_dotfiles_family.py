import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from zara_expert.domain import ExpertError
from zara_expert.dotfiles_family import (
    EXPERT_ID,
    descriptor,
    invoke_dotfiles_operation,
    registered_predicates,
)
from zara_expert.dotfiles_handler import make_dotfiles_expert_handler


class FakeHost:
    def __init__(self, matches=None):
        self.matches = matches or {}
        self.calls = []

    def query(self, namespace, predicate, arguments):
        self.calls.append((namespace, predicate, tuple(arguments)))
        return {
            "ok": True,
            "results": list(self.matches.get((predicate, arguments[0]), ())),
            "trace": [],
        }


class DotfilesFamilyTests(unittest.TestCase):
    def test_descriptor_is_symbolic_zero_model_and_child_delegating(self):
        item = descriptor(available=True)
        self.assertEqual(item["protocol"], "ZARA-EXPERT/1")
        self.assertEqual(item["expert_id"], EXPERT_ID)
        self.assertEqual(item["reasoning_kind"], "symbolic")
        self.assertEqual(item["fallback_policy"], "fail_closed")
        self.assertEqual(item["delegation_policy"], "children")
        self.assertEqual(item["resource_limits"], {"max_model_calls": 0})
        self.assertEqual(
            registered_predicates(),
            {
                "nix_path": 1,
                "bash_path": 1,
                "home_manager_owned_path": 1,
                "style_source": 4,
                "style_revision": 2,
            },
        )

    def test_real_brain_shape_selects_nix_without_model_fallback(self):
        host = FakeHost({("nix_path", "flake.nix"): ("nix_path('flake.nix')",)})
        result = invoke_dotfiles_operation(
            host,
            "inspect",
            {
                "path": "flake.nix",
                "source": "{ x = 1; }",
                "source_generation": "generation-1",
            },
        )
        self.assertEqual(result["verdict"], "succeeded")
        self.assertEqual(result["data"]["language"], "nix")
        self.assertEqual(result["data"]["specialist_expert_id"], "zara:expert/nix")
        self.assertEqual(result["model_calls"], 0)
        self.assertEqual(result["effect_receipts"], [])

    def test_ambiguous_or_unknown_path_is_known_fail_closed(self):
        ambiguous = FakeHost(
            {
                ("nix_path", "ambiguous"): ("nix_path(ambiguous)",),
                ("bash_path", "ambiguous"): ("bash_path(ambiguous)",),
            }
        )
        result = invoke_dotfiles_operation(
            ambiguous,
            "inspect",
            {
                "path": "ambiguous",
                "source": "data",
                "source_generation": "generation-1",
            },
        )
        self.assertEqual(result["verdict"], "failed")
        self.assertEqual(result["data"]["reason"], "ambiguous-specialist")
        self.assertEqual(result["model_calls"], 0)

        unknown = invoke_dotfiles_operation(
            FakeHost(),
            "inspect",
            {
                "path": "README.md",
                "source": "text",
                "source_generation": "generation-1",
            },
        )
        self.assertEqual(unknown["verdict"], "failed")
        self.assertEqual(unknown["data"]["reason"], "unsupported-path")
        self.assertEqual(unknown["model_calls"], 0)

    def test_ownership_uses_only_registered_host_predicate(self):
        host = FakeHost(
            {
                ("home_manager_owned_path", "/.config/systemd/user/zara-server.service"): (
                    "home_manager_owned_path('/.config/systemd/user/zara-server.service')",
                )
            }
        )
        result = invoke_dotfiles_operation(
            host,
            "ownership",
            {"path": "/.config/systemd/user/zara-server.service"},
        )
        self.assertEqual(result["verdict"], "succeeded")
        self.assertEqual(result["data"]["owner"], "home_manager")
        self.assertEqual(
            host.calls,
            [
                (
                    "dotfiles-expert",
                    "home_manager_owned_path",
                    ("/.config/systemd/user/zara-server.service",),
                )
            ],
        )

    def test_handler_blocks_effect_path_and_keeps_usage_zero(self):
        handler = make_dotfiles_expert_handler(FakeHost())
        blocked = handler(
            expert_operation="repair.apply",
            repair={"kind": "preview-only"},
            expected_preimage="before",
            source_generation="generation-1",
        )
        self.assertEqual(blocked["verdict"], "blocked")
        self.assertEqual(blocked["usage"], {"model_calls": 0})
        self.assertEqual(blocked["effect_receipts"], [])
        self.assertEqual(blocked["data"]["reason"], "canonical-typed-edit-required")

    def test_input_schema_is_closed(self):
        with self.assertRaisesRegex(ExpertError, "unknown DotfilesExpert input field"):
            invoke_dotfiles_operation(
                FakeHost(),
                "inspect",
                {
                    "path": "flake.nix",
                    "source": "{}",
                    "source_generation": "generation-1",
                    "predicate": "halt",
                },
            )


if __name__ == "__main__":
    unittest.main()
