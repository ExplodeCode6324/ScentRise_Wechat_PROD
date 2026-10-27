"""Validate the documentation-only governance change without production access."""
from pathlib import Path

root = Path(__file__).resolve().parents[1]
agents = (root / "AGENTS.md").read_text(encoding="utf-8-sig")
plan = (root / "docs/deployment/fix_治理流程与接管审计_20261028.md").read_text(encoding="utf-8-sig")
for required in ("Master", "Issue", "docs/deployment/", "CI", "PR", "明确授权", "自动合并"):
    assert required in agents, f"Missing workflow requirement: {required}"
assert "https://github.com/ExplodeCode6324/ScentRise_Wechat_PROD/issues/1" in plan
assert "验证" in plan and "回退" in plan
print("Governance instructions, issue link, validation and rollback checks passed.")
