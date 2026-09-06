import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from zara_memory.symbolic_memory_mcp import SymbolicMemoryMCP, SymbolicMemoryMCPError


class SymbolicMemoryMCPResponseIdTypeTests(unittest.TestCase):
    def test_rejects_boolean_jsonrpc_response_identity(self):
        def run(argv, **kwargs):
            request = json.loads(kwargs["input"])
            self.assertEqual(request["id"], 1)
            response = {
                "jsonrpc": "2.0",
                "id": True,
                "result": {
                    "structuredContent": {"id": "mem-1", "source_text": "ambiguous"},
                    "isError": False,
                },
            }
            return subprocess.CompletedProcess(
                argv,
                0,
                stdout=json.dumps(response) + "\n",
                stderr="",
            )

        client = SymbolicMemoryMCP(
            executable="symbolic-memory-mcp",
            database=Path("/tmp/memory.db"),
            principal="zara-local",
            session_id="s1",
            capabilities=("memory_read",),
            runner=run,
        )

        with self.assertRaisesRegex(SymbolicMemoryMCPError, "response identity"):
            client.get("mem-1")


if __name__ == "__main__":
    unittest.main()
