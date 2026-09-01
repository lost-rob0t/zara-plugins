import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "libexec" / "gpt-todos-sync"
REQUIRED = ("bash", "git", "flock", "find", "awk", "sort", "realpath")


def command(*args, cwd=None, env=None, check=True):
    return subprocess.run(
        args,
        cwd=cwd,
        env=env,
        check=check,
        capture_output=True,
        text=True,
    )


@unittest.skipUnless(all(shutil.which(name) for name in REQUIRED), "sync test tools unavailable")
class SyncIntegrationTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.remote = root / "remote.git"
        self.seed = root / "seed"
        self.durable = root / "durable"
        self.live = root / "live"
        self.other = root / "other"
        command("git", "init", "--bare", "-q", str(self.remote))
        command("git", "clone", "-q", str(self.remote), str(self.seed))
        self._identity(self.seed, "seed")
        (self.seed / "agenda").mkdir()
        (self.seed / "agenda" / "weekly.org").write_text(
            "#+title: Weekly\n\n* Weekly\n** TODO Initial task\n"
            ":PROPERTIES:\n:ID: task-1\n:END:\n",
            encoding="utf-8",
        )
        command("git", "add", "agenda", cwd=self.seed)
        command("git", "commit", "-qm", "init", cwd=self.seed)
        command("git", "push", "-q", "-u", "origin", "HEAD:master", cwd=self.seed)
        command("git", "symbolic-ref", "HEAD", "refs/heads/master", cwd=self.remote)
        command("git", "clone", "-q", str(self.remote), str(self.durable))
        self._identity(self.durable, "durable")
        self.live.mkdir()
        shutil.copy2(self.durable / "agenda" / "weekly.org", self.live / "weekly.org")
        self.environment = os.environ.copy()
        self.environment.update(
            {
                "GPT_TODOS_REPO_DIR": str(self.durable),
                "GPT_TODOS_ORG_DIR": str(self.live),
                "GPT_TODOS_REMOTE": str(self.remote),
                "XDG_RUNTIME_DIR": str(root),
                "XDG_STATE_HOME": str(root / "state"),
                "GIT_TERMINAL_PROMPT": "0",
            }
        )

    def _identity(self, repo, name):
        command("git", "config", "user.name", name, cwd=repo)
        command("git", "config", "user.email", f"{name}@example.test", cwd=repo)

    def _sync(self, check=True):
        return command("bash", str(SCRIPT), env=self.environment, check=check)

    def test_local_done_remote_update_and_conflict_fail_closed(self):
        weekly = self.live / "weekly.org"
        weekly.write_text(
            weekly.read_text(encoding="utf-8").replace("** TODO Initial task", "** DONE Initial task"),
            encoding="utf-8",
        )
        self._sync()
        subject = command("git", "log", "-1", "--pretty=%s", cwd=self.durable).stdout.strip()
        self.assertEqual(subject, "agenda: mark 1 done in weekly.org")

        command("git", "clone", "-q", str(self.remote), str(self.other))
        self._identity(self.other, "other")
        other_weekly = self.other / "agenda" / "weekly.org"
        other_weekly.write_text(other_weekly.read_text(encoding="utf-8") + "\nRemote note\n", encoding="utf-8")
        command("git", "add", "agenda/weekly.org", cwd=self.other)
        command("git", "commit", "-qm", "remote", cwd=self.other)
        command("git", "push", "-q", cwd=self.other)
        self._sync()
        self.assertIn("Remote note", weekly.read_text(encoding="utf-8"))

        weekly.write_text(weekly.read_text(encoding="utf-8") + "\nLocal conflict\n", encoding="utf-8")
        other_weekly.write_text(other_weekly.read_text(encoding="utf-8") + "\nRemote conflict\n", encoding="utf-8")
        command("git", "add", "agenda/weekly.org", cwd=self.other)
        command("git", "commit", "-qm", "remote conflict", cwd=self.other)
        command("git", "push", "-q", cwd=self.other)
        failed = self._sync(check=False)
        self.assertEqual(failed.returncode, 5)
        self.assertIn("concurrent local/remote edit conflict", failed.stderr)
        local_text = weekly.read_text(encoding="utf-8")
        self.assertIn("Local conflict", local_text)
        self.assertNotIn("Remote conflict", local_text)
