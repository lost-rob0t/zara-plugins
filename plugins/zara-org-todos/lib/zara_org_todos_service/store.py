from __future__ import annotations

import os
import re
import tempfile
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable, Optional


ACTIVE_STATES = ("TODO", "STRT", "WAIT", "HOLD", "IDEA", "LOOP")
ALL_STATES = ACTIVE_STATES + ("DONE", "KILL")
HEADLINE_RE = re.compile(
    r"^(?P<stars>\*+)\s+(?P<state>" + "|".join(ALL_STATES) + r")\s+(?P<body>.*)$"
)
ID_RE = re.compile(r"^\s*:ID:\s*(?P<id>\S+)\s*$")
SCHEDULED_RE = re.compile(r"^\s*SCHEDULED:\s*(?P<value><[^>]+>)\s*$")
TAGS_RE = re.compile(r"(?P<title>.*?)(?P<tags>\s+:[^\s:]+(?::[^\s:]+)*:)\s*$")


@dataclass(frozen=True)
class OrgTask:
    task_id: str
    state: str
    title: str
    path: Path
    line_number: int
    scheduled: str = ""

    def render(self) -> str:
        schedule = f" scheduled={self.scheduled}" if self.scheduled else ""
        return f"{self.task_id} [{self.state}] {self.title}{schedule} ({self.path.name})"


@dataclass(frozen=True)
class _LocatedTask:
    task: OrgTask
    lines: list[str]
    heading_index: int
    block_end: int


