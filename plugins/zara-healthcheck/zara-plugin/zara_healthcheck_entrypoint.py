"""Zara discovery entry for the passive healthcheck service."""

PLUGIN_VERSION = "0.1.0"


def create_plugin():
    from zara_healthcheck.plugin import create_plugin as create_service

    return create_service()
