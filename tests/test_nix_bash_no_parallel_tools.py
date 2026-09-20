from __future__ import annotations

import sys
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "plugins" / "zara-nix-expert" / "lib"))
sys.path.insert(0, str(REPO_ROOT / "plugins" / "zara-bash-expert" / "lib"))

from zara_bash_expert.plugin import ZaraBashExpertPlugin
from zara_nix_expert.plugin import ZaraNixExpertPlugin


class NixBashNoParallelToolSurfaceTests(unittest.TestCase):
    def test_raw_adapter_classes_expose_no_parallel_expert_tools(self) -> None:
        # The package-root factories already use typed boundary wrappers, but the
        # lower-level modules are importable Python. They must not accidentally
        # publish a second descriptor/invoke namespace that bypasses Core-owned
        # activation, cancellation, generation and shared-budget fencing.
        self.assertEqual(ZaraNixExpertPlugin().tools(), ())
        self.assertEqual(ZaraBashExpertPlugin().tools(), ())


if __name__ == "__main__":
    unittest.main()
