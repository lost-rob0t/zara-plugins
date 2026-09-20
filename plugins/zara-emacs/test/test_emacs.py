import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from zara_emacs.client import EmacsClient, EmacsError
from zara_emacs.config import EmacsConfig


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


class EmacsClientTest(unittest.TestCase):
    def client(self, results, **config):
        runner = Runner(results)
        client = EmacsClient(EmacsConfig(projects={"zara": "/work/zara"}, **config), runner=runner)
        return client, runner

    def test_command_catalog_is_configuration_owned(self):
        client, runner = self.client(
            [],
            commands={
                "window.split-right": "split-window-right",
                "window.other": "other-window",
            },
        )
        result = client.command_catalog()
        self.assertEqual(result["count"], 2)
        self.assertEqual(result["commands"][0]["action_id"], "window.other")
        self.assertEqual(runner.calls, [])

    def test_voice_phrase_resolves_to_same_action_protocol_without_execution(self):
        client, runner = self.client(
            [],
            commands={"window.split-right": "split-window-right"},
            voice_commands={"Split   window RIGHT": "window.split-right"},
        )
        result = client.resolve_voice(" split window right ")
        self.assertEqual(result["action_id"], "window.split-right")
        self.assertTrue(result["matched"])
        self.assertEqual(runner.calls, [])

    def test_voice_phrase_rejects_unknown_utterance(self):
        client, runner = self.client(
            [],
            commands={"window.split-right": "split-window-right"},
            voice_commands={"split window right": "window.split-right"},
        )
        with self.assertRaisesRegex(EmacsError, "did not match"):
            client.resolve_voice("delete everything")
        self.assertEqual(runner.calls, [])

    def test_invoke_command_resolves_alias_before_fixed_elisp_template(self):
        client, runner = self.client(
            [Result(stdout='"split-window-right"\n')],
            commands={"window.split-right": "split-window-right"},
        )
        result = client.invoke_command("window.split-right")
        self.assertTrue(result["acknowledged"])
        expression = runner.calls[0][0][-1]
        self.assertIn('(intern "split-window-right")', expression)
        self.assertIn("call-interactively command", expression)
        self.assertNotIn("window.split-right", expression)

    def test_invoke_command_rejects_unknown_alias_without_touching_emacs(self):
        client, runner = self.client(
            [],
            commands={"window.split-right": "split-window-right"},
        )
        with self.assertRaisesRegex(EmacsError, "unknown Emacs action"):
            client.invoke_command('evil\") (shell-command \"touch /tmp/pwned\")')
        self.assertEqual(runner.calls, [])

    def test_open_file_uses_argv_not_shell_and_returns_ack(self):
        client, runner = self.client([Result(stdout="")])
        result = client.open_file("/tmp/note.org")
        argv, kwargs = runner.calls[0]
        self.assertEqual(argv[-1], "/tmp/note.org")
        self.assertFalse(kwargs.get("shell", False))
        self.assertTrue(result["acknowledged"])

    def test_daily_emits_dictation_request_but_never_claims_started(self):
        client, runner = self.client([Result(stdout='"/notes/2026-09-05.org"\n')])
        result = client.open_daily("2026-09-05")
        self.assertTrue(result["acknowledged"])
        self.assertEqual(result["post_open"], {"request": "dictation", "started": False})
        expression = runner.calls[0][0][-1]
        self.assertIn("org-roam-dailies--capture", expression)
        self.assertIn('(org-read-date nil t "2026-09-05")', expression)
        self.assertNotIn("org-roam-dailies-goto-date", expression)
        self.assertNotIn("start-process-shell-command", expression)

    def test_shared_memory_queries_org_ql_with_bounded_limit(self):
        payload = json.dumps([{"id": "m1", "subject": "editor", "value": "emacs"}])
        client, runner = self.client([Result(stdout=json.dumps(payload) + "\n")])
        result = client.shared_memory(25)
        self.assertEqual(result["count"], 1)
        self.assertEqual(result["rows"][0]["id"], "m1")
        expression = runner.calls[0][0][-1]
        self.assertIn("org-ql-select", expression)
        self.assertIn('property "MEMORY_SCOPE" "shared"', expression)
        self.assertIn("seq-take rows 25", expression)

    def test_inventory_queries_structured_org_kinds(self):
        payload = json.dumps([{"id": "i1", "kind": "inventory-item"}])
        client, runner = self.client([Result(stdout=json.dumps(payload) + "\n")])
        result = client.inventory(10)
        self.assertEqual(result["count"], 1)
        expression = runner.calls[0][0][-1]
        self.assertIn('property "KIND" "inventory-event"', expression)
        self.assertIn('property "KIND" "food-event"', expression)

    def test_unresolved_inventory_queries_events_without_item_id(self):
        payload = json.dumps(
            [{"id": "e1", "item_key": "eggs-large", "event": "buy"}]
        )
        client, runner = self.client([Result(stdout=json.dumps(payload) + "\n")])
        result = client.unresolved_inventory(20)
        self.assertEqual(result["count"], 1)
        self.assertEqual(result["rows"][0]["item_key"], "eggs-large")
        expression = runner.calls[0][0][-1]
        self.assertIn('property "KIND" "inventory-event"', expression)
        self.assertIn('property "ITEM_ID" ""', expression)
        self.assertIn("seq-take rows 20", expression)

    def test_materialize_inventory_item_creates_stable_org_node(self):
        response = {
            "status": "created",
            "id": "item-1",
            "file": "/notes/inventory/items/item-1.org",
            "name": "Large eggs",
            "item_key": "eggs-large",
        }
        payload = json.dumps(response)
        client, runner = self.client([Result(stdout=json.dumps(payload) + "\n")])
        result = client.materialize_inventory_item(
            "eggs-large",
            "Large eggs",
            "each",
            "daily:2026-09-19",
            category="food",
            barcode="123456",
            default_location="fridge",
            reorder_at=4,
        )
        self.assertTrue(result["acknowledged"])
        self.assertEqual(result["status"], "created")
        expression = runner.calls[0][0][-1]
        self.assertIn("inventory/items/", expression)
        self.assertIn("inventory-item", expression)
        self.assertIn('property "ITEM_KEY"', expression)
        self.assertIn("* Item", expression)
        self.assertIn("gpt-todos-sync", expression)
        self.assertNotIn("shell-command", expression)

    def test_materialize_inventory_item_rejects_bad_reorder_value(self):
        client, runner = self.client([])
        with self.assertRaisesRegex(EmacsError, "non-negative finite"):
            client.materialize_inventory_item(
                "eggs-large",
                "Large eggs",
                "each",
                "test",
                reorder_at=-1,
            )
        self.assertEqual(runner.calls, [])

    def test_record_inventory_event_appends_to_daily_with_fixed_template(self):
        response = {
            "id": "evt1",
            "file": "/notes/daily/2026-09-19.org",
            "day": "2026-09-19",
            "event": "putaway",
            "item_key": "meijer-mini-penne-16oz",
            "qty": "3",
            "unit": "package",
        }
        payload = json.dumps(response)
        client, runner = self.client([Result(stdout=json.dumps(payload) + "\n")])
        result = client.record_inventory_event(
            "putaway",
            "meijer-mini-penne-16oz",
            3,
            "package",
            "manual",
            to_location="pantry/pasta",
            day="2026-09-19",
        )
        self.assertTrue(result["acknowledged"])
        self.assertEqual(result["event"], "putaway")
        expression = runner.calls[0][0][-1]
        self.assertIn("inventory-event", expression)
        self.assertIn("daily/", expression)
        self.assertIn("save-buffer", expression)
        self.assertIn("ADJUSTMENT", expression)
        self.assertIn(json.dumps("pantry/pasta"), expression)
        self.assertNotIn("shell-command", expression)

    def test_record_inventory_event_rejects_bad_event_and_qty(self):
        client, runner = self.client([])
        with self.assertRaisesRegex(EmacsError, "unsupported inventory event"):
            client.record_inventory_event("teleport", "item", 1, "each", "test")
        with self.assertRaisesRegex(EmacsError, "positive finite"):
            client.record_inventory_event("buy", "item", 0, "each", "test")
        with self.assertRaisesRegex(EmacsError, "1 to 16"):
            client.record_inventory_event("adjust", "item", 1, "each", "test")
        with self.assertRaisesRegex(EmacsError, "add or remove"):
            client.record_inventory_event(
                "adjust", "item", 1, "each", "test", adjustment="sideways"
            )
        with self.assertRaisesRegex(EmacsError, "only valid"):
            client.record_inventory_event(
                "buy", "item", 1, "each", "test", adjustment="add"
            )
        self.assertEqual(runner.calls, [])

    def test_record_inventory_adjustment_writes_explicit_direction(self):
        response = {
            "id": "evt-adjust",
            "file": "/notes/daily/2026-09-19.org",
            "day": "2026-09-19",
            "event": "adjust",
            "item_key": "eggs-large",
            "qty": "2",
            "unit": "each",
        }
        payload = json.dumps(response)
        client, runner = self.client([Result(stdout=json.dumps(payload) + "\n")])
        result = client.record_inventory_event(
            "adjust",
            "eggs-large",
            2,
            "each",
            "manual-count",
            day="2026-09-19",
            adjustment="remove",
        )
        self.assertTrue(result["acknowledged"])
        expression = runner.calls[0][0][-1]
        self.assertIn(json.dumps("remove"), expression)
        self.assertIn(":ADJUSTMENT:", expression)

    def test_append_shared_memory_is_fixed_template_and_syncs(self):
        response = {
            "id": "m2",
            "file": "/notes/memory/shared/m2.org",
            "subject": 'editor "choice"',
            "revision": 2,
            "supersedes": "m1",
        }
        payload = json.dumps(response)
        client, runner = self.client([Result(stdout=json.dumps(payload) + "\n")])
        result = client.append_shared_memory(
            'editor "choice"',
            "emacs",
            "zara",
            "conversation:test",
            "m1",
        )
        self.assertTrue(result["acknowledged"])
        self.assertEqual(result["id"], "m2")
        expression = runner.calls[0][0][-1]
        self.assertIn("org-id-new", expression)
        self.assertIn("memory/shared/", expression)
        self.assertIn("* Assertion", expression)
        self.assertIn("gpt-todos-sync", expression)
        self.assertIn(json.dumps('editor "choice"'), expression)
        self.assertNotIn("shell-command", expression)

    def test_append_shared_memory_rejects_multiline_properties(self):
        client, runner = self.client([])
        with self.assertRaisesRegex(EmacsError, "single line"):
            client.append_shared_memory(
                "editor\nchoice",
                "emacs",
                "zara",
                "conversation:test",
            )
        self.assertEqual(runner.calls, [])

    def test_org_query_limit_is_bounded(self):
        client, runner = self.client([])
        with self.assertRaisesRegex(EmacsError, "between 1 and 500"):
            client.shared_memory(501)
        self.assertEqual(runner.calls, [])

    def test_magit_resolves_only_known_project_alias(self):
        client, runner = self.client([Result(stdout='t\n')])
        result = client.open_magit("zara")
        self.assertEqual(result["project_id"], "zara")
        self.assertIn(json.dumps("/work/zara"), runner.calls[0][0][-1])
        with self.assertRaisesRegex(EmacsError, "unknown project"):
            client.open_magit("$(touch /tmp/pwned)")
        self.assertEqual(len(runner.calls), 1)

    def test_server_failure_is_explicit_and_bounded(self):
        client, _ = self.client([Result(returncode=1, stderr="server unavailable")])
        with self.assertRaisesRegex(EmacsError, "server unavailable"):
            client.open_scratch()


if __name__ == "__main__":
    unittest.main()
