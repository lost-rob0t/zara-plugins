from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Callable


class CodingError(RuntimeError):
    pass


Runner = Callable[..., subprocess.CompletedProcess[str]]


class RepositoryInspector:
    MAX_DISCOVERY_ENTRIES = 1000
    MAX_COMMIT_MESSAGE_CHARS = 4096
    MAX_CHANGED_PATHS = 100

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

    def list_repositories(self, *, limit: int = 50) -> list[dict[str, str]]:
        limit = self._bounded_limit(limit)
        repositories = []
        scanned = 0
        for allowed_root in self._roots:
            if not allowed_root.is_dir():
                continue
            candidates = [allowed_root] if self._is_git_root(allowed_root) else []
            if not candidates:
                for candidate in sorted(allowed_root.iterdir(), key=lambda path: path.name):
                    scanned += 1
                    if scanned > self.MAX_DISCOVERY_ENTRIES:
                        raise CodingError(
                            f"repository discovery exceeds scan limit of {self.MAX_DISCOVERY_ENTRIES} entries"
                        )
                    if candidate.is_symlink() or not candidate.is_dir():
                        continue
                    if self._is_git_root(candidate):
                        candidates.append(candidate)
            for candidate in candidates:
                repositories.append({"root": str(candidate.resolve())})
                if len(repositories) > limit:
                    raise CodingError(f"repository discovery exceeds repository limit of {limit}")
        repositories.sort(key=lambda item: item["root"])
        return repositories

    @staticmethod
    def _is_git_root(path: Path) -> bool:
        marker = path / ".git"
        return marker.is_dir() or marker.is_file()

    def inspect(self, path: Path) -> dict[str, object]:
        root = self._repository_root(path)
        head = self._git(root, "rev-parse", "HEAD").strip()
        branch_result = self._run(root, "symbolic-ref", "--short", "-q", "HEAD", check=False)
        branch = branch_result.stdout.strip() if branch_result.returncode == 0 else "DETACHED"
        changed = set(filter(None, self._git(root, "diff", "--name-only", "HEAD").splitlines()))
        untracked = set(filter(None, self._git(root, "ls-files", "--others", "--exclude-standard").splitlines()))
        changed_paths = sorted(changed | untracked)
        if len(changed_paths) > self.MAX_CHANGED_PATHS:
            raise CodingError(f"repository inspection exceeds changed path limit of {self.MAX_CHANGED_PATHS}")
        final_head = self._git(root, "rev-parse", "HEAD").strip()
        final_branch_result = self._run(root, "symbolic-ref", "--short", "-q", "HEAD", check=False)
        final_branch = final_branch_result.stdout.strip() if final_branch_result.returncode == 0 else "DETACHED"
        if final_head != head or final_branch != branch:
            raise CodingError("repository identity changed during inspection")
        return {
            "root": str(root),
            "head": head,
            "branch": branch,
            "dirty": bool(changed_paths),
            "changed_paths": changed_paths,
        }

    def diff(self, path: Path, *, max_files: int = 50) -> list[dict[str, object]]:
        max_files = self._bounded_limit(max_files)
        root = self._repository_root(path)
        head = self._git(root, "rev-parse", "HEAD").strip()
        output = self._git(root, "diff", "--numstat", "--no-renames", "HEAD", "--")
        entries = []
        for line in output.splitlines():
            if not line:
                continue
            fields = line.split("\t", 2)
            if len(fields) != 3:
                raise CodingError("git diff returned malformed structured output")
            additions, deletions, changed_path = fields
            binary = additions == "-" and deletions == "-"
            entries.append(
                {
                    "path": changed_path,
                    "additions": None if binary else int(additions),
                    "deletions": None if binary else int(deletions),
                    "binary": binary,
                }
            )
            if len(entries) > max_files:
                raise CodingError(f"git diff exceeds file limit of {max_files}")
        final_head = self._git(root, "rev-parse", "HEAD").strip()
        if final_head != head:
            raise CodingError("repository identity changed during diff")
        return entries

    def log(self, path: Path, *, limit: int = 20) -> list[dict[str, object]]:
        limit = self._bounded_limit(limit)
        root = self._repository_root(path)
        output = self._git(
            root,
            "log",
            f"--max-count={limit}",
            "--format=%H%x09%P%x09%an%x09%aI%x09%s",
        )
        history = []
        for line in output.splitlines():
            if not line:
                continue
            fields = line.split("\t", 4)
            if len(fields) != 5:
                raise CodingError("git log returned malformed structured output")
            commit, parents, author, authored_at, subject = fields
            history.append(
                {
                    "commit": commit,
                    "parents": parents.split() if parents else [],
                    "author": author,
                    "authored_at": authored_at,
                    "subject": subject,
                }
            )
        return history

    def branches(self, path: Path, *, limit: int = 50) -> list[dict[str, str]]:
        limit = self._bounded_limit(limit)
        root = self._repository_root(path)
        output = self._git(
            root,
            "for-each-ref",
            f"--count={limit}",
            "--sort=refname",
            "--format=%(refname:short)%09%(objectname)%09%(upstream:short)",
            "refs/heads/",
        )
        branches = self._parse_branch_inventory(output, limit=limit)
        probe = self._git(
            root,
            "for-each-ref",
            f"--count={limit + 1}",
            "--sort=refname",
            "--format=%(refname:short)%09%(objectname)%09%(upstream:short)",
            "refs/heads/",
        )
        self._parse_branch_inventory(probe, limit=limit)
        return branches

    @staticmethod
    def _parse_branch_inventory(output: str, *, limit: int) -> list[dict[str, str]]:
        branches = []
        for line in output.splitlines():
            if not line:
                continue
            fields = line.split("\t", 2)
            if len(fields) != 3:
                raise CodingError("git branch inventory returned malformed structured output")
            name, commit, upstream = fields
            branches.append({"name": name, "commit": commit, "upstream": upstream})
            if len(branches) > limit:
                raise CodingError(f"git branch inventory exceeds branch limit of {limit}")
        return branches

    def create_branch(self, path: Path, name: str, expected_head: str) -> dict[str, str]:
        if not isinstance(name, str) or not name:
            raise ValueError("name must be a non-empty string")
        self._require_full_object_id(expected_head)
        root = self._repository_root(path)
        ref = f"refs/heads/{name}"
        self._git(root, "check-ref-format", ref)
        actual_head = self._git(root, "rev-parse", "HEAD").strip()
        if actual_head.lower() != expected_head.lower():
            raise CodingError("repository HEAD changed since expected_head was observed")
        self._git(root, "update-ref", ref, expected_head, "")
        return {"branch": name, "head": expected_head}

    def delete_branch(self, path: Path, name: str, expected_head: str) -> dict[str, str]:
        if not isinstance(name, str) or not name:
            raise ValueError("name must be a non-empty string")
        self._require_full_object_id(expected_head)
        root = self._repository_root(path)
        ref = f"refs/heads/{name}"
        self._git(root, "check-ref-format", ref)
        for worktree in self.worktrees(root, limit=100):
            if worktree["branch"] == name:
                raise CodingError(f"branch is checked out in worktree: {worktree['path']}")
        self._git(root, "update-ref", "-d", ref, expected_head)
        return {"branch": name, "deleted_head": expected_head}

    def commit(self, path: Path, message: str, expected_head: str) -> dict[str, str]:
        if not isinstance(message, str) or not message.strip():
            raise ValueError("message must be a non-empty string")
        if "\x00" in message or len(message) > self.MAX_COMMIT_MESSAGE_CHARS:
            raise ValueError(f"message must contain at most {self.MAX_COMMIT_MESSAGE_CHARS} characters and no NUL")
        self._require_full_object_id(expected_head)
        root = self._repository_root(path)
        try:
            branch_result = self._run(root, "symbolic-ref", "-q", "HEAD", check=False)
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError) as exc:
            raise CodingError("git commit requires an attached branch") from exc
        branch_ref = branch_result.stdout.strip() if branch_result.returncode == 0 else ""
        if not branch_ref.startswith("refs/heads/"):
            raise CodingError("git commit requires an attached branch")
        actual_head = self._git(root, "rev-parse", "HEAD").strip()
        if actual_head.lower() != expected_head.lower():
            raise CodingError("repository HEAD changed since expected_head was observed")
        tree = self._git(root, "write-tree").strip()
        parent_tree = self._git(root, "rev-parse", f"{expected_head}^{{tree}}").strip()
        if tree == parent_tree:
            raise CodingError("git commit has no staged changes")
        commit_message = message if message.endswith("\n") else f"{message}\n"
        commit_oid = self._git_input(root, commit_message, "commit-tree", tree, "-p", expected_head).strip()
        try:
            self._require_full_object_id(commit_oid)
        except ValueError as exc:
            raise CodingError("git commit-tree returned malformed object ID") from exc
        self._git(root, "update-ref", branch_ref, commit_oid, expected_head)
        return {
            "branch": branch_ref.removeprefix("refs/heads/"),
            "parent": expected_head,
            "commit": commit_oid,
            "tree": tree,
        }

    def worktrees(self, path: Path, *, limit: int = 50) -> list[dict[str, object]]:
        limit = self._bounded_limit(limit)
        root = self._repository_root(path)
        output = self._git(root, "worktree", "list", "--porcelain", "-z")
        worktrees = []
        record: dict[str, object] = {}
        for field in output.split("\0"):
            if not field:
                if record:
                    worktrees.append(self._normalize_worktree_record(record))
                    if len(worktrees) > limit:
                        raise CodingError(f"git worktree inventory exceeds worktree limit of {limit}")
                    record = {}
                continue
            key, separator, value = field.partition(" ")
            if key in {"detached", "bare"} and not separator:
                record[key] = True
            elif key in {"worktree", "HEAD", "branch", "locked", "prunable"}:
                record[key] = value if separator else ""
            else:
                raise CodingError(f"git worktree returned unsupported porcelain field: {key}")
        if record:
            worktrees.append(self._normalize_worktree_record(record))
            if len(worktrees) > limit:
                raise CodingError(f"git worktree inventory exceeds worktree limit of {limit}")
        return worktrees

    def _normalize_worktree_record(self, record: dict[str, object]) -> dict[str, object]:
        path_value = record.get("worktree")
        head = record.get("HEAD")
        if not isinstance(path_value, str) or not path_value or not isinstance(head, str) or not head:
            raise CodingError("git worktree returned malformed structured output")
        worktree_path = Path(path_value).expanduser().resolve()
        self._require_allowed(worktree_path)
        branch_value = record.get("branch")
        if branch_value is not None:
            if not isinstance(branch_value, str) or not branch_value.startswith("refs/heads/"):
                raise CodingError("git worktree returned malformed branch ref")
            branch: str | None = branch_value.removeprefix("refs/heads/")
        else:
            branch = None
        detached = bool(record.get("detached", False))
        if detached and branch is not None:
            raise CodingError("git worktree returned contradictory branch state")
        return {
            "path": str(worktree_path),
            "head": head,
            "branch": branch,
            "detached": detached,
            "locked": self._porcelain_reason(record.get("locked")),
            "prunable": self._porcelain_reason(record.get("prunable")),
        }

    @staticmethod
    def _porcelain_reason(value: object) -> str | None:
        if value is None:
            return None
        if not isinstance(value, str):
            raise CodingError("git worktree returned malformed reason field")
        return value or "unspecified"

    @staticmethod
    def _require_full_object_id(value: str) -> None:
        if (
            not isinstance(value, str)
            or len(value) not in {40, 64}
            or any(character not in "0123456789abcdefABCDEF" for character in value)
        ):
            raise ValueError("expected_head must be a full hexadecimal Git object ID")

    @staticmethod
    def _bounded_limit(limit: int) -> int:
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 100:
            raise ValueError("limit must be an integer between 1 and 100")
        return limit

    def _repository_root(self, path: Path) -> Path:
        candidate = Path(path).expanduser().resolve()
        if not candidate.is_dir():
            raise CodingError("repository path must be an existing directory")
        self._require_allowed(candidate)
        root_text = self._git(candidate, "rev-parse", "--show-toplevel", repository_error=True).strip()
        root = Path(root_text).resolve()
        self._require_allowed(root)
        return root

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

    def _git_input(self, root: Path, input_text: str, *args: str) -> str:
        try:
            result = self._runner(
                [self._executable, "-C", str(root), *args],
                input=input_text,
                check=True,
                capture_output=True,
                text=True,
                timeout=5,
                shell=False,
            )
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError) as exc:
            raise CodingError(f"git operation failed: {' '.join(args)}") from exc
        return result.stdout

    def _git(self, root: Path, *args: str, repository_error: bool = False) -> str:
        try:
            result = self._run(root, *args)
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError) as exc:
            if repository_error:
                raise CodingError("path is not a usable Git repository") from exc
            raise CodingError(f"git operation failed: {' '.join(args)}") from exc
        return result.stdout


