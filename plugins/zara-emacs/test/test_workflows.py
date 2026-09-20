import base64
import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from zara_emacs.client import EmacsError
from zara_emacs.config import EmacsConfig
from zara_emacs.workflow import (
    EmacsWorkflowConfigError,
    WorkflowEmacsClient,
    load_workflows,
)


class Result:
    def __init__(self, returncode=0, stdout="ok\n", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


class Runner:
    def __init__(self, results):
        self.results = list(results)
        self.calls = []

    def __call__(self, argv, **kwargs):
        self.calls.append((list(argv), kwargs))
        return self.results.pop(0)


def bridge_result(operation, result=None):
    payload = {
        "bridge": "ZARA-EMACS/1",
        "session_id": "test-session",
        "operation": operation,
        "ok": True,
        "result": result or {},
    }
    return Result(stdout=json.dumps(json.dumps(payload)) + "\n")


def bridge_payload(runner, index):
    expression = runner.calls[index][0][-1]
    prefix = "(progn (require 'zara) (zara-bridge-call \""
    suffix = "\"))"
    encoded = expression[len(prefix):-len(suffix)]
    return json.loads(base64.b64decode(encoded).decode("utf-8"))


class EmacsWorkflowTest(unittest.TestCase):
    def config(self):
        return EmacsConfig(projects={"zara": "/work/zara"})

    def client(self, workflow_mapping, results):
        config = self.config()
        workflows = load_workflows(workflow_mapping, projects=config.projects)
        runner = Runner(results)
        return WorkflowEmacsClient(config, workflows=workflows, runner=runner), runner

    def test_dashboard_and_zara_chat_use_native_bridge(self):
        client, runner = self.client(
            {},
            [
                bridge_result("ui.ai_dashboard", {"opened": True}),
                bridge_result("ui.zara_chat", {"opened": True}),
            ],
        )
        self.assertTrue(client.open_dashboard()["acknowledged"])
        self.assertTrue(client.open_zara_chat()["acknowledged"])
        self.assertEqual(bridge_payload(runner, 0)["operation"], "ui.ai_dashboard")
        self.assertEqual(bridge_payload(runner, 1)["operation"], "ui.zara_chat")
        self.assertNotIn("(ai/dashboard)", runner.calls[0][0][-1])
        self.assertNotIn("(zara-chat)", runner.calls[1][0][-1])

    def test_named_workflow_runs_only_configured_steps(self):
        mapping = {
            "workflows": {
                "coding": [
                    {"operation": "open_dashboard"},
                    {"operation": "open_magit", "argument": "zara"},
                    {"operation": "open_zara_chat"},
                ]
            }
        }
        client, runner = self.client(
            mapping,
            [
                bridge_result("ui.ai_dashboard", {"opened": True}),
                bridge_result("magit.open_project", {"path": "/work/zara", "opened": True}),
                bridge_result("ui.zara_chat", {"opened": True}),
            ],
        )
        result = client.run_workflow("coding")
        self.assertEqual(result["workflow_id"], "coding")
        self.assertEqual(
            [step["operation"] for step in result["steps"]],
            ["open_dashboard", "open_magit", "open_zara_chat"],
        )
        self.assertEqual(len(runner.calls), 3)

    def test_unsafe_workflow_is_rejected_before_process_execution(self):
        with self.assertRaisesRegex(EmacsWorkflowConfigError, "unsupported workflow"):
            load_workflows(
                {
                    "workflows": {
                        "unsafe": [
                            {"operation": "eval", "argument": "(shell-command \"id\")"}
                        ]
                    }
                },
                projects=self.config().projects,
            )

        client, runner = self.client({}, [])
        with self.assertRaisesRegex(EmacsError, "unknown workflow"):
            client.run_workflow("missing")
        self.assertEqual(runner.calls, [])

    def test_workflow_validation_fails_closed_on_paths_dates_projects_and_args(self):
        invalid_steps = (
            ({"operation": "open_file", "argument": "relative.org"}, "absolute paths"),
            ({"operation": "open_daily", "argument": "tomorrow-ish"}, "ISO YYYY-MM-DD"),
            ({"operation": "open_magit", "argument": "unknown"}, "unknown project alias"),
            ({"operation": "open_dashboard", "argument": "surprise"}, "do not accept arguments"),
        )
        for step, expected in invalid_steps:
            with self.subTest(step=step):
                with self.assertRaisesRegex(EmacsWorkflowConfigError, expected):
                    load_workflows(
                        {"workflows": {"bad": [step]}},
                        projects=self.config().projects,
                    )

    def test_workflow_reports_exact_failing_step_and_stops(self):
        mapping = {
            "workflows": {
                "coding": [
                    {"operation": "open_dashboard"},
                    {"operation": "open_magit", "argument": "zara"},
                    {"operation": "open_zara_chat"},
                ]
            }
        }
        client, runner = self.client(
            mapping,
            [
                bridge_result("ui.ai_dashboard", {"opened": True}),
                Result(returncode=1, stderr="magit unavailable"),
            ],
        )
        with self.assertRaisesRegex(
            EmacsError,
            r"workflow 'coding' failed at step 2 \(open_magit\): magit unavailable",
        ):
            client.run_workflow("coding")
        self.assertEqual(len(runner.calls), 2)


if __name__ == "__main__":
    unittest.main()
