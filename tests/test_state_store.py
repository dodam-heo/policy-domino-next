"""Regression tests for the previously blocked 100 MB GitHub state ledger."""
from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from policy_domino.core import SCHEMA, load_state, new_state, write_json
from policy_domino.state_store import has_shards, save_shards, shard_dir


class ShardedStateTests(unittest.TestCase):
    def test_migrate_old_state_without_dropping_any_official_records(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "data" / "state.json"
            state = new_state()
            state["documents"] = {
                f"document-{i:04}": {
                    "id": f"document-{i:04}",
                    "title": "공식 법령 이름 " + str(i),
                    "source": "admrul",
                    "law_type": "고시" if i%2 else "행정규칙",
                    "text": "공식 원문 " + ("공공기관 법적 근거 " * 25)
                } for i in range(240)
            }
            state["versions"] = {k: {"official": dict(v)}
                                 for k,v in state["documents"].items()}
            state["public_services"] = {f"service-{i}":{
                "agency":"공식 기관", "name":"정부24 서비스 "+str(i),
                "criterion":"기준 중위소득 " * 40}
                for i in range(80)}
            state["ai_run"] = {"status":"partial_generated","generated":21}
            state["backfill_end_dates"] = {"admrul|2|3": "2026-07-01"}
            write_json(path,state)
            self.assertTrue(path.exists())
            report=save_shards(path,state,SCHEMA)
            self.assertGreater(report["shard_files"],1)
            self.assertTrue(has_shards(path))
            self.assertFalse(path.exists(), "old giant JSON must not be committed again")
            actual=load_state(path)
            self.assertEqual(actual,state)
            self.assertEqual(len(actual["documents"]),240)
            self.assertEqual(actual["backfill_end_dates"],state["backfill_end_dates"])
            self.assertEqual(actual["public_services"],state["public_services"])

    def test_unchanged_buckets_are_not_rewritten(self):
        with tempfile.TemporaryDirectory() as root:
            path=Path(root)/"data"/"state.json"
            state=new_state()
            state["documents"]={
                f"doc-{i:04}": {"id": f"doc-{i:04}", "text": "X" * 1000}
                for i in range(240)}
            save_shards(path,state,SCHEMA)
            folder=shard_dir(path)
            before={str(f.relative_to(folder)):
                    hashlib.sha256(f.read_bytes()).hexdigest()
                    for f in folder.rglob("*") if f.is_file()}
            save_shards(path,state,SCHEMA)
            after={str(f.relative_to(folder)):
                   hashlib.sha256(f.read_bytes()).hexdigest()
                   for f in folder.rglob("*") if f.is_file()}
            self.assertEqual(after,before)
            # A single changed source should not modify all the record buckets.
            state["documents"]["doc-0007"]["text"]="Y" * 1000
            save_shards(path,state,SCHEMA)
            last={str(f.relative_to(folder)):
                  hashlib.sha256(f.read_bytes()).hexdigest()
                  for f in folder.rglob("*") if f.is_file()}
            changed=[file for file in before if before[file]!=last[file]]
            self.assertEqual(len(changed),1,changed)
            self.assertEqual(load_state(path)["documents"]["doc-0007"]["text"],
                             "Y" * 1000)

    def test_corrupted_or_unavailable_shards_never_silently_reset_state(self):
        with tempfile.TemporaryDirectory() as root:
            path=Path(root)/"data"/"state.json"
            state=new_state()
            state["documents"]={str(i):{"text":"K" * 1000} for i in range(200)}
            save_shards(path,state,SCHEMA)
            file=next((shard_dir(path)/"records").glob("*/*.json.gz"))
            file.unlink()
            with self.assertRaises((OSError, FileNotFoundError)):
                load_state(path)

    def test_invalid_schema_is_rejected(self):
        with tempfile.TemporaryDirectory() as root:
            path=Path(root)/"data"/"state.json"
            state=new_state()
            save_shards(path,state,SCHEMA)
            manifest=shard_dir(path)/"manifest.json"
            raw=json.loads(manifest.read_text(encoding="utf8"))
            raw["schema"]="incorrect"
            manifest.write_text(json.dumps(raw),encoding="utf8")
            with self.assertRaisesRegex(ValueError,"manifest"):
                load_state(path)


if __name__ == "__main__":
    unittest.main()
