import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from zara_memory.symbolic_memory_mcp import SymbolicMemoryMCP, SymbolicMemoryMCPError


class SymbolicMemoryMCPResultStatusTests(unittest.TestCase):
    def test_rejects_missing_or_non_boolean_tool_result_status(self):
        for status in (None, "false", 0, 1):
            with self.subTest(status=status):
                def run(argv, **kwargs):
                    request = json.loads(kwargs["input"])
                    result = {
                        "structuredContent": {"id": "mem-1", "source_text": "ambiguous"},
                    }
                    if status is not None:
                        result["isError"] = status
                    response = {"jsonrpc": "2.0", "id": request["id"], "result": result}
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

                with self.assertRaisesRegex(SymbolicMemoryMCPError, "result status"):
                    client.get("mem-1")


if __name__ == "__main__":
    unittest.main()
