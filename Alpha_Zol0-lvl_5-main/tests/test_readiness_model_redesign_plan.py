import json

from scripts.readiness_model_redesign_plan import _build_report


def test_redesign_plan_classification(tmp_path):
    audit_path = tmp_path / "readiness_mismatch.json"
    audit_path.write_text(json.dumps({}), encoding="utf-8")
    report = _build_report(audit_path)
    assert report["final_recommendation"] == "REDESIGN_REQUIRED_AND_FEASIBLE"
    assert "canonical_fields" in report["canonical_bucket_identity_proposal"]
