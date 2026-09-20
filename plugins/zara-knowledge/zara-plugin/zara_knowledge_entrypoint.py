"""Zara discovery entry for the knowledge service plugin."""

PLUGIN_VERSION = "0.2.0"


def create_plugin():
    from zara_knowledge.plugin import create_plugin as create_service

    return create_service()
