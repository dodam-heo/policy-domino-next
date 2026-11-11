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
            file=next((shard_dir(path)/"records_v2").glob("*/*.json.gz"))
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

    def test_unchanged_official_clauses_are_reused_across_versions(self):
        with tempfile.TemporaryDirectory() as root:
            path=Path(root)/"data"/"state.json"
            state=new_state()
            def clause(text):
                return {"text":text,"complete":True,
                        "sha256":hashlib.sha256(text.encode()).hexdigest()}
            common=clause("제1조 공통 원문입니다.")
            old=clause("제2조 종전 기준은 10만원입니다.")
            current=clause("제2조 새로운 기준은 12만원입니다.")
            state["versions"]={
                "version-old":{"clauses":{"제1조":common,"제2조":old},
                               "body_sha256":"old-version"},
                "version-new":{"clauses":{"제1조":common,"제2조":current},
                               "body_sha256":"new-version"},
            }
            save_shards(path,state,SCHEMA)
            folder=shard_dir(path)
            manifest=json.loads((folder/"manifest.json").read_text())
            self.assertEqual(manifest["version"],2)
            packs=list((folder/"content").glob("*.json.gz"))
            import gzip
            blocks={}
            for pack in packs:
                blocks.update(json.loads(gzip.decompress(pack.read_bytes())))
            self.assertEqual(len(blocks),3,
                             "The unchanged first article must have one copy")
            self.assertEqual(load_state(path),state)
            unchanged={file.name:hashlib.sha256(file.read_bytes()).hexdigest()
                       for file in packs}
            snapshot=save_shards(path,state,SCHEMA)
            self.assertEqual(snapshot["content_blocks_added"],0)
            self.assertEqual(unchanged,{f.name:hashlib.sha256(f.read_bytes()).hexdigest()
                                        for f in (folder/"content").glob("*.json.gz")})
            state["versions"]["version-three"]={
                "clauses":{"제1조":common,
                           "제2조":clause("제2조 최신 기준은 13만원입니다.")}}
            update=save_shards(path,state,SCHEMA)
            self.assertEqual(update["content_blocks_added"],1)
            self.assertEqual(load_state(path),state)
            for name,digest in unchanged.items():
                self.assertEqual(hashlib.sha256(
                    (folder/"content"/name).read_bytes()).hexdigest(),digest)

    def test_legacy_v1_shards_upgrade_without_dropping_contents(self):
        from policy_domino.state_store import _compressed_json, _bucket
        with tempfile.TemporaryDirectory() as root:
            path=Path(root)/"data"/"state.json"
            folder=shard_dir(path)
            state=new_state()
            plain={"text":"제3조(기준) 10만원","complete":True,"sha256":"legacy-hash"}
            state["versions"]={"old":{"status":"extracted","clauses":{"제3조":plain}}}
            folder.mkdir(parents=True)
            (folder/"meta.json.gz").write_bytes(_compressed_json(
                {k:v for k,v in state.items() if k!="versions"}))
            bucket=_bucket("old")
            old=folder/"records"/"versions"/(bucket+".json.gz")
            old.parent.mkdir(parents=True)
            old.write_bytes(_compressed_json(state["versions"]))
            (folder/"manifest.json").write_text(json.dumps({
                "version":1,"schema":SCHEMA,"bucket_count":64,
                "sharded":{"versions":[bucket]}}))
            self.assertEqual(load_state(path),state)
            save_shards(path,state,SCHEMA)
            self.assertEqual(load_state(path),state)
            self.assertFalse(old.exists())
            self.assertTrue(list((folder/"content").glob("*.json.gz")))


if __name__ == "__main__":
    unittest.main()
