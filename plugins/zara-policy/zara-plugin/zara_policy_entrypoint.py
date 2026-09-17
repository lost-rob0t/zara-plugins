"""Discovery entry for the optional native-Prolog policy service."""

PLUGIN_VERSION = '0.1.0'


def create_plugin():
    from zara_policy.plugin import create_plugin as create_service
    return create_service()
