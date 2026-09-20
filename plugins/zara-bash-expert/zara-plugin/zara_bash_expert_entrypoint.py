"""Zara discovery entry for the BashExpert adapter."""

PLUGIN_VERSION = "0.1.0"


def create_plugin():
    from zara_bash_expert.plugin import create_plugin as create_service

    return create_service()
