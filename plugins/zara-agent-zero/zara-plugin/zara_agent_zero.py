"""Zara discovery entry for the Agent Zero bridge service plugin."""

import os
import sys
from pathlib import Path


PLUGIN_VERSION = "0.1.1"

xdg_root = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
library_dir = xdg_root / "zarathushtra" / "plugins" / "zara-agent-zero" / "lib"
sys.path.insert(0, str(library_dir))


def create_plugin():
    from zara_agent_zero_service.plugin import create_plugin as create_service

    return create_service()
