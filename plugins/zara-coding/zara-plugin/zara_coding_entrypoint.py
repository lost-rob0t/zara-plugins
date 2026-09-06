"""Zara discovery entry for the bounded coding harness service plugin."""

from pathlib import Path


PLUGIN_VERSION = "0.1.0"


def create_plugin():
    from zara_coding.task_plugin import create_plugin as create_service

    plugin_root = Path(__file__).resolve().parents[1]
    return create_service(plugin_root=plugin_root)
