from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from .domain import ExpertError, ExpertHost


_DIGEST_RE = re.compile(r"^sha256:[a-f0-9]{64}$")
_SOURCE_RE = re.compile(r"^source:[a-z0-9][a-z0-9._-]{0,127}$")
_SUBJECT_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_REFERENCE_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,127}$")
_TOKEN_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")

_SUBJECT_SCHEMA_REF = "schema:zara.language-expert.subject.v1"
_RESULT_SCHEMA_REF = "schema:zara.language-expert.result.v1"

_OPERATION_PREDICATES = (
    ("applicable", "expert_applicable", False),
    ("inspect", "expert_evidence", False),
    ("diagnose", "expert_diagnostic", False),
    ("style", "expert_style_rule", False),
    ("explain", "expert_explanation", True),
)


@dataclass(frozen=True)
class LanguageExpertProfile:
    language: str
    expert_id: str
    namespace: str
    name: str
    description: str
    extensions: tuple[str, ...]

    def applies_to_path(self, path: str | Path) -> bool:
        suffix = Path(path).suffix.lower()
        return suffix in self.extensions


PROLOG_EXPERT = LanguageExpertProfile(
    language="prolog",
    expert_id="language:prolog",
    namespace="prolog-expert",
    name="PrologExpert",
    description="Deterministic Prolog module, predicate, DCG, xref and style adapter.",
    extensions=(".pl", ".pro", ".prolog"),
)

PYTHON_EXPERT = LanguageExpertProfile(
    language="python",
    expert_id="language:python",
    namespace="python-expert",
    name="PythonExpert",
    description="Deterministic Python AST, scope, import, diagnostic and style adapter.",
    extensions=(".py", ".pyi"),
)

NIM_EXPERT = LanguageExpertProfile(
    language="nim",
    expert_id="language:nim",
    namespace="nim-expert",
    name="NimExpert",
    description="Deterministic Nim parser, compiler, module, template, macro and style adapter.",
    extensions=(".nim", ".nims", ".nimble"),
)

_LANGUAGE_EXPERT_PROFILES = (PROLOG_EXPERT, PYTHON_EXPERT, NIM_EXPERT)


def profile_for_language(language: str) -> LanguageExpertProfile:
    for profile in _LANGUAGE_EXPERT_PROFILES:
        if profile.language == language:
            return profile
    raise ExpertError(f"unsupported language expert: {language!r}")


def language_expert_schemas() -> dict[str, dict[str, Any]]:
    return {
        _SUBJECT_SCHEMA_REF: {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "additionalProperties": False,
            "required": ["subject_id"],
            "properties": {
                "subject_id": {
                    "type": "string",
                    "pattern": "^[a-z][a-z0-9_]{0,63}$",
                }
            },
        },
        _RESULT_SCHEMA_REF: {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "additionalProperties": False,
            "required": [
                "protocol",
                "expert_id",
                "operation",
                "subject_id",
                "source_reference",
                "manifest_digest",
                "runtime_generation",
                "evidence",
                "explanation",
                "model_calls",
            ],
            "properties": {
                "protocol": {"const": "ZARA-EXPERT/1"},
                "expert_id": {"type": "string"},
                "operation": {
                    "enum": [operation for operation, _, _ in _OPERATION_PREDICATES]
                },
                "subject_id": {"type": "string"},
                "source_reference": {"type": "string"},
                "manifest_digest": {"type": "string"},
                "runtime_generation": {"type": "integer", "minimum": 1},
                "evidence": {"type": "array"},
                "explanation": {"type": "array"},
                "model_calls": {"const": 0},
            },
        },
    }


