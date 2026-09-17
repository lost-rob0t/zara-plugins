"""Zara service discovery entry for first-class operator Prolog."""
PLUGIN_VERSION = '0.1.0'


def create_plugin():
    from zara_prolog.plugin import create_plugin as create_service
    return create_service()
