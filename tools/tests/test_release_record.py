"""Release admission regressions, independent of the application/database fixtures."""

import copy
import importlib.util
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    "record_validator", ROOT / "tools/check_release_record.py"
)
validator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(validator)


class ReleaseRecordTests(unittest.TestCase):
    def setUp(self):
        self.record = json.loads(
            (ROOT / "docs/deployment/release-record.template.json").read_text(encoding="utf-8")
        )

    def ready_record(self):
        def complete(value):
            if isinstance(value, dict):
                return {key: complete(item) for key, item in value.items()}
            if isinstance(value, list):
                return [complete(item) for item in value]
            return "evidence:synthetic-test-only" if value == "unknown" else value

        record = complete(copy.deepcopy(self.record))
        record["status"] = "verified"
        record["recorded_at"] = "2026-10-28T12:00:00+08:00"
        record["pr_url"] = record["issue_url"].replace("issues/4", "pull/999")
        record["source"]["commit"] = "a" * 40
        record["source"]["ci_runs"] = [
            {
                "url": record["source"]["repository"] + "/actions/runs/1",
                "conclusion": "success",
            }
        ]
        for obj, field in (
            (record["build"], "image"),
            (record["build"], "base_image"),
            (record["rollback"], "image"),
        ):
            obj[field] = "example.invalid/test@sha256:" + "b" * 64
        record["rollback"]["commit"] = "c" * 40
        record["database"]["candidate_compatibility"] = "compatible"
        record["database"]["rollback_compatibility"] = "compatible"
        record["blockers"] = []
        return record

    def test_draft_is_valid_but_not_admitted(self):
        self.assertEqual(validator.validate(self.record), [])
        self.assertTrue(validator.validate(self.record, require_ready=True))

    def test_completed_synthetic_record_is_admitted(self):
        self.assertEqual(validator.validate(self.ready_record(), require_ready=True), [])

    def test_verified_template_is_rejected(self):
        self.record["status"] = "verified"
        self.assertTrue(validator.validate(self.record))

    def test_missing_digest_and_short_commit_are_rejected(self):
        for section, field, value in (
            ("build", "image", "example.invalid/test:latest"),
            ("rollback", "commit", "6609c38"),
            ("source", "commit", "master"),
        ):
            with self.subTest(section=section, field=field):
                record = self.ready_record()
                record[section][field] = value
                self.assertTrue(validator.validate(record))

    def test_failed_checks_incompatible_schema_and_blockers_are_rejected(self):
        changes = [
            lambda r: r["source"]["ci_runs"][0].update(conclusion="failure"),
            lambda r: r["database"].update(rollback_compatibility="incompatible"),
            lambda r: r.update(blockers=["pending source mapping"]),
            lambda r: r["authorization_refs"].update(production="unknown"),
            lambda r: r["authorization_refs"].update(production=" UNKNOWN "),
            lambda r: r["source"].update(ci_runs=[]),
        ]
        for change in changes:
            record = self.ready_record()
            change(record)
            self.assertTrue(validator.validate(record))

    def test_structure_credentials_and_wrong_types_are_rejected(self):
        records = []
        missing = copy.deepcopy(self.record)
        del missing["rollback"]
        records.append(missing)
        secret = copy.deepcopy(self.record)
        secret["config"]["JWT_SECRET"] = "test-only-do-not-store"
        records.append(secret)
        credentials = copy.deepcopy(self.record)
        credentials["config"]["backup_ref"] = "https://user:password@example.invalid"
        records.append(credentials)
        wrong_type = copy.deepcopy(self.record)
        wrong_type["target"]["traffic_percent"] = True
        records.append(wrong_type)
        records.extend([[], None])
        for record in records:
            self.assertTrue(validator.validate(record))

    def test_duplicate_json_fields_are_rejected(self):
        with self.assertRaises(ValueError):
            json.loads(
                '{"status":"draft","status":"verified"}', object_pairs_hook=validator.unique_object
            )


if __name__ == "__main__":
    unittest.main()
