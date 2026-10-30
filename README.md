# Backup Verifier

Create a content-addressed backup of a local directory, verify its manifest and blobs, and rehearse a restore into a new directory. Built for Lord_Sumi's portfolio.

## Try it

Python 3.10+; standard-library runtime only.

```bash
git clone https://github.com/sumiEmpire001/backup-verifier.git
cd backup-verifier
python -m unittest discover -s tests -v
python -m backup_verifier create /path/to/source /path/to/new-backup
python -m backup_verifier verify /path/to/new-backup
python -m backup_verifier restore /path/to/new-backup /path/to/new-restore
```

Backup and restore destinations **must not exist**; their parent directories must exist. A restore rehearses recovery into a separate directory, preserving the original source and backup.

## Architecture

The backup contains a versioned `manifest.json` and a `blobs/` directory. Each file is represented by its relative path, SHA-256, byte size and basic permission bits. Identical content shares one blob. Empty directories are recorded explicitly. Source files are checked for size/mtime changes during copying, and copied blobs are hashed before publication.

Creation and restore use temporary sibling directories. Verification runs before the staged directory is renamed into its final location. Restore validates relative paths, copies the referenced blobs, checks restored hashes and sizes, then applies file permission bits. A failed staged operation removes its staging directory. An existing destination is refused during normal operation; concurrent/adversarial changes to destination paths are outside this version's guarantees.

## Verification contract

`verify` reports missing, unsafe, resized or hash-mismatched blobs. Malformed manifests, duplicate paths, missing parent directories, traversal paths and unsupported metadata raise errors. The CLI exits 1 for a damaged backup report and 2 for invalid input or an operational error.

```python
from backup_verifier import create, verify, restore

report = create("source", "new-backup")
assert verify("new-backup")["valid"]
assert restore("new-backup", "new-restore")["verified"]
```

The checksums detect accidental corruption; they do not authenticate an untrusted manifest. An attacker who replaces both a blob and its recorded checksum can create a different internally consistent backup.

## Tests and limits

Local validation on 30 October 2026: **13 tests passed**, covering actual directory restore rehearsals, binary/Unicode content, empty directories, deduplication, corrupt or missing blobs, pre-existing targets, unsafe paths, symlinks and malformed metadata. CI is configured for Python 3.10, 3.12 and 3.13.

Only regular files and directories are supported; symlinks and special files are rejected. File timestamps, directory permission bits, extended attributes, ownership, hard-link relationships and filesystem snapshots are not preserved. Stop writers before backing up a changing source; metadata checks are not a snapshot system or a defense against adversarial filesystem races. Staging files are not fsynced for power-loss durability. The source must fit the chosen storage capacity; there is no incremental scheduler, encryption, compression, retention deletion or cloud upload. The manifest is capped at 20 MiB. Protect the backup directory, and test restoration separately on the intended operating system.

MIT license; see [LICENSE](LICENSE).
