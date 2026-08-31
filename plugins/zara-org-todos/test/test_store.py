import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from zara_org_todos_service.store import OrgTodoStore


class OrgTodoStoreTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.store = OrgTodoStore(self.root)

    def test_capture_lists_and_preserves_stable_id(self):
        task = self.store.add("Buy milk", task_id="task-1")
        self.assertEqual(task.task_id, "task-1")
        self.assertEqual(task.state, "TODO")
        self.assertEqual([item.title for item in self.store.list()], ["Buy milk"])
        text = (self.root / "inbox.org").read_text(encoding="utf-8")
        self.assertIn(":ID:       task-1", text)

    def test_complete_reopen_edit_and_schedule_by_id(self):
        self.store.add("Old title", task_id="task-2")
        self.assertEqual(self.store.edit("task-2", "New title").title, "New title")
        done = self.store.complete("task-2")
        self.assertEqual(done.state, "DONE")
        self.assertEqual(self.store.list(), [])
        reopened = self.store.reopen("task-2")
        self.assertEqual(reopened.state, "TODO")
        scheduled = self.store.schedule("task-2", "2026-09-01 10:30")
        self.assertEqual(scheduled.scheduled, "<2026-09-01 Tue 10:30>")

    def test_search_is_recursive_and_keeps_tags_out_of_title(self):
        nested = self.root / "project" / "zara.org"
        nested.parent.mkdir(parents=True)
        nested.write_text(
            "* Zara\n\n** TODO Ship plugin :zara:important:\n:PROPERTIES:\n:ID:       zara-1\n:END:\n",
            encoding="utf-8",
        )
        matches = self.store.search("ship")
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0].title, "Ship plugin")
        self.assertEqual(matches[0].path, nested)

    def test_mutation_preserves_live_symlink(self):
        durable = self.root / "durable-inbox.org"
        durable.write_text(
            "* Inbox\n\n** TODO Linked\n:PROPERTIES:\n:ID:       linked\n:END:\n",
            encoding="utf-8",
        )
        live = self.root / "inbox.org"
        live.symlink_to(durable)
        self.store.complete("linked")
        self.assertTrue(live.is_symlink())
        self.assertIn("** DONE Linked", durable.read_text(encoding="utf-8"))

    def test_duplicate_title_tasks_are_addressed_by_id(self):
        self.store.add("Same title", task_id="first")
        self.store.add("Same title", task_id="second")
        self.store.complete("second")
        states = {task.task_id: task.state for task in self.store.list(("TODO", "DONE"))}
        self.assertEqual(states, {"first": "TODO", "second": "DONE"})
