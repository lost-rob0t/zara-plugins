import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from zara_memory.symbolic_memory_mcp import SymbolicMemoryMCP, SymbolicMemoryMCPError


class SymbolicMemoryMCPLaunchFailureTests(unittest.TestCase):
    def test_normalizes_os_launch_failures(self):
        def run(*args, **kwargs):
            raise PermissionError("configured executable is not executable")

        client = SymbolicMemoryMCP(
            executable="/tmp/symbolic-memory-mcp",
            database=Path("/tmp/memory.db"),
            principal="zara-local",
            session_id="s1",
            capabilities=("memory_read",),
            runner=run,
        )

        with self.assertRaisesRegex(SymbolicMemoryMCPError, "invocation failed"):
            client.get("mem-1")


if __name__ == "__main__":
    unittest.main()
