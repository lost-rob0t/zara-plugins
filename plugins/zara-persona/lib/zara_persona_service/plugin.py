"""Zara service plugin exposing operator-owned persona context."""

from __future__ import annotations

from langchain_core.tools import StructuredTool
from zara.plugins import PluginMetadata, ServicePlugin

from .config import PersonaConfig
from .prolog import load_prolog_context


PLUGIN_VERSION = "0.1.0"


class ZaraPersonaPlugin(ServicePlugin):
    metadata = PluginMetadata(
        name="zara-persona",
        version=PLUGIN_VERSION,
        api_version="1",
        description="Private local persona context with optional SWI-Prolog",
    )

    def __init__(self) -> None:
        self._config = PersonaConfig()
        self._started = False

    def start(self, runtime) -> None:
        if self._started:
            raise RuntimeError("zara-persona already started")
        self._started = True
        self._config = PersonaConfig.load(runtime.configuration)
        self._config.validate_files()

    def stop(self) -> None:
        return None

    def tools(self):
        return (
            StructuredTool.from_function(
                func=self.persona_context,
                name="persona_context",
                description=(
                    "Return the operator-configured private persona/style context. "
                    "Use it when persona guidance is needed; do not invent missing context."
                ),
            ),
        )

    def persona_context(self) -> str:
        config = self._config
        if not config.enabled:
            return ""

        sections: list[str] = []
        if config.prompt.strip():
            sections.append(config.prompt.strip())
        if config.prompt_file is not None:
            text = config.prompt_file.read_text(encoding="utf-8")
            if len(text) > config.max_chars:
                raise ValueError("persona prompt file exceeds max_chars")
            if text.strip():
                sections.append(text.strip())
        if config.prolog_enabled and config.prolog_file is not None:
            context = load_prolog_context(
                swipl_program=config.swipl_program,
                prolog_file=config.prolog_file,
                timeout_seconds=config.prolog_timeout_seconds,
                output_limit=config.prolog_output_limit,
            )
            if context:
                sections.append(context)

        result = "\n\n".join(sections)
        if len(result) > config.max_chars:
            raise ValueError("persona context exceeds max_chars")
        return result


def create_plugin():
    return ZaraPersonaPlugin()
