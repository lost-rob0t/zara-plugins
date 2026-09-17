"""Zara service discovery entry for the Prolog response policy."""
PLUGIN_VERSION = '0.1.0'


def create_plugin():
    from zara_policy.plugin import create_plugin as create_service
    return create_service()
