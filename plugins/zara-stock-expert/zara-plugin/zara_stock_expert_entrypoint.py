"""Zara API v1 discovery entry for the stock risk and knowledge expert."""

PLUGIN_VERSION = '0.1.0'


def create_plugin():
    from langchain_core.tools import StructuredTool
    from zara.plugins import PluginMetadata, ServicePlugin
    from zara_stock_expert.service import StockService

    class ZaraStockExpertPlugin(StockService, ServicePlugin):
        metadata = PluginMetadata(
            name='zara-stock-expert', version=PLUGIN_VERSION, api_version='1',
            description='Persistent market KB, exact money arithmetic and explainable paper risk proposals',
        )

        def tools(self):
            definitions = (
                (self.status, 'stock.status', 'Report stock expert configuration and execution boundaries.', False),
                (self.report_quote, 'stock.report_quote', 'Persist a source-labelled but unverified quote report; never elevates model claims to provider evidence.', True),
                (self.remember_note, 'stock.remember_note', 'Persist a model note or hypothesis in the configured namespace, separate from market facts.', True),
                (self.history, 'stock.history', 'Retrieve bounded point-in-time market KB evidence, including optional immutable revisions.', False),
                (self.money, 'stock.money', 'Exact decimal-string add, fee-aware P&L, tick-rounded break-even and long-only position sizing. No floats or execution.', False),
                (self.evaluate, 'stock.evaluate', 'Explain paper-trade risk preflight against provider evidence; no strategy profitability claim and no broker order.', False),
            )
            return tuple(StructuredTool.from_function(func=function, name=name, description=description,
                         metadata={'zara_requires_approval': True} if writes else {})
                         for function, name, description, writes in definitions)

    return ZaraStockExpertPlugin()
