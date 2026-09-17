import asyncio
from pathlib import Path
import sys
import unittest
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'lib'))
try:
    from langchain_core.messages import AIMessage, HumanMessage
    from langchain_core.tools import BaseTool
    from zara.plugins import ServicePlugin
    from zara.agent.hooks import AgentLoopAdviceRegistry
    from zara_policy.plugin import PolicyPlugin
except ImportError:
    PolicyPlugin = None


@unittest.skipUnless(PolicyPlugin, 'real Zara and LangChain are not installed')
class RealZaraCompatibilityTest(unittest.TestCase):
    def test_plugin_tools_and_transient_loop_advice(self):
        plugin = PolicyPlugin()
        self.assertIsInstance(plugin, ServicePlugin)
        registry = AgentLoopAdviceRegistry(enabled=True, allow_override=False)
        class Runtime:
            def register_agent_loop_advice(self, kind, priority, callback):
                return registry.register(kind, 'plugin:zara-policy', priority, callback)
        plugin.start(Runtime())
        tools = plugin.tools()
        self.assertTrue(all(isinstance(tool, BaseTool) for tool in tools))
        self.assertEqual({tool.name for tool in tools}, {'policy_advice','policy_rules'})
        plugin.client.advise = lambda _: {'status':'ok','findings':[{'advice':'Verify the tests.'}]}
        state = {'messages':[AIMessage(content='All tests pass.'), HumanMessage(content='Continue')]}
        async def loop(_llm, _tools, received, **kwargs):
            self.assertIn('Verify the tests.', received['messages'][0].content)
            return received
        result = asyncio.run(registry.invoke(loop, None, None, state))
        self.assertEqual(len(result['messages']), 2)
        plugin.stop()
        self.assertEqual(tools[0].invoke({'text':'x'})['reason'], 'plugin_stopped')
