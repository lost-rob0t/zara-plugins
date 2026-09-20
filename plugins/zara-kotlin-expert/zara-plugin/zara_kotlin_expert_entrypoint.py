"""Zara discovery entry for the KotlinExpert adapter."""

PLUGIN_VERSION = "0.1.0"


def create_plugin():
    from zara_kotlin_expert.plugin import create_plugin as create_service

    return create_service()
