"""Zara discovery entry for symbolic memory."""

import os
import sys
from pathlib import Path


PLUGIN_VERSION = "0.1.0"

xdg_root = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
library_dir = xdg_root / "zarathushtra" / "plugins" / "zara-symbolic-memory" / "lib"
if library_dir.is_dir():
    sys.path.insert(0, str(library_dir))


def create_plugin():
    from zara_symbolic_memory.plugin import create_plugin as create_service

    return create_service()
