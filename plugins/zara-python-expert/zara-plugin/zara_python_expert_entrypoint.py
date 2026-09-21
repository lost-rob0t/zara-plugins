"""Zara discovery entry for the PythonExpert adapter."""

PLUGIN_VERSION = "0.1.0"


def create_plugin():
    from zara_python_expert.plugin import create_plugin as create_service

    return create_service()
