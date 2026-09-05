"""Zara discovery entry for the communications service plugin."""

PLUGIN_VERSION = "0.1.0"


def create_plugin():
    from zara_comms.plugin import create_plugin as create_service

    return create_service()
