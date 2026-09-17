"""Zara discovery entry for the Pi coding-agent bridge plugin."""

PLUGIN_VERSION = "0.1.0"


def create_plugin():
    from zara_pi.plugin import create_plugin as create_service

    return create_service()
