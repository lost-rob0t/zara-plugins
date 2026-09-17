from __future__ import annotations
import importlib
import json
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'lib'))

class Metadata:
    def __init__(self, **fields): self.__dict__.update(fields)
class Tool:
    @staticmethod
    def from_function(**fields): return types.SimpleNamespace(**fields)

def load_plugin():
    zara = types.ModuleType('zara')
    zara.__path__ = []
    api = types.ModuleType('zara.plugins')
    api.PluginMetadata, api.ServicePlugin = Metadata, object
    langchain = types.ModuleType('langchain_core')
    langchain.__path__ = []
    tools = types.ModuleType('langchain_core.tools')
    tools.StructuredTool = Tool
    with patch.dict(sys.modules, {'zara':zara, 'zara.plugins':api,
                                'langchain_core':langchain,'langchain_core.tools':tools}):
        return importlib.import_module('zara_policy.plugin')

class Backend:
    ready = False
    mode = 'advise'
    last_rule_ids = ()
    match_count = 0
    def start(self): self.ready = True
    def stop(self): self.ready = False
    def inspect(self, text): return ()

class Runtime:
    def __init__(self, enabled=True):
        self.configuration = {}
        self.enabled = enabled
        self.calls=[]
    def register_agent_loop_advice(self,*args):
        if not self.enabled:
            raise PermissionError('hooks disabled')
        self.calls.append(args)
        return 7

class PluginTests(unittest.TestCase):
    def setUp(self): self.module=load_plugin()
    def test_registers_once_with_correct_hook(self):
        plugin=self.module.ZaraPolicyPlugin(backend=Backend())
        runtime=Runtime()
        plugin.start(runtime); plugin.start(runtime)
        self.assertEqual(len(runtime.calls),1)
        self.assertEqual(runtime.calls[0][:2],('around',40))
        self.assertEqual(json.loads(plugin.status())['advice'],'active')
    def test_disabled_hooks_are_reported_without_enabling_them(self):
        plugin=self.module.ZaraPolicyPlugin(backend=Backend()); runtime=Runtime(False)
        plugin.start(runtime)
        self.assertEqual(runtime.calls,[])
        self.assertEqual(json.loads(plugin.status())['advice'],'hooks-disabled')
        self.assertFalse(runtime.enabled)
        self.assertEqual(runtime.configuration,{})
    def test_stopped_hook_does_not_wrap_model(self):
        import asyncio
        plugin=self.module.ZaraPolicyPlugin(backend=Backend()); plugin.start(Runtime())
        plugin.stop(); model=object()
        async def continuation(client, registry, state, **kwargs): return client
        self.assertIs(asyncio.run(plugin.advise(continuation,model,None,{})),model)
    def test_inspect_is_available_without_repair(self):
        plugin=self.module.ZaraPolicyPlugin(backend=Backend()); plugin.start(Runtime(False))
        self.assertEqual(json.loads(plugin.inspect('plain'))['findings'],[])
    def test_tools_have_no_arbitrary_eval(self):
        plugin=self.module.ZaraPolicyPlugin(backend=Backend())
        self.assertEqual({t.name for t in plugin.tools()}, {'policy.status','policy.inspect'})
    def test_backend_failure_is_explicit(self):
        backend=Backend()
        backend.start=lambda: (_ for _ in ()).throw(RuntimeError('secret'))
        plugin=self.module.ZaraPolicyPlugin(backend=backend); plugin.start(Runtime())
        status=plugin.status()
        self.assertIn('unavailable',status)
        self.assertNotIn('secret',status)