class PrologRLMBridge:
    SPEC_CATALOG_GOAL = (
        "rlm_spec_lang:spec_language_catalog([],O),"
        "write_canonical(O),nl,halt"
    )
    SPEC_NORMALIZE_GOAL = (
        "read_string(user_input,_,S),"
        "rlm_spec_lang:spec_source_normalize(S,O),"
        "write_canonical(O),nl,halt"
    )
    MAX_SPEC_CHARS = 65536

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

    def spec_catalog(self) -> dict[str, str]:
        outcome = self._run_spec_language(self.SPEC_CATALOG_GOAL, operation="catalog")
        return {"status": "ok" if outcome.startswith("ok(") else "rejected", "outcome": outcome}

    def normalize_spec(self, source: str) -> dict[str, str]:
        if not isinstance(source, str) or not source.strip():
            raise CodingError("SPEC source must be a non-empty string")
        if len(source) > self.MAX_SPEC_CHARS:
            raise CodingError(f"SPEC source exceeds {self.MAX_SPEC_CHARS} character limit")
        outcome = self._run_spec_language(self.SPEC_NORMALIZE_GOAL, operation="normalization", input_text=source)
        return {"status": "ok" if outcome.startswith("ok(") else "rejected", "outcome": outcome}

    def _run_spec_language(self, goal: str, *, operation: str, input_text: str | None = None) -> str:
        module = self.checkout / "prolog" / "rlm_spec_lang.pl"
        if self._validate_checkout and not module.is_file():
            raise CodingError("Prolog-RLM SPEC language module is unavailable")
        argv = [self.executable, "-q", "-s", str(module), "-g", goal]
        kwargs = {
            "check": True,
            "capture_output": True,
            "text": True,
            "timeout": self.timeout_seconds,
            "shell": False,
        }
        if input_text is not None:
            kwargs["input"] = input_text
        try:
            result = self._runner(argv, **kwargs)
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError) as exc:
            raise CodingError(f"Prolog-RLM SPEC {operation} failed") from exc
        lines = [line for line in result.stdout.splitlines() if line.strip()]
        if not lines:
            raise CodingError(f"Prolog-RLM SPEC {operation} returned no outcome")
        return lines[-1].strip()