class LanguageExpertAdapter:
    """Zara adapter over one already-installed canonical language expert package.

    This class does not own discovery, scheduling, permissions, source parsing, or
    expert definitions. It binds a canonical package to the existing ExpertHost,
    exposes ZARA-EXPERT/1 descriptor metadata, and maps a closed operation set to
    fixed predicates. Source text is never interpolated into Prolog goals.
    """

    def __init__(
        self,
        host: ExpertHost,
        profile: LanguageExpertProfile,
        *,
        source_reference: str,
        manifest_digest: str,
        registry_generation: int,
        runtime_generation: int,
    ) -> None:
        self._host = host
        self.profile = profile
        self.source_reference = self._validate_source_reference(source_reference)
        self.manifest_digest = self._validate_manifest_digest(manifest_digest)
        self.registry_generation = self._validate_generation(
            registry_generation,
            "registry_generation",
        )
        self.runtime_generation = self._validate_generation(
            runtime_generation,
            "runtime_generation",
        )

    def register(self, knowledge_bases: Iterable[Path]) -> None:
        self._host.register(self.profile.namespace, knowledge_bases)

    def descriptor(
        self,
        *,
        node_id: str,
        runtime_id: str,
        available: bool,
        unavailable_reason: str | None = None,
    ) -> dict[str, Any]:
        node_id = self._validate_reference(node_id, "node_id")
        runtime_id = self._validate_token(runtime_id, "runtime_id")
        if not isinstance(available, bool):
            raise ExpertError("available must be boolean")
        if available:
            if unavailable_reason is not None:
                raise ExpertError("available expert cannot have unavailable_reason")
            availability = "available"
        else:
            if (
                not isinstance(unavailable_reason, str)
                or not unavailable_reason
                or len(unavailable_reason) > 256
            ):
                raise ExpertError("unavailable expert requires a bounded reason")
            availability = "unavailable"

        operations = []
        for operation, _, _ in _OPERATION_PREDICATES:
            operations.append(
                {
                    "id": operation,
                    "input_schema": _SUBJECT_SCHEMA_REF,
                    "output_schema": _RESULT_SCHEMA_REF,
                    "effects": [],
                    "required_capabilities": [],
                }
            )

        return {
            "protocol": "ZARA-EXPERT/1",
            "expert_id": self.profile.expert_id,
            "expert_version": "1",
            "package_namespace": "zara-expert.language-adapters",
            "manifest_digest": self.manifest_digest,
            "name": self.profile.name,
            "description": self.profile.description,
            "source_reference": self.source_reference,
            "reasoning_kind": "symbolic",
            "operations": operations,
            "applicability_schema": _SUBJECT_SCHEMA_REF,
            "required_observations": ["source-index"],
            "required_capabilities": [],
            "possible_effects": [],
            "supported_engines": ["swipl"],
            "supported_platforms": ["zara-runtime"],
            "placement": {
                "node_id": node_id,
                "runtime_id": runtime_id,
            },
            "fallback_policy": "none",
            "delegation_policy": "none",
            "resource_limits": {
                "timeout_ms": 1000,
                "max_results": 16,
                "max_output_bytes": 65536,
                "max_model_calls": 0,
            },
            "registry_generation": self.registry_generation,
            "availability": availability,
            "unavailable_reason": unavailable_reason,
        }

    def invoke(
        self,
        operation: str,
        subject_id: str,
        *,
        limits: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        predicate, explain = self._operation(operation)
        subject_id = self._validate_subject(subject_id)
        bounded = self._validate_limits(limits)
        goal = f"{predicate}({subject_id}, Result)"
        runner = self._host.explain if explain else self._host.query
        result = runner(
            self.profile.namespace,
            goal,
            timeout_seconds=bounded["timeout_ms"] / 1000.0,
            max_results=bounded["max_results"],
            max_output_bytes=bounded["max_output_bytes"],
        )
        evidence = result.get("results", [])
        explanation = result.get("trace", [])
        if not isinstance(evidence, list) or not isinstance(explanation, list):
            raise ExpertError(f"{self.profile.namespace}: malformed expert evidence")
        return {
            "protocol": "ZARA-EXPERT/1",
            "expert_id": self.profile.expert_id,
            "operation": operation,
            "subject_id": subject_id,
            "source_reference": self.source_reference,
            "manifest_digest": self.manifest_digest,
            "runtime_generation": self.runtime_generation,
            "evidence": evidence,
            "explanation": explanation,
            "model_calls": 0,
        }

    @staticmethod
    def _operation(operation: str) -> tuple[str, bool]:
        for name, predicate, explain in _OPERATION_PREDICATES:
            if operation == name:
                return predicate, explain
        raise ExpertError(f"unsupported language expert operation: {operation!r}")

    @staticmethod
    def _validate_subject(subject_id: str) -> str:
        if not isinstance(subject_id, str) or not _SUBJECT_RE.fullmatch(subject_id):
            raise ExpertError("subject_id must be a safe symbolic token")
        return subject_id

    @staticmethod
    def _validate_source_reference(source_reference: str) -> str:
        if not isinstance(source_reference, str) or not _SOURCE_RE.fullmatch(source_reference):
            raise ExpertError("invalid source_reference")
        return source_reference

    @staticmethod
    def _validate_manifest_digest(manifest_digest: str) -> str:
        if not isinstance(manifest_digest, str) or not _DIGEST_RE.fullmatch(manifest_digest):
            raise ExpertError("invalid manifest_digest")
        return manifest_digest

    @staticmethod
    def _validate_generation(value: int, name: str) -> int:
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise ExpertError(f"{name} must be a positive integer")
        return value

    @staticmethod
    def _validate_reference(value: str, name: str) -> str:
        if not isinstance(value, str) or not _REFERENCE_RE.fullmatch(value):
            raise ExpertError(f"invalid {name}")
        return value

    @staticmethod
    def _validate_token(value: str, name: str) -> str:
        if not isinstance(value, str) or not _TOKEN_RE.fullmatch(value):
            raise ExpertError(f"invalid {name}")
        return value

    @staticmethod
    def _validate_limits(limits: dict[str, Any] | None) -> dict[str, int]:
        defaults = {
            "timeout_ms": 1000,
            "max_results": 16,
            "max_output_bytes": 65536,
            "max_model_calls": 0,
        }
        if limits is None:
            return defaults
        if not isinstance(limits, dict) or set(limits) != set(defaults):
            raise ExpertError("limits must contain the canonical four budget fields")
        for key in ("timeout_ms", "max_results", "max_output_bytes", "max_model_calls"):
            value = limits[key]
            if isinstance(value, bool) or not isinstance(value, int):
                raise ExpertError(f"{key} must be an integer")
        if limits["max_model_calls"] != 0:
            raise ExpertError("max_model_calls must remain 0 for symbolic experts")
        if limits["timeout_ms"] < 1 or limits["timeout_ms"] > defaults["timeout_ms"]:
            raise ExpertError("timeout_ms exceeds the symbolic adapter budget")
        if limits["max_results"] < 1 or limits["max_results"] > defaults["max_results"]:
            raise ExpertError("max_results exceeds the symbolic adapter budget")
        if (
            limits["max_output_bytes"] < 1
            or limits["max_output_bytes"] > defaults["max_output_bytes"]
        ):
            raise ExpertError("max_output_bytes exceeds the symbolic adapter budget")
        return dict(limits)
