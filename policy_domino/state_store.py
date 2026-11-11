"""Deterministic, incrementally committable state shards.

The old data/state.json file grew past GitHub's 100 MB single-blob limit.
Keep the same logical state contract while persisting separately compressed
buckets. Rewriting a run only changes git blobs for buckets that changed;
unchanged bytes are left untouched. No old results are thrown away.
"""
from __future__ import annotations

import gzip
import hashlib
import io
import json
import re
from pathlib import Path

STORAGE_VERSION = 1
BUCKET_COUNT = 64
SHARD_THRESHOLD_BYTES = 100_000
KEY_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")


def _compressed_json(value: object) -> bytes:
    content = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    output = io.BytesIO()
    with gzip.GzipFile(fileobj=output, mode="wb", compresslevel=6,
                       mtime=0, filename="") as gz:
        gz.write(content)
    return output.getvalue()


def _unpack(path: Path):
    return json.loads(gzip.decompress(path.read_bytes()).decode("utf-8"))


def _save_unchanged_aware(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.read_bytes() == content:
        return
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(content)
    tmp.replace(path)


def _bucket(key: str) -> str:
    return f"{int.from_bytes(hashlib.sha256(key.encode('utf-8')).digest()[:2], 'big') % BUCKET_COUNT:02x}"


def shard_dir(state_path: Path) -> Path:
    return state_path.parent / state_path.stem


def has_shards(state_path: Path) -> bool:
    return (shard_dir(state_path) / "manifest.json").is_file()


def load_shards(state_path: Path, schema: str) -> dict:
    folder = shard_dir(state_path)
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("version") != STORAGE_VERSION or manifest.get("schema") != schema:
        raise ValueError("Incompatible or corrupt state shard manifest")
    state = _unpack(folder / "meta.json.gz")
    if not isinstance(state, dict) or state.get("schema") != schema:
        raise ValueError("Invalid state shard metadata")
    for key, buckets in manifest.get("sharded", {}).items():
        if not KEY_PATTERN.fullmatch(key) or not isinstance(buckets, list):
            raise ValueError("Unsafe state shard name")
        dest = {}
        for bucket in buckets:
            if not isinstance(bucket, str) or not re.fullmatch(r"[0-9a-f]{2}", bucket):
                raise ValueError("Invalid state bucket")
            if int(bucket, 16) >= BUCKET_COUNT:
                raise ValueError("Out-of-range state bucket")
            file = folder / "records" / key / (bucket + ".json.gz")
            records = _unpack(file)
            if not isinstance(records, dict):
                raise ValueError("Invalid state bucket records")
            if dest.keys() & records.keys():
                raise ValueError("Duplicate official record across buckets")
            for record_key in records:
                if _bucket(record_key) != bucket:
                    raise ValueError("State record is in wrong bucket")
            dest.update(records)
        if key in state:
            raise ValueError("Duplicated state key between metadata and shards")
        state[key] = dest
    return state


def save_shards(state_path: Path, state: dict, schema: str) -> dict:
    """Write a new full *logical* snapshot as deterministic small git blobs.

    The manifest is replaced last; if a failure occurs before that, the
    existing state still loads. Obsolete buckets are cleaned up after commit
    metadata is complete; an old flat JSON is removed only after success.
    """
    if state.get("schema") != schema:
        raise ValueError("Cannot persist state with wrong schema")
    folder = shard_dir(state_path)
    sharded = {}
    metadata = {}
    expected_paths = set()
    for key, value in state.items():
        if (isinstance(value, dict) and KEY_PATTERN.fullmatch(key)
                and len(json.dumps(value, ensure_ascii=False,
                                   separators=(",", ":")).encode("utf-8"))
                >= SHARD_THRESHOLD_BYTES):
            grouped = {}
            for record_key, record in value.items():
                if not isinstance(record_key, str):
                    raise ValueError("State dictionary contains nonstring key")
                bucket = _bucket(record_key)
                grouped.setdefault(bucket, {})[record_key] = record
            sharded[key] = sorted(grouped)
            for bucket, records in grouped.items():
                file = folder / "records" / key / (bucket + ".json.gz")
                encoded = _compressed_json(records)
                if len(encoded) >= 90_000_000:
                    raise ValueError("State shard too large for GitHub")
                _save_unchanged_aware(file, encoded)
                expected_paths.add(file)
        else:
            metadata[key] = value
    meta = folder / "meta.json.gz"
    _save_unchanged_aware(meta, _compressed_json(metadata))
    manifest = folder / "manifest.json"
    payload = {
        "schema": schema, "version": STORAGE_VERSION,
        "bucket_count": BUCKET_COUNT, "sharded": sharded,
    }
    _save_unchanged_aware(
        manifest, (json.dumps(payload, ensure_ascii=False,
                              sort_keys=True, indent=2) + "\n").encode("utf-8"))
    # Delete only buckets that are not referenced by the newly saved manifest.
    store = folder / "records"
    if store.is_dir():
        for file in store.glob("*/*.json.gz"):
            if file not in expected_paths:
                file.unlink()
        for directory in store.iterdir():
            if directory.is_dir() and not any(directory.iterdir()):
                directory.rmdir()
    # Migration: remove old >100 MB tracked JSON only once sharded state
    # has been committed to the local working tree successfully.
    if state_path.exists():
        state_path.unlink()
    return {
        "sharded_fields": len(sharded),
        "shard_files": len(expected_paths),
        "metadata_fields": len(metadata),
    }
