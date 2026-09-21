"""Feed the real Prolog/Python/Nim expert chain into Zara symbolic conversation state."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import types
import unittest
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
DOTFILES_ROOT = os.environ.get("ZARA_DOTFILES_ROOT")
ZARA_CORE_ROOT = os.environ.get("ZARA_CORE_ROOT")
EXPECTED_DOTFILES_COMMIT = "fe8f7fa3c42803e0e505dcb6f7e4600d27649d9e"
EXPECTED_ZARA_CORE_COMMIT = "1095bc5537c98c555c29ac29ed335843191c558d"
ZARA_EXPERT_LIB = REPO_ROOT / "plugins" / "zara-expert" / "lib"

if ZARA_CORE_ROOT:
    sys.path.insert(0, str(Path(ZARA_CORE_ROOT).resolve()))
sys.path.insert(0, str(ZARA_EXPERT_LIB))

from zara_expert.backend import SwiplBackend
from zara_expert.domain import ExpertHost
from zara_expert.language_family import descriptors, register_language_family
from zara_expert.language_handler import make_language_expert_handler
from zara_expert.language_source_contract import validate_language_source_contracts

if ZARA_CORE_ROOT:
    # ConversationStore only needs PrincipalContext from zara.server, but the
    # public server facade also imports the entire long-lived runtime/plugin
    # stack. Keep this acceptance focused on the canonical conversation owner
    # by binding that facade name to the same canonical PrincipalContext type.
    from zara.principals import PrincipalContext

    server_facade = types.ModuleType("zara.server")
    server_facade.PrincipalContext = PrincipalContext
    sys.modules["zara.server"] = server_facade

    from zara.database import DatabaseManager
    from zara.desktop.conversation import ConversationStore, SymbolicConversationProjection
    from zara.desktop.conversation.models import MessageRecord, MessageRole, MessageStatus
    from zara.experts import ExpertDescriptor, ExpertLimits, ExpertRegistry, ExpertVerdict


_PROVIDER_CREDENTIALS = (
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "OPENROUTER_API_KEY",
    "GOOGLE_API_KEY",
    "GEMINI_API_KEY",
    "GROQ_API_KEY",
    "ZAI_API_KEY",
    "AZURE_OPENAI_API_KEY",
    "HF_TOKEN",
)
_SYMBOLIC_RENDERER = "symbolic-dcg/v1"
_WORKSPACE = "workspace:prolog-python-nim-symbolic-conversation"


def _run(*argv: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        argv,
        cwd=cwd,
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def _checkout_head(root: Path, expected: str, label: str) -> None:
    result = _run("git", "rev-parse", "HEAD", cwd=root)
    if result.returncode != 0:
        raise AssertionError(f"cannot resolve {label} checkout: {result.stderr}")
    actual = result.stdout.strip()
    if actual != expected:
        raise AssertionError(
            f"{label} checkout must be exact: expected {expected}, got {actual}"
        )


def _provider_free_env() -> dict[str, str]:
    env = os.environ.copy()
    for name in _PROVIDER_CREDENTIALS:
        env.pop(name, None)
    return env


@unittest.skipUnless(
    DOTFILES_ROOT and ZARA_CORE_ROOT,
    "exact Dotfiles and Zara Core checkouts not provided",
)
class PrologPythonNimSymbolicConversationE2ETests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.dotfiles_root = Path(DOTFILES_ROOT).resolve()
        cls.zara_core_root = Path(ZARA_CORE_ROOT).resolve()
        if shutil.which("swipl") is None:
            raise AssertionError("SWI-Prolog is required for symbolic conversation E2E")
        _checkout_head(cls.dotfiles_root, EXPECTED_DOTFILES_COMMIT, "Dotfiles producer")
        _checkout_head(cls.zara_core_root, EXPECTED_ZARA_CORE_COMMIT, "Zara Core")
        cls.sources = {
            language: [
                cls.dotfiles_root
                / ".zara"
                / "experts"
                / language
                / "kb"
                / "expert.pl"
            ]
            for language in ("prolog", "python", "nim")
        }
        for paths in cls.sources.values():
            for source in paths:
                if not source.is_file():
                    raise AssertionError(f"missing canonical expert source: {source}")

    def _runtime(self, state_root: Path):
        validate_language_source_contracts(self.sources)
        host = ExpertHost(SwiplBackend(), state_root=state_root)
        registered = register_language_family(host, self.sources)
        self.assertEqual(registered, frozenset({"prolog", "python", "nim"}))
        published = {item["expert_id"]: item for item in descriptors(registered)}
        handlers = {
            expert_id: make_language_expert_handler(host, expert_id)
            for expert_id in (
                "zara:expert/prolog",
                "zara:expert/python",
                "zara:expert/nim",
            )
        }
        return published, handlers

    @staticmethod
    def _activate(registry, expert_id: str):
        handle, receipt = registry.activate(
            "expert-builder-3",
            _WORKSPACE,
            expert_id,
            expected_registry_generation=registry.generation,
            expected_runtime_generation=registry.runtime_generation,
        )
        if receipt["state"] != "active":
            raise AssertionError(f"failed to activate {expert_id}: {receipt!r}")
        return handle

    def _run_symbolic_dialogue(self, evidence_ref: str) -> tuple[str, str]:
        summary = "Prolog, Python, and Nim inspection complete."
        goal = (
            f"EvidenceRef={json.dumps(evidence_ref)},"
            f"Summary={json.dumps(summary)},"
            "symbolic_dialogue:response_act("
            "expert_result(summary(Summary),evidence(EvidenceRef)),Act),"
            "symbolic_dialogue:render_response(Act,Answer),"
            "symbolic_dialogue:symbolic_follow_up("
            '"why did you do that?",Act,Why,WhyEvidence),'
            "WhyEvidence=evidence(renderer('symbolic-dcg/v1'),provider_calls(0),model_calls(0)),"
            "format('~s~n~s~n',[Answer,Why]),halt(0)"
        )
        completed = subprocess.run(
            [
                "swipl",
                "-q",
                "-s",
                str(self.zara_core_root / "modules" / "symbolic_dialogue.pl"),
                "-g",
                goal,
                "-t",
                "halt(1)",
            ],
            cwd=self.zara_core_root,
            env=_provider_free_env(),
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        lines = completed.stdout.splitlines()
        self.assertEqual(len(lines), 2, completed.stdout + completed.stderr)
        return lines[0], lines[1]

    @staticmethod
    def _message(
        conversation_id: str,
        sequence: int,
        turn_id: str,
        role,
        content: str,
    ):
        timestamp = f"2026-09-21T01:00:{sequence:02d}.000000"
        return MessageRecord(
            id=f"message-{sequence}",
            conversation_id=conversation_id,
            sequence=sequence,
            turn_id=turn_id,
            role=role,
            content=content,
            status=MessageStatus.COMPLETE,
            created_at=timestamp,
            updated_at=timestamp,
        )

    def test_real_three_expert_chain_survives_restart_and_answers_why(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        published, handlers = self._runtime(root / "expert-state")
        registry = ExpertRegistry(engines=("swipl",))
        handles: dict[str, Any] = {}
        child_results: dict[str, Any] = {}
        prolog_handler = handlers["zara:expert/prolog"]
        python_handler = handlers["zara:expert/python"]

        def delegating_python(*, expert_operation: str, **payload: Any) -> dict[str, Any]:
            result = python_handler(expert_operation=expert_operation, **payload)
            child_results["nim"] = registry.invoke(
                handles["zara:expert/nim"],
                "inspect",
                {
                    "source": "proc answer(): int = 42\n",
                    "source_generation": "conversation-nim-1",
                },
                limits=ExpertLimits(max_model_calls=64),
            )
            return result

        def delegating_prolog(*, expert_operation: str, **payload: Any) -> dict[str, Any]:
            result = prolog_handler(expert_operation=expert_operation, **payload)
            child_results["python"] = registry.invoke(
                handles["zara:expert/python"],
                "inspect",
                {
                    "source": "def answer():\n    return 42\n",
                    "source_generation": "conversation-python-1",
                },
                limits=ExpertLimits(max_model_calls=64),
            )
            return result

        for expert_id in (
            "zara:expert/prolog",
            "zara:expert/python",
            "zara:expert/nim",
        ):
            handler = handlers[expert_id]
            if expert_id == "zara:expert/prolog":
                handler = delegating_prolog
            elif expert_id == "zara:expert/python":
                handler = delegating_python
            registry.register(ExpertDescriptor.from_wire(published[expert_id]), handler)

        for expert_id in (
            "zara:expert/prolog",
            "zara:expert/python",
            "zara:expert/nim",
        ):
            handles[expert_id] = self._activate(registry, expert_id)

        root_result = registry.invoke(
            handles["zara:expert/prolog"],
            "inspect",
            {
                "source": "fact(conversation_ready).",
                "source_generation": "conversation-prolog-1",
            },
            limits=ExpertLimits(max_model_calls=0),
        )

        results = (root_result, child_results["python"], child_results["nim"])
        for result in results:
            self.assertIs(result.verdict, ExpertVerdict.SUCCEEDED)
            self.assertTrue(result.evidence_refs)
            self.assertEqual(result.effect_receipts, ())
            self.assertIs(type(result.usage["model_calls"]), int)
            self.assertEqual(result.usage["model_calls"], 0)

        invocation_ids = registry.snapshot().invocation_ids
        self.assertEqual(len(invocation_ids), 3)
        traces = [registry.explain(invocation_id) for invocation_id in invocation_ids]
        by_expert = {trace["expert_id"]: trace for trace in traces}
        self.assertEqual(
            set(by_expert),
            {"zara:expert/prolog", "zara:expert/python", "zara:expert/nim"},
        )
        expert_evidence = []
        for expert_id in (
            "zara:expert/prolog",
            "zara:expert/python",
            "zara:expert/nim",
        ):
            trace = by_expert[expert_id]
            self.assertEqual(trace["verdict"], "succeeded")
            self.assertTrue(trace["evidence_refs"])
            self.assertEqual(trace.get("effect_receipts", []), [])
            self.assertIs(type(trace["usage"]["model_calls"]), int)
            self.assertEqual(trace["usage"]["model_calls"], 0)
            expert_evidence.append(
                {
                    "expert_id": expert_id,
                    "invocation_id": trace["invocation_id"],
                    "evidence_refs": list(trace["evidence_refs"]),
                    "verdict": trace["verdict"],
                    "model_calls": trace["usage"]["model_calls"],
                }
            )

        root_evidence_ref = root_result.evidence_refs[0]
        answer, why = self._run_symbolic_dialogue(root_evidence_ref)
        self.assertEqual(answer, "Prolog, Python, and Nim inspection complete.")
        self.assertEqual(why, f"I answered from evidence {root_evidence_ref}.")

        database_path = root / "conversation.db"
        database = DatabaseManager(database_path)
        store = ConversationStore(database)
        conversation = store.create_conversation(
            "Pure symbolic language chain",
            conversation_id="conversation:prolog-python-nim",
        )
        store.save_message(
            self._message(
                conversation.id,
                1,
                "turn:inspect",
                MessageRole.USER,
                "Inspect this Prolog and follow the language chain.",
            )
        )
        store.save_message(
            self._message(
                conversation.id,
                2,
                "turn:inspect",
                MessageRole.ASSISTANT,
                answer,
            )
        )
        first_projection = store.save_symbolic_projection(
            SymbolicConversationProjection(
                conversation_id=conversation.id,
                projection_generation=1,
                runtime_generation=1,
                turn_id="turn:inspect",
                outcome="success",
                project_id=_WORKSPACE,
                project_generation=1,
                dialogue_act="expert.answer",
                dialogue_state={
                    "root_expert": "zara:expert/prolog",
                    "selected_experts": [
                        "zara:expert/prolog",
                        "zara:expert/python",
                        "zara:expert/nim",
                    ],
                },
                expert_evidence=expert_evidence,
                renderer_provenance=_SYMBOLIC_RENDERER,
                providers_enabled=False,
                max_model_calls=0,
                provider_calls=0,
                model_calls=0,
            ),
            expected_generation=0,
        )
        first_projection.assert_pure_symbolic()
        database.close()

        reopened_database = DatabaseManager(database_path)
        reopened = ConversationStore(reopened_database)
        recovered = reopened.load_symbolic_projection(conversation.id)
        self.assertIsNotNone(recovered)
        assert recovered is not None
        recovered.assert_pure_symbolic()
        self.assertEqual(recovered.expert_evidence, expert_evidence)
        self.assertEqual(
            [message.content for message in reopened.load_messages(conversation.id)],
            [
                "Inspect this Prolog and follow the language chain.",
                answer,
            ],
        )

        recovered_root_ref = recovered.expert_evidence[0]["evidence_refs"][0]
        _answer_after_restart, why_after_restart = self._run_symbolic_dialogue(
            recovered_root_ref
        )
        self.assertEqual(
            why_after_restart,
            f"I answered from evidence {recovered_root_ref}.",
        )
        reopened.save_message(
            self._message(
                conversation.id,
                3,
                "turn:why",
                MessageRole.USER,
                "why did you do that?",
            )
        )
        reopened.save_message(
            self._message(
                conversation.id,
                4,
                "turn:why",
                MessageRole.ASSISTANT,
                why_after_restart,
            )
        )
        second_projection = reopened.save_symbolic_projection(
            SymbolicConversationProjection(
                conversation_id=conversation.id,
                projection_generation=2,
                runtime_generation=2,
                turn_id="turn:why",
                outcome="success",
                project_id=_WORKSPACE,
                project_generation=1,
                dialogue_act="explain",
                dialogue_state={
                    "follow_up": "why",
                    "evidence_ref": recovered_root_ref,
                },
                expert_evidence=recovered.expert_evidence,
                renderer_provenance=_SYMBOLIC_RENDERER,
                providers_enabled=False,
                max_model_calls=0,
                provider_calls=0,
                model_calls=0,
            ),
            expected_generation=first_projection.projection_generation,
        )
        second_projection.assert_pure_symbolic()
        reopened_database.close()

        final_database = DatabaseManager(database_path)
        final_store = ConversationStore(final_database)
        final_projection = final_store.load_symbolic_projection(conversation.id)
        self.assertIsNotNone(final_projection)
        assert final_projection is not None
        final_projection.assert_pure_symbolic()
        self.assertEqual(final_projection.dialogue_act, "explain")
        self.assertEqual(final_projection.expert_evidence, expert_evidence)
        self.assertEqual(final_projection.provider_calls, 0)
        self.assertEqual(final_projection.model_calls, 0)
        self.assertEqual(
            [message.content for message in final_store.load_messages(conversation.id)],
            [
                "Inspect this Prolog and follow the language chain.",
                answer,
                "why did you do that?",
                why_after_restart,
            ],
        )
        final_database.close()


if __name__ == "__main__":
    unittest.main()
