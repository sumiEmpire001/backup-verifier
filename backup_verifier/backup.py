"""Content-addressed directory backup with verifiable restore rehearsals."""
import hashlib
import json
import os
import re
import shutil
import tempfile
from pathlib import Path, PurePosixPath


def checksum(path):
    result = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            result.update(chunk)
    return result.hexdigest()


def safe_name(name):
    if not isinstance(name, str) or not name or "\\" in name or ":" in name or "\x00" in name:
        raise ValueError("Unsafe manifest path")
    path = PurePosixPath(name)
    if path.is_absolute() or any(part in ("", ".", "..") for part in name.split("/")):
        raise ValueError("Unsafe manifest path")
    return path


def _manifest(backup):
    if backup.is_symlink() or not backup.is_dir():
        raise ValueError("Backup must be a regular directory")
    manifest_path = backup / "manifest.json"
    if manifest_path.is_symlink() or manifest_path.stat().st_size > 20 * 1024 * 1024:
        raise ValueError("Invalid manifest file")
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or type(data.get("format")) is not int or data.get("format") != 1 or not isinstance(data.get("files"), list) or not isinstance(data.get("directories"), list):
        raise ValueError("Unsupported backup manifest")
    seen = set()
    directories = set()
    for name in data["directories"]:
        safe_name(name)
        if name in seen:
            raise ValueError("Duplicate manifest path")
        seen.add(name)
        directories.add(name)
    for item in data["files"]:
        if not isinstance(item, dict) or set(item) != {"path", "sha256", "size", "mode"}:
            raise ValueError("Malformed file entry")
        safe_name(item["path"])
        if item["path"] in seen or not isinstance(item["sha256"], str) or not re.fullmatch(r"[0-9a-f]{64}", item["sha256"]):
            raise ValueError("Duplicate path or invalid checksum")
        if type(item["size"]) is not int or item["size"] < 0 or type(item["mode"]) is not int or not 0 <= item["mode"] <= 0o777:
            raise ValueError("Invalid file metadata")
        seen.add(item["path"])
    files = {item["path"] for item in data["files"]}
    for name in seen:
        for parent in PurePosixPath(name).parents:
            if str(parent) != "." and str(parent) not in directories:
                raise ValueError("Every parent directory must be explicitly listed")
            if str(parent) in files:
                raise ValueError("File path is also a directory ancestor")
    return data


def create(source, destination):
    source, destination = Path(source), Path(destination)
    if source.is_symlink() or not source.is_dir():
        raise ValueError("Source must be a regular directory")
    source = source.resolve()
    destination = destination.absolute()
    if destination.exists() or destination.is_symlink() or not destination.parent.is_dir():
        raise ValueError("Destination must not exist and its parent must exist")
    resolved_destination = destination.resolve()
    if resolved_destination.is_relative_to(source) or source.is_relative_to(resolved_destination):
        raise ValueError("Source and destination must not contain one another")
    temporary = Path(tempfile.mkdtemp(prefix=".backup-stage-", dir=destination.parent))
    try:
        blobs = temporary / "blobs"
        blobs.mkdir()
        files, directories = [], []
        for path in sorted(source.rglob("*")):
            relative = path.relative_to(source).as_posix()
            safe_name(relative)
            if path.is_symlink():
                raise ValueError("Symlinks are not supported: " + relative)
            if path.is_dir():
                directories.append(relative)
                continue
            if not path.is_file():
                raise ValueError("Special files are not supported: " + relative)
            before = path.stat()
            file_hash = checksum(path)
            blob = blobs / file_hash
            if not blob.exists():
                shutil.copyfile(path, blob)
            after = path.stat()
            if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns) or checksum(blob) != file_hash:
                raise ValueError("Source changed while backing up: " + relative)
            files.append({"path": relative, "sha256": file_hash, "size": after.st_size, "mode": after.st_mode & 0o777})
        manifest = {"format": 1, "files": files, "directories": directories}
        (temporary / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        report = verify(temporary)
        if not report["valid"]:
            raise ValueError("Backup staging verification failed")
        # Do not overwrite an existing path, including an empty directory.
        if destination.exists() or destination.is_symlink():
            raise FileExistsError(destination)
        temporary.rename(destination)
        return {"files": len(files), "directories": len(directories), "unique_blobs": len(list((destination / "blobs").iterdir())), "bytes": sum(item["size"] for item in files)}
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)


def verify(backup):
    backup = Path(backup)
    data = _manifest(backup)
    blob_dir = backup / "blobs"
    if blob_dir.is_symlink() or not blob_dir.is_dir():
        raise ValueError("Invalid blob directory")
    findings = []
    checked = {}
    for item in data["files"]:
        blob = blob_dir / item["sha256"]
        if blob.is_symlink() or not blob.is_file():
            findings.append({"path": item["path"], "error": "missing or unsafe blob"})
            continue
        if item["sha256"] not in checked:
            checked[item["sha256"]] = (blob.stat().st_size, checksum(blob))
        size, digest = checked[item["sha256"]]
        if size != item["size"] or digest != item["sha256"]:
            findings.append({"path": item["path"], "error": "size or checksum mismatch"})
    return {"valid": not findings, "files": len(data["files"]), "findings": findings}


def restore(backup, destination):
    backup, destination = Path(backup), Path(destination).absolute()
    data = _manifest(backup)
    report = verify(backup)
    if not report["valid"]:
        raise ValueError("Refusing to restore a damaged backup")
    if destination.exists() or destination.is_symlink() or not destination.parent.is_dir():
        raise ValueError("Restore destination must not exist and its parent must exist")
    if destination.resolve().is_relative_to(backup.resolve()):
        raise ValueError("Restore destination must be outside the backup")
    temporary = Path(tempfile.mkdtemp(prefix=".restore-stage-", dir=destination.parent))
    try:
        for name in sorted(data["directories"], key=lambda name: len(PurePosixPath(name).parts)):
            (temporary / name).mkdir()
        for item in data["files"]:
            target = temporary / item["path"]
            shutil.copyfile(backup / "blobs" / item["sha256"], target)
            if checksum(target) != item["sha256"] or target.stat().st_size != item["size"]:
                raise ValueError("Restored file failed verification")
            os.chmod(target, item["mode"])
        if destination.exists() or destination.is_symlink():
            raise FileExistsError(destination)
        temporary.rename(destination)
        return {"restored": len(data["files"]), "verified": True}
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)
