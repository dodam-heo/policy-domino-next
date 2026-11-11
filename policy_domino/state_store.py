"""Lossless, incremental content-addressed canonical source ledger.

The logical API used by collection and analysis remains unchanged:
load_state() returns full official version/clauses objects. Physical storage
deduplicates equal verified clause objects across document versions; immutable
new content packs are added only when new clause content is observed.

Existing v1 64-bucket ledgers are readable and migrate on the next save.
The v2 manifest is written last, after all content and record buckets.
"""
from __future__ import annotations

import copy
import gzip
import hashlib
import io
import json
import re
from pathlib import Path

STORAGE_VERSION = 2
BUCKET_COUNT = 64
SHARD_THRESHOLD_BYTES = 100_000
PACK_TARGET_BYTES = 400_000
KEY_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")
CLAUSE_REF = "$clause_ref"


def _json_bytes(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":")).encode("utf-8")


def _fingerprint(value: object) -> str:
    return hashlib.sha256(_json_bytes(value)).hexdigest()


def _compressed_json(value: object) -> bytes:
    output = io.BytesIO()
    with gzip.GzipFile(fileobj=output, mode="wb", compresslevel=6,
                       mtime=0, filename="") as gz:
        gz.write(_json_bytes(value))
    return output.getvalue()


def _unpack(path: Path):
    return json.loads(gzip.decompress(path.read_bytes()).decode("utf-8"))


