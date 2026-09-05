from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Callable


class CodingError(RuntimeError):
    pass


Runner = Callable[..., subprocess.CompletedProcess[str]]


class RepositoryInspector:
    def __init__(
        self,
        allowed_roots: tuple[Path, ...],
        *,
        executable: str = "git",
        runner: Runner | None = None,
    ) -> None:
        if not allowed_roots:
            raise ValueError("allowed_roots must not be empty")
        if not executable:
            raise ValueError("executable must not be empty")
        self._roots = tuple(Path(root).expanduser().resolve() for root in allowed_roots)
        self._executable = executable
        self._runner = runner or subprocess.run

    def inspect(self, path: Path) -> dict[str, object]:
        candidate = Path(path).expanduser().resolve()
        if not candidate.is_dir():
            raise CodingError("repository path must be an existing directory")
        self._require_allowed(candidate)
        root_text = self._git(candidate, "rev-parse", "--show-toplevel", repository_error=True).strip()
        root = Path(root_text).resolve()
        self._require_allowed(root)
        head = self._git(root, "rev-parse", "HEAD").strip()
        branch_result = self._run(root, "symbolic-ref", "--short", "-q", "HEAD", check=False)
        branch = branch_result.stdout.strip() if branch_result.returncode == 0 else "DETACHED"
        changed = set(filter(None, self._git(root, "diff", "--name-only", "HEAD").splitlines()))
        untracked = set(filter(None, self._git(root, "ls-files", "--others", "--exclude-standard").splitlines()))
        changed_paths = sorted(changed | untracked)
        return {
            "root": str(root),
            "head": head,
            "branch": branch,
            "dirty": bool(changed_paths),
            "changed_paths": changed_paths,
        }

    def _require_allowed(self, path: Path) -> None:
        if not any(path == root or root in path.parents for root in self._roots):
            raise CodingError("repository path is outside allowed roots")

    def _run(self, root: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        return self._runner(
            [self._executable, "-C", str(root), *args],
            check=check,
            capture_output=True,
            text=True,
            timeout=5,
            shell=False,
        )

    def _git(self, root: Path, *args: str, repository_error: bool = False) -> str:
        try:
            result = self._run(root, *args)
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError) as exc:
            if repository_error:
                raise CodingError("path is not a usable Git repository") from exc
            raise CodingError(f"git operation failed: {' '.join(args)}") from exc
        return result.stdout


class PrologRLMBridge:
    SPEC_NORMALIZE_GOAL = (
        "read_string(user_input,_,S),"
        "rlm_spec_lang:spec_source_normalize(S,O),"
        "write_canonical(O),nl,halt"
    )

    def __init__(
        self,
        checkout: Path,
        *,
        executable: str = "swipl",
        timeout_seconds: float = 5.0,
        runner: Runner | None = None,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self.checkout = Path(checkout).expanduser()
        self.executable = executable
        self.timeout_seconds = timeout_seconds
        self._runner = runner or subprocess.run
        self._validate_checkout = runner is None

    def status(self) -> dict[str, str]:
        facade = self.checkout / "prolog" / "rlm.pl"
        if self._validate_checkout and not facade.is_file():
            return {"status": "unavailable", "reason": "prolog-rlm-checkout-missing"}
        argv = [
            self.executable,
            "-q",
            "-s",
            str(facade),
            "-g",
            "rlm:rlm_ready,rlm:rlm_version(V),format('ready\\t~w~n',[V]),halt",
        ]
        try:
            result = self._runner(
                argv,
                check=True,
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
                shell=False,
            )
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError):
            return {"status": "unavailable", "reason": "prolog-rlm-not-ready"}
        line = result.stdout.strip().splitlines()[-1] if result.stdout.strip() else ""
        prefix = "ready\t"
        if not line.startswith(prefix) or not line[len(prefix):].strip():
            return {"status": "unavailable", "reason": "prolog-rlm-invalid-readiness-output"}
        return {"status": "ready", "version": line[len(prefix):].strip()}

    def normalize_spec(self, source: str) -> dict[str, str]:
        if not isinstance(source, str) or not source.strip():
            raise CodingError("SPEC source must be a non-empty string")
        module = self.checkout / "prolog" / "rlm_spec_lang.pl"
        if self._validate_checkout and not module.is_file():
            raise CodingError("Prolog-RLM SPEC language module is unavailable")
        argv = [
            self.executable,
            "-q",
            "-s",
            str(module),
            "-g",
            self.SPEC_NORMALIZE_GOAL,
        ]
        try:
            result = self._runner(
                argv,
                input=source,
                check=True,
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
                shell=False,
            )
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError) as exc:
            raise CodingError("Prolog-RLM SPEC normalization failed") from exc
        lines = [line for line in result.stdout.splitlines() if line.strip()]
        if not lines:
            raise CodingError("Prolog-RLM SPEC normalization returned no outcome")
        outcome = lines[-1].strip()
        status = "ok" if outcome.startswith("ok(") else "rejected"
        return {"status": status, "outcome": outcome}
