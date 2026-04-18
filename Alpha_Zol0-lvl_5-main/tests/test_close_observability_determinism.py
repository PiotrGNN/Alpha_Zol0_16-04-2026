from core.BotCore import _compute_lifecycle_ownership_flags


def test_lifecycle_flags_mark_deterministic_for_known_reason_owner():
    flags = _compute_lifecycle_ownership_flags(
        "post_green_protective_exit",
        "post_green_protection_exit",
    )

    assert flags["exit_reason_deterministic"] is True
    assert flags["exit_owner_deterministic"] is True
    assert flags["lifecycle_ownership_reason_codes"] == []
    assert flags["lifecycle_ownership_deterministic"] is True
    assert flags["lifecycle_ownership_state"] == "deterministic"


def test_lifecycle_flags_mark_review_when_unclassified():
    flags = _compute_lifecycle_ownership_flags(
        "close_reason_unclassified",
        "unclassified_exit_owner",
    )

    assert flags["exit_reason_deterministic"] is False
    assert flags["exit_owner_deterministic"] is False
    assert flags["lifecycle_ownership_reason_codes"] == [
        "close_reason_unclassified",
        "unclassified_exit_owner",
    ]
    assert flags["lifecycle_ownership_deterministic"] is False
    assert flags["lifecycle_ownership_state"] == "requires_review"


def test_lifecycle_flags_capture_single_axis_review_reason():
    flags = _compute_lifecycle_ownership_flags(
        "post_green_protective_exit",
        "unclassified_exit_owner",
    )

    assert flags["exit_reason_deterministic"] is True
    assert flags["exit_owner_deterministic"] is False
    assert flags["lifecycle_ownership_reason_codes"] == [
        "unclassified_exit_owner",
    ]
    assert flags["lifecycle_ownership_state"] == "requires_review"