def _save_unchanged_aware(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.read_bytes() == content:
        return
    pending = path.with_suffix(path.suffix + ".tmp")
    pending.write_bytes(content)
    pending.replace(path)


def _bucket(key: str) -> str:
    hashed = hashlib.sha256(key.encode("utf-8")).digest()
    return f"{int.from_bytes(hashed[:2], 'big') % BUCKET_COUNT:02x}"


def shard_dir(state_path: Path) -> Path:
    return state_path.parent / state_path.stem


def has_shards(state_path: Path) -> bool:
    return (shard_dir(state_path) / "manifest.json").is_file()


def _read_manifest(folder: Path, schema: str) -> dict:
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("version") not in (1, STORAGE_VERSION) or manifest.get("schema") != schema:
        raise ValueError("Incompatible or corrupt state shard manifest")
    return manifest


def _read_packs(folder: Path, manifest: dict) -> dict:
    """Verify immutable compressed pack hashes and their content addresses."""
    blocks = {}
    names = manifest.get("content_packs", [])
    if not isinstance(names, list) or len(set(names)) != len(names):
        raise ValueError("Invalid immutable content pack manifest")
    for name in names:
        if not isinstance(name, str) or not re.fullmatch(r"[0-9a-f]{40}", name):
            raise ValueError("Unsafe content pack identity")
        file = folder / "content" / (name + ".json.gz")
        payload = file.read_bytes()
        if hashlib.sha256(payload).hexdigest()[:40] != name:
            raise ValueError("Official content pack digest mismatch")
        rows = json.loads(gzip.decompress(payload).decode("utf-8"))
        if not isinstance(rows, dict):
            raise ValueError("Invalid content-addressed pack")
        for digest, body in rows.items():
            if not re.fullmatch(r"[0-9a-f]{64}", digest):
                raise ValueError("Invalid official clause fingerprint")
            if _fingerprint(body) != digest or digest in blocks:
                raise ValueError("Corrupt or duplicated official clause content")
            blocks[digest] = body
    return blocks


def load_shards(state_path: Path, schema: str) -> dict:
    folder = shard_dir(state_path)
    manifest = _read_manifest(folder, schema)
    v2 = manifest["version"] == STORAGE_VERSION
    # Earlier v2 runners may have written the original metadata file while
    # a new source-sync run was already in flight. Accept it exactly once,
    # then migrate to canonical v2 metadata on the next successful save.
    v2_meta = folder / "meta_v2.json.gz"
    meta = v2_meta if v2 and v2_meta.is_file() else folder / "meta.json.gz"
    state = _unpack(meta)
    if not isinstance(state, dict) or state.get("schema") != schema:
        raise ValueError("Invalid state shard metadata")
    records_base = folder / ("records_v2" if v2 else "records")
    for key, buckets in manifest.get("sharded", {}).items():
        if not KEY_PATTERN.fullmatch(key) or not isinstance(buckets, list):
            raise ValueError("Unsafe state shard name")
        dest = {}
        for bucket in buckets:
            if not isinstance(bucket, str) or not re.fullmatch(r"[0-9a-f]{2}", bucket):
                raise ValueError("Invalid state bucket")
            if int(bucket, 16) >= BUCKET_COUNT:
                raise ValueError("Out-of-range state bucket")
            file = records_base / key / (bucket + ".json.gz")
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
    if v2:
        blocks = _read_packs(folder, manifest)
        for version in state.get("versions", {}).values():
            if not isinstance(version, dict) or not isinstance(version.get("clauses"), dict):
                continue
            for key, body in version["clauses"].items():
                if isinstance(body, dict) and set(body) == {CLAUSE_REF}:
                    digest = body[CLAUSE_REF]
                    if digest not in blocks:
                        raise ValueError("Missing immutable official clause: "+str(digest))
                    version["clauses"][key] = copy.deepcopy(blocks[digest])
                elif isinstance(body, dict) and "text" in body:
                    raise ValueError("Undeduplicated clause in v2 record")
        by_text_sha={}
        for body in blocks.values():
            if isinstance(body, dict) and isinstance(body.get("text"), str):
                # Hashes from official extraction are SHA-256 of actual text.
                fingerprint=hashlib.sha256(body["text"].encode("utf-8")).hexdigest()
                by_text_sha[fingerprint]=body["text"]
        for finding in state.get("findings", {}).values():
            if not isinstance(finding, dict):
                continue
            for change in finding.get("changes", []):
                for key in ("before", "after"):
                    ref=change.get(key)
                    if isinstance(ref, dict) and set(ref)=={"$clause_text_ref"}:
                        digest=ref["$clause_text_ref"]
                        if digest not in by_text_sha:
                            raise ValueError("Missing official clause text for "+str(digest))
                        change[key]=by_text_sha[digest]
    return state


def _write_new_packs(folder: Path, new_blocks: dict) -> list[str]:
    """Append immutable packs, never rewrite an existing clause or old pack."""
    added = []
    rows = {}
    row_bytes = 0

    def flush():
        nonlocal rows, row_bytes
        if not rows:
            return
        payload = _compressed_json(rows)
        digest = hashlib.sha256(payload).hexdigest()[:40]
        file = folder / "content" / (digest + ".json.gz")
        if file.exists() and file.read_bytes() != payload:
            raise ValueError("Immutable official content pack was mutated")
        _save_unchanged_aware(file, payload)
        added.append(digest)
        rows = {}
        row_bytes = 0

    for digest, body in sorted(new_blocks.items()):
        size = len(_json_bytes({digest: body}))
        if rows and row_bytes + size > PACK_TARGET_BYTES:
            flush()
        rows[digest] = body
        row_bytes += size
    flush()
    return added


def save_shards(state_path: Path, state: dict, schema: str) -> dict:
    """Persist one complete logical state with incremental immutable clauses.

    Existing v1 files are not mutated before v2 files are written. Version
    references and immutable content packs must exist before manifest switch.
    All other record families retain deterministic 64-bucket snapshots.
    """
    if state.get("schema") != schema:
        raise ValueError("Cannot persist state with wrong schema")
    folder = shard_dir(state_path)
    prior = (_read_manifest(folder, schema) if has_shards(state_path) else {})
    old_packs = prior.get("content_packs", []) if prior.get("version") == STORAGE_VERSION else []
    original_blocks = _read_packs(folder, prior) if old_packs else {}
    known = set(original_blocks)

    stored_state = state.copy()
    versions = state.get("versions", {})
    pending = {}
    if isinstance(versions, dict):
        referenced = {}
        for identity, raw_version in versions.items():
            if not isinstance(raw_version, dict) or not isinstance(raw_version.get("clauses"), dict):
                referenced[identity] = raw_version
                continue
            version = raw_version.copy()
            clauses = {}
            for key, body in raw_version["clauses"].items():
                if isinstance(body, dict) and "text" in body:
                    digest = _fingerprint(body)
                    clauses[key] = {CLAUSE_REF: digest}
                    if digest not in known and digest not in pending:
                        pending[digest] = body
                else:
                    # Do not alter unknown legacy clause formats during migration.
                    clauses[key] = body
            version["clauses"] = clauses
            referenced[identity] = version
        stored_state["versions"] = referenced

    # Findings reference exactly the same official clause texts, not another
    # copy of every before/after article. Fall back to literal strings if an
    # older finding cannot be proven to equal an official stored version.
    by_text_sha = {}
    for block in (*original_blocks.values(), *pending.values()):
        if isinstance(block, dict) and isinstance(block.get("text"), str):
            body = block["text"]
            by_text_sha[hashlib.sha256(body.encode("utf-8")).hexdigest()] = body
    if isinstance(state.get("findings"), dict):
        stored_findings={}
        for identity, raw_finding in state["findings"].items():
            if not isinstance(raw_finding, dict) or not isinstance(raw_finding.get("changes"), list):
                stored_findings[identity]=raw_finding
                continue
            finding=raw_finding.copy()
            changes=[]
            for raw_change in finding["changes"]:
                if not isinstance(raw_change, dict):
                    changes.append(raw_change)
                    continue
                change=raw_change.copy()
                evidence=change.get("evidence") or {}
                for key, proof_key in (("before","old_body_sha256"),
                                       ("after","new_body_sha256")):
                    text=change.get(key)
                    digest=evidence.get(proof_key)
                    if (isinstance(text,str) and isinstance(digest,str) and
                            by_text_sha.get(digest)==text):
                        change[key]={"$clause_text_ref":digest}
                changes.append(change)
            finding["changes"]=changes
            stored_findings[identity]=finding
        stored_state["findings"]=stored_findings

    new_packs = _write_new_packs(folder, pending)
    names = sorted(set(old_packs) | set(new_packs))
    sharded = {}
    metadata = {}
    expected = set()
    records_base = folder / "records_v2"
    for key, value in stored_state.items():
        if (isinstance(value, dict) and KEY_PATTERN.fullmatch(key)
                and len(_json_bytes(value)) >= SHARD_THRESHOLD_BYTES):
            grouped = {}
            for identity, record in value.items():
                if not isinstance(identity, str):
                    raise ValueError("State dictionary contains nonstring key")
                grouped.setdefault(_bucket(identity), {})[identity] = record
            sharded[key] = sorted(grouped)
            for bucket, records in grouped.items():
                file = records_base / key / (bucket + ".json.gz")
                payload = _compressed_json(records)
                if len(payload) >= 90_000_000:
                    raise ValueError("State shard too large for GitHub")
                _save_unchanged_aware(file, payload)
                expected.add(file)
        else:
            metadata[key] = value
    _save_unchanged_aware(folder / "meta_v2.json.gz", _compressed_json(metadata))
    manifest = {
        "schema": schema, "version": STORAGE_VERSION,
        "bucket_count": BUCKET_COUNT, "sharded": sharded,
        "content_packs": names,
    }
    _save_unchanged_aware(
        folder / "manifest.json",
        (json.dumps(manifest, ensure_ascii=False,
                    sort_keys=True, indent=2) + "\n").encode("utf-8"))
    # Clean obsolete mutable record buckets only AFTER v2 manifest exists.
    if records_base.is_dir():
        for file in records_base.glob("*/*.json.gz"):
            if file not in expected:
                file.unlink()
        for directory in records_base.iterdir():
            if directory.is_dir() and not any(directory.iterdir()):
                directory.rmdir()
    legacy = folder / "records"
    if legacy.exists():
        for file in legacy.glob("*/*.json.gz"):
            file.unlink()
        for directory in legacy.iterdir():
            if directory.is_dir() and not any(directory.iterdir()):
                directory.rmdir()
        if not any(legacy.iterdir()):
            legacy.rmdir()
    legacy_meta=folder / "meta.json.gz"
    if legacy_meta.exists():
        legacy_meta.unlink()
    if state_path.exists():
        state_path.unlink()
    return {
        "sharded_fields": len(sharded),
        "shard_files": len(expected),
        "metadata_fields": len(metadata),
        "content_blocks_reused": len(known),
        "content_blocks_added": len(pending),
        "immutable_content_packs_added": len(new_packs),
    }
