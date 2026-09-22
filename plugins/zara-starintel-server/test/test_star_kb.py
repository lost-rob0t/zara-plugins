import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from zara_starintel_server.config import StarIntelConfig
from zara_starintel_server.star_kb import EXPERT_ID, StarKB, descriptor


class FakeClient:
    def __init__(self, operations):
        self._operations = list(operations)
        self.calls = []

    def operations(self, *, refresh=False):
        self.calls.append(("operations", refresh))
        return list(self._operations)

    def capabilities(self):
        self.calls.append(("capabilities",))
        return {"features": {"documents": True, "targets": True}}

    def call_operation(
        self,
        operation_id,
        *,
        path_parameters=None,
        query=None,
        body=None,
        headers=None,
    ):
        self.calls.append(
            (
                "call_operation",
                operation_id,
                path_parameters,
                query,
                body,
                headers,
            )
        )
        return {
            "status": 200,
            "ok": True,
            "correlation_id": "corr-1",
            "data": {"operation_id": operation_id},
        }


class StarKBTest(unittest.TestCase):
    def setUp(self):
        self.operations = [
            {
                "operation_id": "document.search",
                "method": "GET",
                "path": "/documents/search",
                "summary": "Search documents and evidence",
            },
            {
                "operation_id": "document.update",
                "method": "PATCH",
                "path": "/documents/{id}",
                "summary": "Update a document",
            },
            {
                "operation_id": "target.submit",
                "method": "POST",
                "path": "/targets",
                "summary": "Submit an investigation target",
            },
            {
                "operation_id": "credential.reset",
                "path": "/credentials/{id}/reset",
                "summary": "Reset a credential",
            },
        ]
        self.client = FakeClient(self.operations)
        self.kb = StarKB(
            self.client,
            StarIntelConfig(base_url="https://starintel.example"),
        )

    def test_descriptor_is_service_expert(self):
        item = descriptor(available=True)

        self.assertEqual(item["protocol"], "ZARA-EXPERT/1")
        self.assertEqual(item["expert_id"], EXPERT_ID)
        self.assertEqual(item["reasoning_kind"], "service")
        self.assertEqual(item["availability"], "ready")
        self.assertEqual(item["resource_limits"]["max_model_calls"], 0)
        self.assertIn("star-kb.run", item["required_capabilities"])

    def test_plan_excludes_writes_until_explicitly_admitted(self):
        read_only = self.kb.plan("update document", allow_writes=False)
        admitted = self.kb.plan("update document", allow_writes=True)

        self.assertNotIn(
            "document.update",
            [step["operation_id"] for step in read_only["steps"]],
        )
        self.assertEqual(admitted["steps"][0]["operation_id"], "document.update")
        self.assertTrue(admitted["steps"][0]["write"])

    def test_unknown_method_dotted_write_operation_fails_closed(self):
        read_only = self.kb.plan("reset credential", allow_writes=False)
        admitted = self.kb.plan("reset credential", allow_writes=True)

        self.assertNotIn(
            "credential.reset",
            [step["operation_id"] for step in read_only["steps"]],
        )
        self.assertIn(
            "credential.reset",
            [step["operation_id"] for step in admitted["steps"]],
        )

    def test_run_is_dry_run_by_default(self):
        result = self.kb.run("search documents")

        self.assertTrue(result["dry_run"])
        self.assertEqual(result["executed"], [])
        self.assertFalse(
            any(call[0] == "call_operation" for call in self.client.calls)
        )

    def test_write_execution_requires_idempotency_key(self):
        blocked = self.kb.run(
            "update document",
            allow_writes=True,
            dry_run=False,
        )

        self.assertFalse(blocked["completed"])
        self.assertEqual(
            blocked["executed"][0]["reason"],
            "write-operation-requires-idempotency-key",
        )
        self.assertFalse(
            any(call[0] == "call_operation" for call in self.client.calls)
        )

        result = self.kb.run(
            "update document",
            bindings={
                "document.update": {
                    "path_parameters": {"id": "doc-1"},
                    "body": {"name": "updated"},
                    "headers": {"Idempotency-Key": "run-1"},
                }
            },
            max_steps=1,
            allow_writes=True,
            dry_run=False,
        )

        self.assertTrue(result["completed"])
        call = next(call for call in self.client.calls if call[0] == "call_operation")
        self.assertEqual(call[1], "document.update")
        self.assertEqual(call[2], {"id": "doc-1"})
        self.assertEqual(call[4], {"name": "updated"})
        self.assertEqual(call[5], {"Idempotency-Key": "run-1"})


if __name__ == "__main__":
    unittest.main()
