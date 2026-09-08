import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "test.yml"


class FlakeGateDiagnosticsContractTests(unittest.TestCase):
    def test_flake_check_log_is_preserved_without_weakening_gate(self):
        workflow = WORKFLOW.read_text(encoding="utf-8")

        self.assertIn(
            'nix flake check --print-build-logs 2>&1 | tee flake-check.log',
            workflow,
        )
        self.assertIn('name: Upload flake check diagnostics', workflow)
        self.assertIn('if: always()', workflow)
        self.assertIn('name: flake-check-diagnostics', workflow)
        self.assertIn('path: flake-check.log', workflow)
        self.assertNotIn('continue-on-error: true\n        run: nix flake check', workflow)


if __name__ == "__main__":
    unittest.main()
