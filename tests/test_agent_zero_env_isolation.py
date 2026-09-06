from __future__ import annotations

import os
import unittest

from scripts.zara_compat import fake_dependency_environment


class AgentZeroEnvironmentIsolationTest(unittest.TestCase):
    def test_fake_dependency_environment_strips_and_restores_agent_zero_live_configuration(self) -> None:
        variables = {
            "ZARA_AGENT_ZERO_URL": "http://127.0.0.1:5000",
            "ZARA_AGENT_ZERO_API_KEY": "private-token",
        }
        previous = {name: os.environ.get(name) for name in variables}
        try:
            os.environ.update(variables)
            with fake_dependency_environment("zara-agent-zero"):
                for name in variables:
                    self.assertNotIn(name, os.environ)
            for name, value in variables.items():
                self.assertEqual(os.environ.get(name), value)
        finally:
            for name, value in previous.items():
                if value is None:
                    os.environ.pop(name, None)
                else:
                    os.environ[name] = value


if __name__ == "__main__":
    unittest.main()
