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
    zara=types.ModuleType('zara'); zara.__path__=[]
    api=types.ModuleType('zara.plugins'); api.PluginMetadata=Metadata; api.ServicePlugin=object
    langchain=types.ModuleType('langchain_core'); langchain.__path__=[]
    tools=types.ModuleType('langchain_core.tools'); tools.StructuredTool=Tool
    with patch.dict(sys.modules, {'zara':zara,'zara.plugins':api,
                                'langchain_core':langchain,'langchain_core.tools':tools}):
        return importlib.import_module('zara_prolog.plugin')

class Session:
    ready=False
    def start(self): self.ready=True
    def stop(self): self.ready=False
    def query(self,goal,max_solutions=16): return {'status':'success','solutions':[], 'goal':goal}
    def reload(self): return {'status':'reloaded'}

class PluginTests(unittest.TestCase):
    def setUp(self): self.module=load_plugin()
    def test_executable_tools_require_approval(self):
        tools={tool.name:tool for tool in self.module.ZaraPrologPlugin(session=Session()).tools()}
        self.assertTrue(tools['prolog.query'].metadata['zara_requires_approval'])
        self.assertTrue(tools['prolog.reload'].metadata['zara_requires_approval'])
        self.assertEqual(set(tools), {'prolog.status','prolog.query','prolog.reload','prolog.catalog'})
    def test_start_stop(self):
        plugin=self.module.ZaraPrologPlugin(session=Session()); plugin.start(None)
        self.assertEqual(json.loads(plugin.status())['status'],'ready')
        plugin.stop(); self.assertEqual(json.loads(plugin.status())['status'],'unavailable')
    def test_no_claim_of_sandbox(self):
        plugin=self.module.ZaraPrologPlugin(session=Session())
        self.assertFalse(json.loads(plugin.status())['sandboxed'])
    def test_query_delegates_to_canonical_session(self):
        plugin=self.module.ZaraPrologPlugin(session=Session())
        self.assertEqual(json.loads(plugin.query('example(square,X)'))['goal'],'example(square,X)')