class OrgTodoStore:
    def __init__(self, org_dir: Path) -> None:
        self.org_dir = org_dir
        self._lock = threading.RLock()

    def list(self, statuses: Optional[Iterable[str]] = None) -> list[OrgTask]:
        allowed = set(statuses or ACTIVE_STATES)
        invalid = allowed.difference(ALL_STATES)
        if invalid:
            raise ValueError(f"unknown Org todo state(s): {', '.join(sorted(invalid))}")
        with self._lock:
            return [task for task in self._scan() if task.state in allowed]

    def search(self, query: str, statuses: Optional[Iterable[str]] = None) -> list[OrgTask]:
        needle = query.strip().lower()
        if not needle:
            raise ValueError("query must not be empty")
        return [task for task in self.list(statuses) if needle in task.title.lower()]

    def add(self, title: str, *, task_id: Optional[str] = None) -> OrgTask:
        clean = " ".join(title.split())
        if not clean:
            raise ValueError("todo title must not be empty")
        identifier = task_id or str(uuid.uuid4())
        path = self.org_dir / "inbox.org"
        with self._lock:
            self.org_dir.mkdir(parents=True, exist_ok=True)
            if path.exists():
                text = path.read_text(encoding="utf-8")
            else:
                text = (
                    "#+title: Inbox\n"
                    "#+todo: TODO(t) STRT(s!) WAIT(w@/!) HOLD(h@/!) IDEA(i) LOOP(l!) | DONE(d!) KILL(k@/!)\n"
                    "#+startup: overview\n\n"
                    "* Inbox\n"
                )
            if not text.endswith("\n"):
                text += "\n"
            block = (
                f"\n** TODO {clean}\n"
                ":PROPERTIES:\n"
                f":ID:       {identifier}\n"
                ":OWNER:    user\n"
                ":SOURCE:   zara-org-todos\n"
                ":END:\n"
            )
            self._atomic_write(path, text + block)
            located = self._locate(identifier)
            if located is None:
                raise RuntimeError("captured todo could not be reloaded")
            return located.task

    def complete(self, task_id: str) -> OrgTask:
        return self._change_state(task_id, "DONE")

    def reopen(self, task_id: str) -> OrgTask:
        return self._change_state(task_id, "TODO")

    def edit(self, task_id: str, title: str) -> OrgTask:
        clean = " ".join(title.split())
        if not clean:
            raise ValueError("todo title must not be empty")
        with self._lock:
            located = self._require(task_id)
            lines = located.lines
            lines[located.heading_index] = self._rewrite_heading(
                lines[located.heading_index], title=clean
            )
            self._atomic_write(located.task.path, "".join(lines))
            return self._require(task_id).task

    def schedule(self, task_id: str, schedule: str) -> OrgTask:
        try:
            moment = datetime.strptime(schedule.strip(), "%Y-%m-%d %H:%M")
        except ValueError as error:
            raise ValueError("schedule must use YYYY-MM-DD HH:MM") from error
        timestamp = moment.strftime("<%Y-%m-%d %a %H:%M>")
        with self._lock:
            located = self._require(task_id)
            lines = located.lines
            replacement = f"SCHEDULED: {timestamp}\n"
            scheduled_index = None
            for index in range(located.heading_index + 1, located.block_end):
                if SCHEDULED_RE.match(lines[index]):
                    scheduled_index = index
                    break
            if scheduled_index is None:
                lines.insert(located.heading_index + 1, replacement)
            else:
                lines[scheduled_index] = replacement
            self._atomic_write(located.task.path, "".join(lines))
            return self._require(task_id).task

    def path_for(self, task_id: str) -> Path:
        with self._lock:
            return self._require(task_id).task.path

    def _change_state(self, task_id: str, state: str) -> OrgTask:
        with self._lock:
            located = self._require(task_id)
            if located.task.state == state:
                return located.task
            lines = located.lines
            lines[located.heading_index] = self._rewrite_heading(
                lines[located.heading_index], state=state
            )
            self._atomic_write(located.task.path, "".join(lines))
            return self._require(task_id).task

    def _scan(self) -> list[OrgTask]:
        tasks = []
        if not self.org_dir.exists():
            return tasks
        for path in sorted(self.org_dir.rglob("*.org")):
            if not path.is_file():
                continue
            lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
            tasks.extend(self._tasks_from_lines(path, lines))
        return tasks

    def _tasks_from_lines(self, path: Path, lines: list[str]) -> list[OrgTask]:
        tasks = []
        for index, line in enumerate(lines):
            match = HEADLINE_RE.match(line.rstrip("\n"))
            if match is None:
                continue
            level = len(match.group("stars"))
            end = self._block_end(lines, index, level)
            identifier = ""
            scheduled = ""
            for candidate in lines[index + 1 : end]:
                id_match = ID_RE.match(candidate.rstrip("\n"))
                if id_match:
                    identifier = id_match.group("id")
                schedule_match = SCHEDULED_RE.match(candidate.rstrip("\n"))
                if schedule_match:
                    scheduled = schedule_match.group("value")
            if not identifier:
                continue
            title, _tags = self._split_body(match.group("body"))
            tasks.append(
                OrgTask(
                    task_id=identifier,
                    state=match.group("state"),
                    title=title,
                    path=path,
                    line_number=index + 1,
                    scheduled=scheduled,
                )
            )
        return tasks

    def _locate(self, task_id: str) -> Optional[_LocatedTask]:
        for path in sorted(self.org_dir.rglob("*.org")) if self.org_dir.exists() else ():
            if not path.is_file():
                continue
            lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
            for index, line in enumerate(lines):
                match = HEADLINE_RE.match(line.rstrip("\n"))
                if match is None:
                    continue
                level = len(match.group("stars"))
                end = self._block_end(lines, index, level)
                for candidate in lines[index + 1 : end]:
                    id_match = ID_RE.match(candidate.rstrip("\n"))
                    if id_match and id_match.group("id") == task_id:
                        scheduled = ""
                        for scheduled_line in lines[index + 1 : end]:
                            schedule_match = SCHEDULED_RE.match(scheduled_line.rstrip("\n"))
                            if schedule_match:
                                scheduled = schedule_match.group("value")
                                break
                        title, _tags = self._split_body(match.group("body"))
                        task = OrgTask(
                            task_id=task_id,
                            state=match.group("state"),
                            title=title,
                            path=path,
                            line_number=index + 1,
                            scheduled=scheduled,
                        )
                        return _LocatedTask(task, lines, index, end)
        return None

    def _require(self, task_id: str) -> _LocatedTask:
        located = self._locate(task_id)
        if located is None:
            raise KeyError(f"todo id not found: {task_id}")
        return located

    @staticmethod
    def _block_end(lines: list[str], heading_index: int, level: int) -> int:
        for index in range(heading_index + 1, len(lines)):
            stripped = lines[index].lstrip()
            if not stripped.startswith("*"):
                continue
            match = re.match(r"^(\*+)\s", lines[index])
            if match and len(match.group(1)) <= level:
                return index
        return len(lines)

    @staticmethod
    def _split_body(body: str) -> tuple[str, str]:
        match = TAGS_RE.match(body)
        if match is None:
            return body.strip(), ""
        return match.group("title").strip(), match.group("tags")

    @classmethod
    def _rewrite_heading(
        cls,
        line: str,
        *,
        state: Optional[str] = None,
        title: Optional[str] = None,
    ) -> str:
        newline = "\n" if line.endswith("\n") else ""
        match = HEADLINE_RE.match(line.rstrip("\n"))
        if match is None:
            raise ValueError("not an Org todo heading")
        old_title, tags = cls._split_body(match.group("body"))
        new_state = state or match.group("state")
        new_title = title or old_title
        suffix = tags if tags else ""
        return f"{match.group('stars')} {new_state} {new_title}{suffix}{newline}"

    @staticmethod
    def _atomic_write(path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        destination = path.resolve(strict=False) if path.is_symlink() else path
        destination.parent.mkdir(parents=True, exist_ok=True)
        mode = destination.stat().st_mode & 0o777 if destination.exists() else 0o600
        descriptor, temporary = tempfile.mkstemp(
            prefix=f".{destination.name}.", dir=destination.parent
        )
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                handle.write(content)
            os.chmod(temporary, mode)
            os.replace(temporary, destination)
        except Exception:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass
            raise
