"""Zara discovery entry for the files service plugin."""

PLUGIN_VERSION = "0.1.0"


def create_plugin():
    from zara_files.plugin import create_plugin as create_service

    return create_service()
