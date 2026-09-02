import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from zara_agent_zero_service.config import AgentZeroConfig, AgentZeroConfigError


class AgentZeroConfigTest(unittest.TestCase):
    def test_empty_url_is_allowed_until_tool_use(self):
        config = AgentZeroConfig.load({})
        self.assertEqual(config.base_url, "")
        self.assertEqual(config.api_key, "")
        self.assertTrue(config.enabled)

    def test_loopback_url_is_allowed_by_default(self):
        config = AgentZeroConfig.load({"base_url": "http://127.0.0.1:5000/"})
        self.assertEqual(config.base_url, "http://127.0.0.1:5000")

    def test_remote_url_requires_explicit_opt_in(self):
        with self.assertRaisesRegex(AgentZeroConfigError, "allow_remote=true"):
            AgentZeroConfig.load({"base_url": "https://agent-zero.example"})

    def test_environment_supplies_runtime_url_and_api_key(self):
        with patch.dict(
            os.environ,
            {
                "ZARA_AGENT_ZERO_URL": "http://localhost:5000",
                "ZARA_AGENT_ZERO_API_KEY": "private-token",
            },
            clear=False,
        ):
            config = AgentZeroConfig.load({"base_url": "http://127.0.0.1:1"})
        self.assertEqual(config.base_url, "http://localhost:5000")
        self.assertEqual(config.api_key, "private-token")


if __name__ == "__main__":
    unittest.main()
