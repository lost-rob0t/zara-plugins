import json
import os
import tempfile
import unittest
from pathlib import Path

from discord_test_support import install_zara_stubs

install_zara_stubs()

from zara_discord_service.moderation_audit import ModerationAudit


class ModerationAuditTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.directory = Path(self.temporary.name)

    def tearDown(self):
        self.temporary.cleanup()

    def test_records_only_bounded_structured_moderation_metadata(self):
        audit = ModerationAudit(self.directory, max_bytes=4096, max_files=2)

        audit.record(
            guild_id=10,
            channel_id=20,
            message_id=30,
            target_id=40,
            action="timeout",
            outcome="refused",
            reason="  protected administrator\nwith control\x00bytes  ",
        )

        path = self.directory / "moderation-audit.jsonl"
        entry = json.loads(path.read_text(encoding="utf-8").strip())
        self.assertEqual(
            set(entry),
            {
                "timestamp",
                "guild_id",
                "channel_id",
                "message_id",
                "target_id",
                "action",
                "outcome",
                "actor",
                "reason",
            },
        )
        self.assertEqual(entry["actor"], "mara")
        self.assertEqual(entry["reason"], "protected administrator with controlbytes")
        self.assertNotIn("content", entry)
        self.assertNotIn("username", entry)
        self.assertNotIn("token", entry)
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.directory.stat().st_mode & 0o777, 0o700)

    def test_reason_is_bounded(self):
        audit = ModerationAudit(self.directory)
        audit.record(
            guild_id=1,
            channel_id=2,
            message_id=3,
            target_id=4,
            action="warn",
            outcome="succeeded",
            reason="x" * 1000,
        )

        entry = json.loads(
            (self.directory / "moderation-audit.jsonl")
            .read_text(encoding="utf-8")
            .strip()
        )
        self.assertLessEqual(len(entry["reason"]), 256)

    def test_rotates_before_file_exceeds_bound(self):
        audit = ModerationAudit(self.directory, max_bytes=400, max_files=2)
        for index in range(20):
            audit.record(
                guild_id=1,
                channel_id=2,
                message_id=index,
                target_id=4,
                action="warn",
                outcome="succeeded",
                reason="bounded audit entry",
            )

        current = self.directory / "moderation-audit.jsonl"
        rotated = self.directory / "moderation-audit.jsonl.1"
        self.assertTrue(current.is_file())
        self.assertTrue(rotated.is_file())
        self.assertLessEqual(current.stat().st_size, 400)
        self.assertLessEqual(rotated.stat().st_size, 400)
        self.assertFalse((self.directory / "moderation-audit.jsonl.2").exists())

    def test_rejects_unknown_actions_outcomes_and_invalid_ids(self):
        audit = ModerationAudit(self.directory)
        common = dict(guild_id=1, channel_id=2, message_id=3, target_id=4)
        with self.assertRaisesRegex(ValueError, "action"):
            audit.record(**common, action="shell", outcome="failed", reason="no")
        with self.assertRaisesRegex(ValueError, "outcome"):
            audit.record(**common, action="warn", outcome="maybe", reason="no")
        with self.assertRaisesRegex(ValueError, "guild_id"):
            audit.record(
                guild_id=-1,
                channel_id=2,
                message_id=3,
                target_id=4,
                action="warn",
                outcome="failed",
                reason="no",
            )


if __name__ == "__main__":
    unittest.main()
