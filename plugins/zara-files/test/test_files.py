import os
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from zara_files.files import FileDomain, FileDomainError


class FileDomainTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name) / "root"
        self.outside = Path(self.temporary.name) / "outside"
        self.root.mkdir()
        self.outside.mkdir()
        (self.root / "notes").mkdir()
        (self.root / "notes" / "a.txt").write_text("alpha\nbeta\n", encoding="utf-8")
        (self.root / "b.md").write_text("bravo", encoding="utf-8")
        self.domain = FileDomain([self.root], max_read_bytes=128, max_results=8)

    def tearDown(self):
        self.temporary.cleanup()

    def test_search_is_root_scoped_structured_and_bounded(self):
        results = self.domain.search(name="*.txt")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["relative_path"], "notes/a.txt")
        self.assertEqual(results[0]["root_id"], "root-0")
        self.assertEqual(results[0]["kind"], "file")
        self.assertNotIn(str(self.root), repr(results))

    def test_read_text_is_bounded_and_binary_is_metadata_first(self):
        result = self.domain.read_text("root-0", "notes/a.txt", max_bytes=5)
        self.assertEqual(result["text"], "alpha")
        self.assertTrue(result["truncated"])
        (self.root / "binary.bin").write_bytes(b"\x00\x01secret")
        with self.assertRaisesRegex(FileDomainError, "binary"):
            self.domain.read_text("root-0", "binary.bin")
        metadata = self.domain.metadata("root-0", "binary.bin")
        self.assertEqual(metadata["kind"], "file")
        self.assertEqual(metadata["size"], 8)

    def test_traversal_and_absolute_paths_cannot_escape_root(self):
        for path in ("../outside/secret.txt", "/etc/passwd", "notes/../../outside"):
            with self.subTest(path=path):
                with self.assertRaises(FileDomainError):
                    self.domain.metadata("root-0", path)

    def test_symlink_file_and_directory_escapes_are_rejected(self):
        (self.outside / "secret.txt").write_text("secret", encoding="utf-8")
        (self.root / "link-file").symlink_to(self.outside / "secret.txt")
        (self.root / "link-dir").symlink_to(self.outside, target_is_directory=True)
        with self.assertRaisesRegex(FileDomainError, "symlink"):
            self.domain.read_text("root-0", "link-file")
        with self.assertRaisesRegex(FileDomainError, "symlink"):
            self.domain.metadata("root-0", "link-dir/secret.txt")
        self.assertEqual(self.domain.search(name="secret.txt"), [])

    def test_copy_move_rename_create_and_delete_are_explicit_and_verified(self):
        created = self.domain.create_text("root-0", "new.txt", "hello")
        self.assertEqual(created["relative_path"], "new.txt")
        copied = self.domain.copy("root-0", "new.txt", "root-0", "notes/copied.txt")
        self.assertEqual(copied["relative_path"], "notes/copied.txt")
        moved = self.domain.move("root-0", "notes/copied.txt", "root-0", "moved.txt")
        self.assertEqual(moved["relative_path"], "moved.txt")
        renamed = self.domain.rename("root-0", "moved.txt", "renamed.txt")
        self.assertEqual(renamed["relative_path"], "renamed.txt")
        deleted = self.domain.delete("root-0", "renamed.txt")
        self.assertEqual(deleted, {"deleted": True, "root_id": "root-0", "relative_path": "renamed.txt"})
        self.assertFalse((self.root / "renamed.txt").exists())

    def test_mutations_refuse_overwrite_parent_symlinks_and_directory_delete(self):
        (self.root / "existing.txt").write_text("keep", encoding="utf-8")
        with self.assertRaisesRegex(FileDomainError, "exists"):
            self.domain.create_text("root-0", "existing.txt", "replace")
        (self.root / "escape").symlink_to(self.outside, target_is_directory=True)
        with self.assertRaisesRegex(FileDomainError, "symlink"):
            self.domain.create_text("root-0", "escape/pwned.txt", "nope")
        self.assertFalse((self.outside / "pwned.txt").exists())
        with self.assertRaisesRegex(FileDomainError, "directory"):
            self.domain.delete("root-0", "notes")

    def test_cross_root_copy_stays_inside_configured_roots(self):
        second = Path(self.temporary.name) / "second"
        second.mkdir()
        domain = FileDomain([self.root, second])
        result = domain.copy("root-0", "b.md", "root-1", "copied.md")
        self.assertEqual(result["root_id"], "root-1")
        self.assertEqual((second / "copied.md").read_text(encoding="utf-8"), "bravo")

    def test_unknown_root_and_optional_semantic_search_fail_explicitly(self):
        with self.assertRaisesRegex(FileDomainError, "unknown root"):
            self.domain.metadata("root-99", "x")
        result = self.domain.semantic_search("alpha")
        self.assertEqual(result, {"status": "unavailable", "reason": "semantic-index-not-configured", "results": []})

    def test_root_configuration_rejects_symlink_and_non_directory(self):
        symlink_root = Path(self.temporary.name) / "root-link"
        symlink_root.symlink_to(self.root, target_is_directory=True)
        with self.assertRaisesRegex(FileDomainError, "symlink"):
            FileDomain([symlink_root])
        regular = Path(self.temporary.name) / "regular"
        regular.write_text("x", encoding="utf-8")
        with self.assertRaises(FileDomainError):
            FileDomain([regular])


if __name__ == "__main__":
    unittest.main()
