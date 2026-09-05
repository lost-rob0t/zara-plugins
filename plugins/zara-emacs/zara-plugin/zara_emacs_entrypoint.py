"""Zara discovery entry for the Emacs service plugin."""

PLUGIN_VERSION = "0.1.0"


def create_plugin():
    from zara_emacs.plugin import create_plugin as create_service

    return create_service()
