"""Bounded Emacs IPC with fixed operation templates."""

from __future__ import annotations

import json
import math
import subprocess
from datetime import date
from pathlib import Path
from typing import Callable

from .config import EmacsConfig


class EmacsError(RuntimeError):
    pass


class EmacsClient:
    def __init__(self, config: EmacsConfig, *, runner: Callable | None = None) -> None:
        config.validate()
        self.config = config
        self._runner = runner or subprocess.run

    def _run(self, argv: list[str]) -> str:
        try:
            result = self._runner(
                argv,
                capture_output=True,
                text=True,
                timeout=self.config.timeout_seconds,
                check=False,
                shell=False,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise EmacsError("Emacs client/server unavailable") from error
        if result.returncode != 0:
            detail = str(result.stderr or "Emacs operation failed").strip()[:512]
            raise EmacsError(detail)
        return str(result.stdout or "").strip()[:8192]

    def _eval(self, expression: str) -> str:
        return self._run(
            [
                self.config.emacsclient,
                "--socket-name",
                self.config.server_name,
                "--alternate-editor=false",
                "--eval",
                expression,
            ]
        )

    def _eval_json(self, expression: str):
        raw = self._eval(expression)
        try:
            decoded = json.loads(raw)
            if isinstance(decoded, str):
                return json.loads(decoded)
            return decoded
        except (TypeError, json.JSONDecodeError) as error:
            raise EmacsError("Emacs returned malformed JSON") from error

    @staticmethod
    def _single_line(name: str, value: str, *, maximum: int) -> str:
        if not isinstance(value, str) or not value.strip() or len(value) > maximum:
            raise EmacsError(f"{name} must contain 1 to {maximum} characters")
        if "\x00" in value or "\n" in value or "\r" in value:
            raise EmacsError(f"{name} must be a single line")
        return value.strip()

    def open_file(self, path: str) -> dict:
        resolved = Path(str(path)).expanduser()
        if not resolved.is_absolute() or "\x00" in str(resolved):
            raise EmacsError("file path must be an absolute path")
        self._run(
            [
                self.config.emacsclient,
                "--socket-name",
                self.config.server_name,
                "--alternate-editor=false",
                "--no-wait",
                "--",
                str(resolved),
            ]
        )
        return {"operation": "open_file", "path": str(resolved), "acknowledged": True}

    def open_scratch(self) -> dict:
        self._eval('(progn (switch-to-buffer "*scratch*") (buffer-name))')
        return {"operation": "open_scratch", "buffer": "*scratch*", "acknowledged": True}

    def open_buffer(self, name: str) -> dict:
        if not isinstance(name, str) or not name or len(name) > 256 or "\x00" in name:
            raise EmacsError("buffer name is invalid")
        expression = f"(progn (switch-to-buffer {json.dumps(name)}) (buffer-name))"
        self._eval(expression)
        return {"operation": "open_buffer", "buffer": name, "acknowledged": True}

    def open_daily(self, day: str = "today") -> dict:
        value = date.today().isoformat() if day == "today" else str(day)
        try:
            date.fromisoformat(value)
        except ValueError as error:
            raise EmacsError("daily date must be ISO YYYY-MM-DD or today") from error
        encoded = json.dumps(value)
        expression = (
            "(progn (require 'org-roam-dailies) "
            f"(org-roam-dailies--capture (org-read-date nil t {encoded}) t nil) "
            "(or (buffer-file-name) (buffer-name)))"
        )
        observed = self._eval(expression)
        return {
            "operation": "open_daily",
            "date": value,
            "observed": observed,
            "acknowledged": True,
            "post_open": {"request": "dictation", "started": False},
        }

    def _notes_root(self) -> str:
        return str(Path(self.config.notes_root).expanduser())

    def shared_memory(self, limit: int = 100) -> dict:
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 500:
            raise EmacsError("limit must be an integer between 1 and 500")
        root = json.dumps(self._notes_root())
        expression = (
            "(progn (require 'org) (require 'org-ql) (require 'json) (require 'seq) "
            f"(let* ((root (file-name-as-directory (expand-file-name {root}))) "
            "(files (directory-files-recursively root \"\\\\.org\\\\'\")) "
            "(rows (org-ql-select files "
            "'(and (property \"KIND\" \"memory\") "
            "(property \"MEMORY_SCOPE\" \"shared\") "
            "(property \"STATUS\" \"active\")) "
            ":action (lambda () "
            "`((id . ,(or (org-entry-get nil \"ID\") \"\")) "
            "(title . ,(org-get-heading t t t t)) "
            "(subject . ,(or (org-entry-get nil \"SUBJECT\") \"\")) "
            "(value . ,(or (org-entry-get nil \"VALUE\") \"\")) "
            "(revision . ,(string-to-number (or (org-entry-get nil \"REV\") \"0\"))) "
            "(author . ,(or (org-entry-get nil \"AUTHOR\") \"\")) "
            "(source . ,(or (org-entry-get nil \"SOURCE\") \"\")) "
            "(supersedes . ,(or (org-entry-get nil \"SUPERSEDES\") \"\"))))))) "
            f"(json-serialize (seq-take rows {limit}))))"
        )
        rows = self._eval_json(expression)
        return {"operation": "shared_memory", "rows": rows, "count": len(rows)}

    def inventory(self, limit: int = 100) -> dict:
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 500:
            raise EmacsError("limit must be an integer between 1 and 500")
        root = json.dumps(self._notes_root())
        expression = (
            "(progn (require 'org) (require 'org-ql) (require 'json) (require 'seq) "
            f"(let* ((root (file-name-as-directory (expand-file-name {root}))) "
            "(files (directory-files-recursively root \"\\\\.org\\\\'\")) "
            "(rows (org-ql-select files "
            "'(or (property \"KIND\" \"inventory-item\") "
            "(property \"KIND\" \"inventory-location\") "
            "(property \"KIND\" \"inventory-event\") "
            "(property \"KIND\" \"food-event\")) "
            ":action (lambda () "
            "`((id . ,(or (org-entry-get nil \"ID\") \"\")) "
            "(kind . ,(or (org-entry-get nil \"KIND\") \"\")) "
            "(title . ,(org-get-heading t t t t)) "
            "(event . ,(or (org-entry-get nil \"EVENT\") \"\")) "
            "(item_id . ,(or (org-entry-get nil \"ITEM_ID\") \"\")) "
            "(qty . ,(or (org-entry-get nil \"QTY\") \"\")) "
            "(unit . ,(or (org-entry-get nil \"UNIT\") \"\")) "
            "(source . ,(or (org-entry-get nil \"SOURCE\") \"\"))))))) "
            f"(json-serialize (seq-take rows {limit}))))"
        )
        rows = self._eval_json(expression)
        return {"operation": "inventory", "rows": rows, "count": len(rows)}

    def record_inventory_event(
        self,
        event: str,
        item_key: str,
        qty: float,
        unit: str,
        source: str,
        item_id: str = "",
        from_location: str = "",
        to_location: str = "",
        day: str = "today",
    ) -> dict:
        allowed = {
            "ordered",
            "receive",
            "buy",
            "putaway",
            "move",
            "open",
            "consume",
            "waste",
            "return",
            "adjust",
        }
        if event not in allowed:
            raise EmacsError(f"unsupported inventory event: {event}")
        if isinstance(qty, bool) or not isinstance(qty, (int, float)) or not math.isfinite(qty) or qty <= 0:
            raise EmacsError("qty must be a positive finite number")
        item_key = self._single_line("item_key", item_key, maximum=256)
        unit = self._single_line("unit", unit, maximum=64)
        source = self._single_line("source", source, maximum=512)
        if item_id:
            item_id = self._single_line("item_id", item_id, maximum=128)
        if from_location:
            from_location = self._single_line("from_location", from_location, maximum=256)
        if to_location:
            to_location = self._single_line("to_location", to_location, maximum=256)
        value = date.today().isoformat() if day == "today" else str(day)
        try:
            date.fromisoformat(value)
        except ValueError as error:
            raise EmacsError("inventory day must be ISO YYYY-MM-DD or today") from error

        root = json.dumps(self._notes_root())
        encoded_day = json.dumps(value)
        encoded_event = json.dumps(event)
        encoded_item_key = json.dumps(item_key)
        encoded_item_id = json.dumps(item_id)
        encoded_qty = json.dumps(format(float(qty), ".12g"))
        encoded_unit = json.dumps(unit)
        encoded_source = json.dumps(source)
        encoded_from = json.dumps(from_location)
        encoded_to = json.dumps(to_location)
        expression = (
            "(progn (require 'org) (require 'org-id) (require 'json) "
            f"(let* ((root (file-name-as-directory (expand-file-name {root}))) "
            "(dir (expand-file-name \"daily/\" root)) "
            f"(day {encoded_day}) (event {encoded_event}) "
            f"(item-key {encoded_item_key}) (item-id {encoded_item_id}) "
            f"(qty {encoded_qty}) (unit {encoded_unit}) (source {encoded_source}) "
            f"(from-location {encoded_from}) (to-location {encoded_to}) "
            "(file (expand-file-name (concat day \".org\") dir)) "
            "(event-id (org-id-new))) "
            "(make-directory dir t) "
            "(unless (file-exists-p file) "
            "(with-temp-file file "
            "(insert \"#+title: \" day \"\\n#+filetags: :daily:\\n:PROPERTIES:\\n:ID:       \" "
            "(org-id-new) \"\\n:KIND:     daily\\n:DATE:     \" day \"\\n:END:\\n\"))) "
            "(with-current-buffer (find-file-noselect file) "
            "(goto-char (point-max)) (unless (bolp) (insert \"\\n\")) "
            "(insert \"\\n* INVENTORY \" event \" \" item-key \"\\n:PROPERTIES:\\n:ID:       \" "
            "event-id \"\\n:KIND:     inventory-event\\n:EVENT:    \" event "
            "\"\\n:ITEM_KEY: \" item-key \"\\n:ITEM_ID:  \" item-id "
            "\"\\n:QTY:      \" qty \"\\n:UNIT:     \" unit "
            "\"\\n:FROM_LOCATION: \" from-location \"\\n:TO_LOCATION: \" to-location "
            "\"\\n:SOURCE:   \" source \"\\n:AT:       \" "
            "(format-time-string \"[%Y-%m-%d %a %H:%M]\") \"\\n:END:\\n\") "
            "(save-buffer)) "
            "(json-serialize `((id . ,event-id) (file . ,file) (day . ,day) "
            "(event . ,event) (item_key . ,item-key) (qty . ,qty) (unit . ,unit))))))"
        )
        result = self._eval_json(expression)
        return {"operation": "record_inventory_event", **result, "acknowledged": True}

    def append_shared_memory(
        self,
        subject: str,
        value: str,
        author: str,
        source: str,
        supersedes: str = "",
    ) -> dict:
        subject = self._single_line("subject", subject, maximum=256)
        value = self._single_line("value", value, maximum=2048)
        author = self._single_line("author", author, maximum=128)
        source = self._single_line("source", source, maximum=512)
        if supersedes:
            supersedes = self._single_line("supersedes", supersedes, maximum=128)
        root = json.dumps(self._notes_root())
        encoded_subject = json.dumps(subject)
        encoded_value = json.dumps(value)
        encoded_author = json.dumps(author)
        encoded_source = json.dumps(source)
        encoded_supersedes = json.dumps(supersedes)
        expression = (
            "(progn (require 'org) (require 'org-id) (require 'org-ql) (require 'json) "
            f"(let* ((root (file-name-as-directory (expand-file-name {root}))) "
            "(dir (expand-file-name \"memory/shared/\" root)) "
            "(files (when (file-directory-p root) "
            "(directory-files-recursively root \"\\\\.org\\\\'\"))) "
            f"(subject {encoded_subject}) (value {encoded_value}) "
            f"(author {encoded_author}) (source {encoded_source}) "
            f"(supersedes {encoded_supersedes}) "
            "(revisions (org-ql-select files "
            "`(and (property \"KIND\" \"memory\") (property \"SUBJECT\" ,subject)) "
            ":action (lambda () (string-to-number (or (org-entry-get nil \"REV\") \"0\"))))) "
            "(revision (1+ (apply #'max 0 revisions))) "
            "(id (org-id-new)) (file (expand-file-name (concat id \".org\") dir))) "
            "(when (not (string-empty-p supersedes)) "
            "(let ((parents (org-ql-select files `(property \"ID\" ,supersedes) "
            ":action (lambda () (or (org-entry-get nil \"SUBJECT\") \"\"))))) "
            "(unless parents (error \"superseded memory ID not found\")) "
            "(unless (string= subject (car parents)) (error \"superseded memory subject mismatch\")))) "
            "(make-directory dir t) "
            "(with-temp-file file "
            "(insert \"#+title: Shared memory: \" subject \"\\n#+filetags: :memory:shared:\\n\" "
            "\":PROPERTIES:\\n:ID:       \" id \"\\n:KIND:     memory\\n:MEMORY_SCOPE: shared\\n:SUBJECT:  \" subject "
            "\"\\n:VALUE:    \" value \"\\n:REV:      \" (number-to-string revision) "
            "\"\\n:STATUS:   active\\n:AUTHOR:   \" author \"\\n:SOURCE:   \" source "
            "\"\\n:CREATED:  \" (format-time-string \"[%Y-%m-%d %a %H:%M]\") "
            "\"\\n:SUPERSEDES: \" supersedes \"\\n:END:\\n\")) "
            "(when (fboundp 'org-roam-db-sync) (org-roam-db-sync)) "
            "(when (fboundp 'gpt-todos-sync) (gpt-todos-sync file)) "
            "(json-serialize `((id . ,id) (file . ,file) (subject . ,subject) "
            "(revision . ,revision) (supersedes . ,supersedes))))))"
        )
        result = self._eval_json(expression)
        return {"operation": "append_shared_memory", **result, "acknowledged": True}

    def open_magit(self, project_id: str) -> dict:
        if project_id not in self.config.projects:
            raise EmacsError(f"unknown project alias: {project_id}")
        path = str(Path(self.config.projects[project_id]).expanduser())
        expression = (
            "(progn (require 'magit) "
            f"(magit-status {json.dumps(path)}) t)"
        )
        self._eval(expression)
        return {
            "operation": "open_magit",
            "project_id": project_id,
            "acknowledged": True,
        }

    def context(self) -> dict:
        expression = (
            "(let ((file (buffer-file-name)) (buffer (buffer-name)) "
            "(project (when (fboundp 'project-current) (project-current nil)))) "
            "(prin1-to-string (list :buffer buffer :file file :project "
            "(when project (car (project-roots project))))))"
        )
        observed = self._eval(expression)
        return {"operation": "context", "observed": observed, "acknowledged": True}
