import json
import tempfile
import unittest
from pathlib import Path
from backup_verifier import create, verify, restore


class BackupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "source"
        self.backup = self.root / "backup"
        self.source.mkdir()
        (self.source / "nested").mkdir()
        (self.source / "empty").mkdir()
        (self.source / "hello.txt").write_text("Hello 🌍", encoding="utf-8")
        (self.source / "nested" / "bytes.bin").write_bytes(bytes(range(256)))

    def manifest(self):
        return json.loads((self.backup / "manifest.json").read_text())

    def write_manifest(self, value):
        (self.backup / "manifest.json").write_text(json.dumps(value))

    def test_restore_rehearsal_preserves_bytes_and_empty_directories(self):
        report = create(self.source, self.backup)
        self.assertEqual(report["files"], 2)
        self.assertTrue(verify(self.backup)["valid"])
        destination = self.root / "restore"
        self.assertTrue(restore(self.backup, destination)["verified"])
        for path in self.source.rglob("*"):
            other = destination / path.relative_to(self.source)
            self.assertEqual(path.is_dir(), other.is_dir())
            if path.is_file():
                self.assertEqual(path.read_bytes(), other.read_bytes())

    def test_identical_content_is_deduplicated(self):
        (self.source / "copy.txt").write_bytes((self.source / "hello.txt").read_bytes())
        report = create(self.source, self.backup)
        self.assertEqual(report["files"], 3)
        self.assertEqual(report["unique_blobs"], 2)

    def test_corrupt_blob_is_detected_and_restore_refused(self):
        create(self.source, self.backup)
        blob = next((self.backup / "blobs").iterdir())
        blob.write_bytes(b"corrupt")
        self.assertFalse(verify(self.backup)["valid"])
        target = self.root / "restore"
        with self.assertRaises(ValueError):
            restore(self.backup, target)
        self.assertFalse(target.exists())

    def test_missing_blob_is_reported(self):
        create(self.source, self.backup)
        next((self.backup / "blobs").iterdir()).unlink()
        self.assertFalse(verify(self.backup)["valid"])

    def test_restore_does_not_overwrite_existing_destination(self):
        create(self.source, self.backup)
        target = self.root / "restore"
        target.mkdir()
        with self.assertRaises(ValueError):
            restore(self.backup, target)
        self.assertTrue(target.is_dir())

    def test_backup_refuses_existing_destination_and_recursion(self):
        self.backup.mkdir()
        with self.assertRaises(ValueError):
            create(self.source, self.backup)
        with self.assertRaises(ValueError):
            create(self.source, self.source / "backup")

    def test_source_symlinks_are_rejected_and_staging_removed(self):
        (self.source / "link").symlink_to(self.source / "hello.txt")
        with self.assertRaises(ValueError):
            create(self.source, self.backup)
        self.assertFalse(self.backup.exists())
        self.assertEqual(list(self.root.glob(".backup-stage-*")), [])

    def test_manifest_path_traversal_is_rejected(self):
        create(self.source, self.backup)
        original = self.manifest()
        for path in ("../escape", "/absolute", "C:/windows", "a\\b", "a//b", "a/./b"):
            value = json.loads(json.dumps(original))
            value["files"][0]["path"] = path
            self.write_manifest(value)
            with self.subTest(path=path), self.assertRaises(ValueError):
                restore(self.backup, self.root / "restored")
        self.assertFalse((self.root / "escape").exists())

    def test_blob_and_manifest_symlinks_are_rejected(self):
        create(self.source, self.backup)
        blob = next((self.backup / "blobs").iterdir())
        blob.unlink()
        blob.symlink_to(self.source / "hello.txt")
        self.assertFalse(verify(self.backup)["valid"])

    def test_duplicate_and_incomplete_manifest_paths_are_rejected(self):
        create(self.source, self.backup)
        original = self.manifest()
        duplicate = json.loads(json.dumps(original))
        duplicate["files"].append(duplicate["files"][0])
        self.write_manifest(duplicate)
        with self.assertRaises(ValueError):
            verify(self.backup)
        original["directories"] = []
        self.write_manifest(original)
        with self.assertRaises(ValueError):
            verify(self.backup)

    def test_bad_manifest_metadata_is_rejected(self):
        create(self.source, self.backup)
        original = self.manifest()
        for field, value in (("size", -1), ("mode", 0o4777), ("sha256", "bad"), ("sha256", 123)):
            bad = json.loads(json.dumps(original))
            bad["files"][0][field] = value
            self.write_manifest(bad)
            with self.subTest(field=field), self.assertRaises(ValueError):
                verify(self.backup)

    def test_empty_backup_and_restore_work(self):
        empty = self.root / "empty-source"
        empty.mkdir()
        create(empty, self.backup)
        self.assertEqual(verify(self.backup)["files"], 0)
        target = self.root / "empty-restore"
        restore(self.backup, target)
        self.assertEqual(list(target.iterdir()), [])

    def test_restore_inside_backup_is_rejected(self):
        create(self.source, self.backup)
        with self.assertRaises(ValueError):
            restore(self.backup, self.backup / "restore")


if __name__ == "__main__":
    unittest.main()
