import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from zara_memory.symbolic_memory_mcp import SymbolicMemoryMCP, SymbolicMemoryMCPError


class SymbolicMemoryMCPTests(unittest.TestCase):
    def test_remember_uses_fixed_argv_and_host_bound_authority(self):
        calls = []

        def run(argv, **kwargs):
            calls.append((argv, kwargs))
            request = json.loads(kwargs["input"])
            self.assertEqual(request["method"], "tools/call")
            self.assertEqual(request["params"]["name"], "memory_remember")
            self.assertNotIn("principal", request["params"]["arguments"])
            self.assertNotIn("capabilities", request["params"]["arguments"])
            response = {
                "jsonrpc": "2.0",
                "id": request["id"],
                "result": {
                    "content": [{"type": "text", "text": "Stored memory mem_1"}],
                    "structuredContent": {
                        "status": "stored",
                        "id": "mem_1",
                        "source_id": "src_1",
                        "namespace": {"scope": "project", "project": "repo-1"},
                        "durable": True,
                        "version": 1,
                        "projection_status": "not_attempted",
                    },
                    "isError": False,
                },
            }
            return subprocess.CompletedProcess(argv, 0, stdout=json.dumps(response) + "\n", stderr="")

        client = SymbolicMemoryMCP(
            executable="/nix/store/example/bin/symbolic-memory-mcp",
            database=Path("/var/lib/zara/memory.db"),
            principal="zara-local",
            session_id="session-1",
            project_remote="https://git.example/repo.git",
            capabilities=("memory_read", "memory_write_project"),
            runner=run,
        )
        result = client.remember("Use Prolog as authority.", scope="project", kind="text")
        self.assertEqual(result["id"], "mem_1")
        argv, kwargs = calls[0]
        self.assertEqual(argv, ["/nix/store/example/bin/symbolic-memory-mcp"])
        self.assertFalse(kwargs["shell"])
        self.assertTrue(kwargs["check"])
        self.assertGreater(kwargs["timeout"], 0)
        env = kwargs["env"]
        self.assertEqual(env["SYMBOLIC_MEMORY_DB"], "/var/lib/zara/memory.db")
        self.assertEqual(env["SYMBOLIC_MEMORY_PRINCIPAL"], "zara-local")
        self.assertEqual(env["SYMBOLIC_MEMORY_CAPABILITIES"], "memory_read,memory_write_project")

    def test_get_returns_backend_evidence_without_inventing_projection(self):
        def run(argv, **kwargs):
            request = json.loads(kwargs["input"])
            response = {
                "jsonrpc": "2.0",
                "id": request["id"],
                "result": {
                    "content": [{"type": "text", "text": "hello"}],
                    "structuredContent": {
                        "id": "mem_1",
                        "source_id": "src_1",
                        "source_text": "hello",
                        "namespace": {"scope": "session", "session_id": "s1"},
                        "lifetime": "short_term",
                        "kind": "text",
                        "provenance": {"source_class": "model_inferred"},
                        "principal": "zara-local",
                        "trust": "model_inferred",
                        "created_at": "2026-09-05T00:00:00Z",
                        "source_created_at": "2026-09-05T00:00:00Z",
                        "version": 1,
                        "lifecycle": "active",
                    },
                    "isError": False,
                },
            }
            return subprocess.CompletedProcess(argv, 0, stdout=json.dumps(response) + "\n", stderr="")

        client = SymbolicMemoryMCP(
            executable="symbolic-memory-mcp",
            database=Path("/tmp/memory.db"),
            principal="zara-local",
            session_id="s1",
            capabilities=("memory_read",),
            runner=run,
        )
        result = client.get("mem_1")
        self.assertEqual(result["source_text"], "hello")
        self.assertEqual(result["lifecycle"], "active")
        self.assertNotIn("facts", result)

    def test_rejects_backend_tool_errors(self):
        def run(argv, **kwargs):
            request = json.loads(kwargs["input"])
            response = {
                "jsonrpc": "2.0",
                "id": request["id"],
                "result": {"content": [{"type": "text", "text": "denied"}], "isError": True},
            }
            return subprocess.CompletedProcess(argv, 0, stdout=json.dumps(response) + "\n", stderr="")

        client = SymbolicMemoryMCP(
            executable="symbolic-memory-mcp",
            database=Path("/tmp/memory.db"),
            principal="zara-local",
            session_id="s1",
            capabilities=("memory_read",),
            runner=run,
        )
        with self.assertRaisesRegex(SymbolicMemoryMCPError, "denied"):
            client.get("mem_private")

    def test_rejects_scopes_current_backend_does_not_support(self):
        client = SymbolicMemoryMCP(
            executable="symbolic-memory-mcp",
            database=Path("/tmp/memory.db"),
            principal="zara-local",
            session_id="s1",
            capabilities=("memory_read",),
            runner=lambda *args, **kwargs: self.fail("runner must not be called"),
        )
        with self.assertRaisesRegex(SymbolicMemoryMCPError, "unsupported.*user"):
            client.remember("x", scope="user")


if __name__ == "__main__":
    unittest.main()
