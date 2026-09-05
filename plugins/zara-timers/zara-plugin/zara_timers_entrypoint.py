"""Zara discovery entry for the persistent timer service."""

PLUGIN_VERSION = "0.1.0"


def create_plugin():
    from zara_timers.plugin import create_plugin as create_service

    return create_service()
