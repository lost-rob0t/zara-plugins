"""Zara discovery entry for the GitHub service plugin."""


def create_plugin():
    from zara_github.plugin import create_plugin as create_service

    return create_service()
