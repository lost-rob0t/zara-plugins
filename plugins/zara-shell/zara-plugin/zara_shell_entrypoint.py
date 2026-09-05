"""Zara discovery entry for the constrained shell service plugin."""

PLUGIN_VERSION = "0.1.0"


def create_plugin():
    from zara_shell.plugin import create_plugin as create_service

    return create_service()
