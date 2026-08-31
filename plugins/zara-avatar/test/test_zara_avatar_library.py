"""Avatar library tests: VRM validation, import, list, select, delete."""

from __future__ import annotations

import json
import struct
import tempfile
import unittest
from pathlib import Path

import avatar_test_support

AVATAR = avatar_test_support.load_avatar_module()


def build_glb(extensions=("VRMCvrm",), spec_version="1.0", *, version=2) -> bytes:
    document = {
        "asset": {"version": "2.0"},
        "extensionsUsed": list(extensions),
    }
    if spec_version is not None:
        document["extensions"] = {"VRMCvrm": {"specVersion": spec_version}}
    payload = json.dumps(document).encode("utf-8")
    while len(payload) % 4:
        payload += b" "
    header = struct.pack("<4sII", b"glTF", version, 12 + 8 + len(payload))
    chunk = struct.pack("<I", len(payload)) + b"JSON" + payload
    return header + chunk


class VrmValidationTest(unittest.TestCase):
    def test_valid_vrm_1(self) -> None:
        info = AVATAR.validate_vrm(build_glb())
        self.assertEqual(info.vrm_version, "1.0")

    def test_valid_vrm_0(self) -> None:
        info = AVATAR.validate_vrm(
            build_glb(extensions=("VRM",), spec_version=None)
        )
        self.assertEqual(info.vrm_version, "0.x")

    def test_empty_file_rejected(self) -> None:
        with self.assertRaises(AVATAR.InvalidVrmError) as caught:
            AVATAR.validate_vrm(b"")
        self.assertIn("empty", str(caught.exception).lower())

    def test_bad_magic_rejected(self) -> None:
        blob = b"NOPE" + b"\x00" * 64
        with self.assertRaises(AVATAR.InvalidVrmError):
            AVATAR.validate_vrm(blob)

    def test_truncated_file_rejected(self) -> None:
        blob = build_glb()[:20]
        with self.assertRaises(AVATAR.InvalidVrmError):
            AVATAR.validate_vrm(blob)

    def test_wrong_gltf_version_rejected(self) -> None:
        with self.assertRaises(AVATAR.InvalidVrmError):
            AVATAR.validate_vrm(build_glb(version=7))

    def test_non_json_chunk_rejected(self) -> None:
        blob = b"glTF" + struct.pack("<II", 2, 12 + 8 + 4) + struct.pack("<I", 4) + b"BIN\x00"
        with self.assertRaises(AVATAR.InvalidVrmError):
            AVATAR.validate_vrm(blob)

    def test_gltf_without_vrm_extension_rejected(self) -> None:
        with self.assertRaises(AVATAR.InvalidVrmError) as caught:
            AVATAR.validate_vrm(build_glb(extensions=(), spec_version=None))
        self.assertIn("vrm", str(caught.exception).lower())

    def test_invalid_json_chunk_rejected(self) -> None:
        payload = b"{not json" + b" " * 4
        header = struct.pack("<4sII", b"glTF", 2, 12 + 8 + len(payload))
        chunk = struct.pack("<I", len(payload)) + b"JSON" + payload
        with self.assertRaises(AVATAR.InvalidVrmError):
            AVATAR.validate_vrm(header + chunk)


class AvatarLibraryTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.library = AVATAR.AvatarLibrary(Path(self.tmp.name) / "avatars")

    def test_import_creates_record_and_file(self) -> None:
        record = self.library.import_avatar("Sample Avatar", build_glb())
        self.assertTrue(record.avatar_id.startswith("sample-avatar-"))
        self.assertEqual(record.name, "Sample Avatar")
        self.assertTrue(record.path.exists())
        self.assertEqual(record.vrm_version, "1.0")
        self.assertTrue(record.size_bytes > 0)
        self.assertTrue(record.sha256)

    def test_list_round_trip(self) -> None:
        first = self.library.import_avatar("First", build_glb())
        second = self.library.import_avatar("Second", build_glb())
        records = self.library.list_avatars()
        self.assertEqual(
            sorted(record.avatar_id for record in records),
            sorted([first.avatar_id, second.avatar_id]),
        )

    def test_same_name_imports_get_distinct_ids(self) -> None:
        first = self.library.import_avatar("Twin", build_glb(spec_version="1.0"))
        second = self.library.import_avatar(
            "Twin", build_glb(spec_version=None, extensions=("VRM",))
        )
        self.assertNotEqual(first.avatar_id, second.avatar_id)
        self.assertEqual(
            [record.name for record in self.library.list_avatars()],
            ["Twin", "Twin"],
        )

    def test_identical_bytes_dedupe_to_one_avatar(self) -> None:
        first = self.library.import_avatar("Twin", build_glb())
        second = self.library.import_avatar("Twin", build_glb())
        self.assertEqual(first.avatar_id, second.avatar_id)
        self.assertEqual(len(self.library.list_avatars()), 1)

    def test_get_missing_returns_none(self) -> None:
        self.assertIsNone(self.library.get("nope"))

    def test_delete_removes_files(self) -> None:
        record = self.library.import_avatar("Doomed", build_glb())
        self.library.delete(record.avatar_id)
        self.assertFalse(record.path.exists())
        self.assertIsNone(self.library.get(record.avatar_id))

    def test_delete_missing_raises(self) -> None:
        with self.assertRaises(KeyError):
            self.library.delete("ghost")

    def test_corrupt_vrm_import_rejected_without_side_effects(self) -> None:
        with self.assertRaises(AVATAR.InvalidVrmError):
            self.library.import_avatar("Broken", b"garbage")
        self.assertEqual(self.library.list_avatars(), ())

    def test_oversized_import_rejected(self) -> None:
        strict = AVATAR.AvatarLibrary(Path(self.tmp.name) / "small", max_bytes=16)
        with self.assertRaises(AVATAR.InvalidVrmError):
            strict.import_avatar("Huge", build_glb())

    def test_import_from_path(self) -> None:
        source = Path(self.tmp.name) / "source.vrm"
        source.write_bytes(build_glb())
        record = self.library.import_from_path("From Disk", source)
        self.assertTrue(record.path.exists())
        self.assertNotEqual(record.path, source)

    def test_import_from_missing_path_raises(self) -> None:
        with self.assertRaises(FileNotFoundError):
            self.library.import_from_path("Ghost", Path(self.tmp.name) / "gone.vrm")

    def test_id_rejects_path_traversal(self) -> None:
        with self.assertRaises(KeyError):
            self.library.get("../escape")
        with self.assertRaises(KeyError):
            self.library.delete("a/b")


if __name__ == "__main__":
    unittest.main()
