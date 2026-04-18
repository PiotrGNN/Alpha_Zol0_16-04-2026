from scripts.readiness_model_redesign_plan import _build_report


def test_redesign_plan_classification():
    report = _build_report(
        __import__("pathlib").Path("artifacts/diagnostics/readiness_architecture_mismatch_audit_20260328_075242.json")
    )
    assert report["final_recommendation"] == "REDESIGN_REQUIRED_AND_FEASIBLE"
    assert "canonical_fields" in report["canonical_bucket_identity_proposal"]

