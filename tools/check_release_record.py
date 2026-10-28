"""Validate a redacted release record; never deploy or connect to a database."""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit

SCHEMA = {
    "record_id": str,
    "status": str,
    "recorded_at": str,
    "operator": str,
    "issue_url": str,
    "pr_url": str,
    "authorization_refs": {"implementation": str, "merge": str, "production": str},
    "source": {
        "repository": str,
        "branch": str,
        "commit": str,
        "business_commit": str,
        "governance_commit": str,
        "ci_runs": [{"url": str, "conclusion": str}],
    },
    "build": {"id": str, "context": str, "dockerfile": str, "base_image": str, "image": str},
    "target": {
        "environment_ref": str,
        "service_ref": str,
        "tracking_branch": str,
        "version": str,
        "traffic_percent": int,
        "port": int,
        "startup": str,
        "probes": {"liveness": str, "readiness": str},
    },
    "config": {
        "revision": str,
        "backup_ref": str,
        "environment_keys": [str],
        "secret_version_refs": [str],
    },
    "database": {
        "before": str,
        "after": str,
        "schema_evidence_ref": str,
        "backup_ref": str,
        "restore_drill_ref": str,
        "candidate_compatibility": str,
        "rollback_compatibility": str,
    },
    "rollback": {
        "image": str,
        "commit": str,
        "config_revision": str,
        "trigger": str,
        "procedure_ref": str,
        "validation_ref": str,
        "owner": str,
    },
    "blockers": [str],
}
SHA = re.compile(r"[0-9a-f]{40}")
IMAGE = re.compile(r"[^\s@]+@sha256:[0-9a-f]{64}")
UNKNOWN = {"unknown", "pending", "todo", "tbd", "n/a", "none", "null"}


def _shape(value, schema, path, errors):
    if isinstance(schema, dict):
        if not isinstance(value, dict):
            errors.append(f"{path}: expected object")
            return
        if value.keys() != schema.keys():
            errors.append(f"{path}: missing or unexpected fields (secret values are not allowed)")
        for key in schema.keys() & value.keys():
            _shape(value[key], schema[key], f"{path}.{key}", errors)
    elif isinstance(schema, list):
        if not isinstance(value, list):
            errors.append(f"{path}: expected array")
        else:
            for index, item in enumerate(value):
                _shape(item, schema[0], f"{path}[{index}]", errors)
    elif type(value) is not schema:
        errors.append(f"{path}: expected {schema.__name__}")
    elif schema is str:
        if not value.strip():
            errors.append(f"{path}: empty string; use unknown in a draft")
        if "://" in value:
            parsed = urlsplit(value)
            if parsed.username is not None or parsed.password is not None:
                errors.append(f"{path}: embedded credentials are forbidden")


def _leaves(value, path="record"):
    if isinstance(value, dict):
        for key, item in value.items():
            yield from _leaves(item, f"{path}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from _leaves(item, f"{path}[{index}]")
    else:
        yield path, value


def validate(record, *, require_ready=False):
    errors = []
    _shape(record, SCHEMA, "record", errors)
    if errors:
        return errors
    status = record["status"]
    if status not in {"draft", "verified", "deployed", "rolled_back"}:
        errors.append("record.status: invalid lifecycle state")
    ready = status in {"verified", "deployed", "rolled_back"}
    if require_ready and not ready:
        errors.append("record.status: draft is not release-ready")
    for path, value in _leaves(record):
        unknown = isinstance(value, str) and value.strip().casefold() in UNKNOWN
        if ready and unknown:
            errors.append(f"{path}: unresolved value")
    for field in ("commit", "business_commit", "governance_commit"):
        value = record["source"][field]
        if value != "unknown" and not SHA.fullmatch(value):
            errors.append(f"source.{field}: expected full lowercase commit SHA")
    value = record["rollback"]["commit"]
    if value != "unknown" and not SHA.fullmatch(value):
        errors.append("rollback.commit: expected full lowercase commit SHA")
    for label, value in (
        ("build.image", record["build"]["image"]),
        ("build.base_image", record["build"]["base_image"]),
        ("rollback.image", record["rollback"]["image"]),
    ):
        if value != "unknown" and not IMAGE.fullmatch(value):
            errors.append(f"{label}: image must be pinned by sha256 digest")
    if not 1 <= record["target"]["port"] <= 65535:
        errors.append("target.port: invalid port")
    if not 0 <= record["target"]["traffic_percent"] <= 100:
        errors.append("target.traffic_percent: invalid percentage")
    if record["recorded_at"] != "unknown":
        try:
            if datetime.fromisoformat(record["recorded_at"]).utcoffset() is None:
                raise ValueError
        except ValueError:
            errors.append("recorded_at: expected ISO timestamp with timezone")
    for key in ("candidate_compatibility", "rollback_compatibility"):
        if record["database"][key] not in {"unknown", "compatible", "incompatible"}:
            errors.append(f"database.{key}: invalid compatibility result")
        if ready and record["database"][key] != "compatible":
            errors.append(f"database.{key}: compatible evidence is required")
    for label, value in (
        ("issue_url", record["issue_url"]),
        ("pr_url", record["pr_url"]),
        *((f"ci_runs[{i}]", item["url"]) for i, item in enumerate(record["source"]["ci_runs"])),
    ):
        if value != "unknown" and not value.startswith("https://github.com/"):
            errors.append(f"{label}: expected a GitHub HTTPS evidence URL")
    if ready:
        if record["blockers"]:
            errors.append("blockers: unresolved blockers prevent release")
        for key, value in record["authorization_refs"].items():
            if value.strip().casefold() in UNKNOWN:
                errors.append(f"authorization_refs.{key}: authorization evidence is required")
        for path, value in (
            ("source.ci_runs", record["source"]["ci_runs"]),
            ("config.environment_keys", record["config"]["environment_keys"]),
            ("config.secret_version_refs", record["config"]["secret_version_refs"]),
        ):
            if not value:
                errors.append(f"{path}: evidence cannot be empty")
        if any(item["conclusion"] != "success" for item in record["source"]["ci_runs"]):
            errors.append("source.ci_runs: all referenced required checks must pass")
    return errors


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON field")
        result[key] = value
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("record", type=Path)
    parser.add_argument("--require-ready", action="store_true")
    args = parser.parse_args()
    try:
        record = json.loads(
            args.record.read_text(encoding="utf-8-sig"), object_pairs_hook=unique_object
        )
        errors = validate(record, require_ready=args.require_ready)
    except (OSError, ValueError) as error:
        # Do not echo the record, parser context or credential-bearing values.
        print(f"Invalid release record: {type(error).__name__}")
        return 1
    for error in errors:
        print(error)
    if not errors:
        print(f"Valid {record['status']} record (structural check only; no authorization granted).")
    return int(bool(errors))


if __name__ == "__main__":
    raise SystemExit(main())
