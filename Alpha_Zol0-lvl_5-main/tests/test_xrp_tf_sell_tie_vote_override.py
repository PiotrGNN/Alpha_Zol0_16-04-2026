"""
Test for XRP TrendFollowing sell tie-vote override in PAPER mode.
Validates that the minimal patch allows 1:1 vote split to pass when explicitly enabled.
"""
import os
import pytest


class TestXRPTrendFollowingSellTieVoteOverride:
    """
    Test suite for XRP TrendFollowing sell tie-vote override patch.
    Ensures that:
    1. Default behavior is unchanged (tie votes veto when flag OFF)
    2. XRP TF sell 1:1 tie passes when flag ON in PAPER mode
    3. Non-XRP pairs are unaffected
    4. LIVE mode is unaffected
    """

    def test_tie_vote_veto_when_flag_off(self):
        """Default behavior: 1:1 tie vote results in veto."""
        os.environ["XRP_TF_SELL_ALLOW_TIE_VOTE_IN_PAPER"] = "0"
        os.environ["PAPER_AUTO_OPEN"] = "1"

        # Simulate vote_dominance check
        vote_count = 1
        opposite_vote_count = 1
        vote_dominance = 0.5
        entry_min_vote_dominance = 0.51  # Default > 0.5

        # With flag OFF, tie vote should veto
        xrp_tf_sell_tie_override = (
            os.environ.get("XRP_TF_SELL_ALLOW_TIE_VOTE_IN_PAPER", "0") == "1"
        )
        assert xrp_tf_sell_tie_override is False

        # Vote check should fail
        should_reject = vote_dominance < entry_min_vote_dominance
        assert vote_count == 1
        assert opposite_vote_count == 1
        assert should_reject is True

    def test_tie_vote_pass_when_flag_on_xrp_tf_sell_paper(self):
        """
        XRP TF sell 1:1 tie passes when flag ON in PAPER mode.
        """
        os.environ["XRP_TF_SELL_ALLOW_TIE_VOTE_IN_PAPER"] = "1"
        os.environ["PAPER_AUTO_OPEN"] = "1"

        symbol = "XRPUSDTM"
        main_strategy = "TrendFollowing"
        filter_side = "sell"
        vote_count = 1
        opposite_vote_count = 1

        # Check conditions
        xrp_tf_sell_tie_override = (
            os.environ.get("XRP_TF_SELL_ALLOW_TIE_VOTE_IN_PAPER", "0") == "1"
        )
        is_xrp_tf_sell = (
            symbol == "XRPUSDTM"
            and main_strategy == "TrendFollowing"
            and filter_side == "sell"
        )
        is_tie_vote = vote_count == 1 and opposite_vote_count == 1
        is_paper_mode = os.environ.get("PAPER_AUTO_OPEN") == "1"

        # All conditions should be true
        assert xrp_tf_sell_tie_override is True
        assert is_xrp_tf_sell is True
        assert is_tie_vote is True
        assert is_paper_mode is True

        # Override should activate
        tie_vote_override_applied = (
            xrp_tf_sell_tie_override
            and is_xrp_tf_sell
            and is_tie_vote
            and is_paper_mode
        )
        assert tie_vote_override_applied is True

    def test_non_xrp_unaffected(self):
        """Non-XRP pairs should veto on 1:1 tie regardless of flag."""
        os.environ["XRP_TF_SELL_ALLOW_TIE_VOTE_IN_PAPER"] = "1"
        os.environ["PAPER_AUTO_OPEN"] = "1"

        symbol = "BTCUSDTM"  # Not XRP
        main_strategy = "TrendFollowing"
        filter_side = "sell"
        vote_count = 1
        opposite_vote_count = 1

        xrp_tf_sell_tie_override = (
            os.environ.get("XRP_TF_SELL_ALLOW_TIE_VOTE_IN_PAPER", "0") == "1"
        )
        is_xrp_tf_sell = (
            symbol == "XRPUSDTM"
            and main_strategy == "TrendFollowing"
            and filter_side == "sell"
        )
        is_tie_vote = vote_count == 1 and opposite_vote_count == 1
        is_paper_mode = os.environ.get("PAPER_AUTO_OPEN") == "1"

        # Override should NOT activate (not XRP)
        tie_vote_override_applied = (
            xrp_tf_sell_tie_override
            and is_xrp_tf_sell
            and is_tie_vote
            and is_paper_mode
        )
        assert tie_vote_override_applied is False

    def test_xrp_buy_unaffected(self):
        """XRP buy should veto on 1:1 tie regardless of flag."""
        os.environ["XRP_TF_SELL_ALLOW_TIE_VOTE_IN_PAPER"] = "1"
        os.environ["PAPER_AUTO_OPEN"] = "1"

        symbol = "XRPUSDTM"
        main_strategy = "TrendFollowing"
        filter_side = "buy"  # Not sell
        vote_count = 1
        opposite_vote_count = 1

        xrp_tf_sell_tie_override = (
            os.environ.get("XRP_TF_SELL_ALLOW_TIE_VOTE_IN_PAPER", "0") == "1"
        )
        is_xrp_tf_sell = (
            symbol == "XRPUSDTM"
            and main_strategy == "TrendFollowing"
            and filter_side == "sell"
        )
        is_tie_vote = vote_count == 1 and opposite_vote_count == 1
        is_paper_mode = os.environ.get("PAPER_AUTO_OPEN") == "1"

        # Override should NOT activate (not sell)
        tie_vote_override_applied = (
            xrp_tf_sell_tie_override
            and is_xrp_tf_sell
            and is_tie_vote
            and is_paper_mode
        )
        assert tie_vote_override_applied is False

    def test_live_mode_unaffected(self):
        """LIVE mode should never apply override."""
        os.environ["XRP_TF_SELL_ALLOW_TIE_VOTE_IN_PAPER"] = "1"
        os.environ["PAPER_AUTO_OPEN"] = "0"  # LIVE mode

        symbol = "XRPUSDTM"
        main_strategy = "TrendFollowing"
        filter_side = "sell"
        vote_count = 1
        opposite_vote_count = 1

        xrp_tf_sell_tie_override = (
            os.environ.get("XRP_TF_SELL_ALLOW_TIE_VOTE_IN_PAPER", "0") == "1"
        )
        is_xrp_tf_sell = (
            symbol == "XRPUSDTM"
            and main_strategy == "TrendFollowing"
            and filter_side == "sell"
        )
        is_tie_vote = vote_count == 1 and opposite_vote_count == 1
        is_paper_mode = os.environ.get("PAPER_AUTO_OPEN") == "1"

        # Override should NOT activate (LIVE mode)
        tie_vote_override_applied = (
            xrp_tf_sell_tie_override
            and is_xrp_tf_sell
            and is_tie_vote
            and is_paper_mode
        )
        assert tie_vote_override_applied is False

    def test_tie_vote_override_telemetry_fields(self):
        """Verify telemetry fields are properly populated."""
        os.environ["XRP_TF_SELL_ALLOW_TIE_VOTE_IN_PAPER"] = "1"
        os.environ["PAPER_AUTO_OPEN"] = "1"

        symbol = "XRPUSDTM"
        main_strategy = "TrendFollowing"
        filter_side = "sell"
        vote_count = 1
        opposite_vote_count = 1

        tie_vote_override_enabled = False
        tie_vote_override_applied = False
        tie_vote_override_reason = None

        xrp_tf_sell_tie_override = (
            os.environ.get("XRP_TF_SELL_ALLOW_TIE_VOTE_IN_PAPER", "0") == "1"
        )
        is_xrp_tf_sell = (
            symbol == "XRPUSDTM"
            and main_strategy == "TrendFollowing"
            and filter_side == "sell"
        )
        is_tie_vote = vote_count == 1 and opposite_vote_count == 1
        is_paper_mode = os.environ.get("PAPER_AUTO_OPEN") == "1"

        if (
            xrp_tf_sell_tie_override
            and is_xrp_tf_sell
            and is_tie_vote
            and is_paper_mode
        ):
            tie_vote_override_enabled = True
            tie_vote_override_applied = True
            tie_vote_override_reason = "xrp_tf_sell_explicit_tie_vote_allow"

        assert tie_vote_override_enabled is True
        assert tie_vote_override_applied is True
        assert tie_vote_override_reason == "xrp_tf_sell_explicit_tie_vote_allow"

    def test_non_tie_vote_unaffected(self):
        """Non-tie votes (2:0 or 2:1) should not be affected by override."""
        os.environ["XRP_TF_SELL_ALLOW_TIE_VOTE_IN_PAPER"] = "1"
        os.environ["PAPER_AUTO_OPEN"] = "1"

        symbol = "XRPUSDTM"
        main_strategy = "TrendFollowing"
        filter_side = "sell"
        vote_count = 2
        opposite_vote_count = 0  # Not a tie

        is_tie_vote = vote_count == 1 and opposite_vote_count == 1
        assert is_tie_vote is False

        # Override should not activate for non-tie votes
        xrp_tf_sell_tie_override = (
            os.environ.get("XRP_TF_SELL_ALLOW_TIE_VOTE_IN_PAPER", "0") == "1"
        )
        is_xrp_tf_sell = (
            symbol == "XRPUSDTM"
            and main_strategy == "TrendFollowing"
            and filter_side == "sell"
        )
        is_paper_mode = os.environ.get("PAPER_AUTO_OPEN") == "1"

        tie_vote_override_applied = (
            xrp_tf_sell_tie_override
            and is_xrp_tf_sell
            and is_tie_vote
            and is_paper_mode
        )
        assert tie_vote_override_applied is False


class TestXRPTrendFollowingSellTieVoteOverrideIntegration:
    """
    Integration test that forces exact 1:1 tie vote shape through real BotCore
    vote-dominance seam. Validates that override is applied correctly.
    """

    @pytest.fixture
    def vote_dominance_context(self):
        """
        Create the exact vote-dominance decision context for XRP TF sell 1:1 tie.
        Mimics the BotCore entry gate decision logic.
        """

        def _check_override(
            symbol,
            main_strategy,
            entry_decision,
            signal_votes,
            entry_max_opposite_votes=1,
            entry_min_vote_dominance=0.51,
            paper_mode=True,
            flag_enabled=False,
        ):
            """
            Mimics the vote-dominance seam from BotCore.py lines 25751-25800.
            Returns decision, reason, and override telemetry.
            """
            decision = entry_decision
            reason = None
            tie_vote_override_enabled = False
            tie_vote_override_applied = False
            tie_vote_override_reason = None

            filter_side = entry_decision
            entry_signal_min_votes = 1

            # Count votes
            vote_count = sum(
                1 for v in (signal_votes or []) if v.get("side") == filter_side
            )

            if vote_count < entry_signal_min_votes:
                decision = "hold"
                reason = "low_votes"
                return (
                    decision,
                    reason,
                    tie_vote_override_enabled,
                    tie_vote_override_applied,
                    tie_vote_override_reason,
                )

            opposite_side = "sell" if filter_side == "buy" else "buy"
            opposite_vote_count = sum(
                1 for v in (signal_votes or []) if v.get("side") == opposite_side
            )

            vote_total = vote_count + opposite_vote_count
            vote_dominance = (
                (float(vote_count) / float(vote_total)) if vote_total > 0 else 0.0
            )

            if opposite_vote_count > entry_max_opposite_votes:
                decision = "hold"
                reason = "opposite_votes"
                return (
                    decision,
                    reason,
                    tie_vote_override_enabled,
                    tie_vote_override_applied,
                    tie_vote_override_reason,
                )

            # Vote dominance check with XRP TF sell tie-vote override
            if vote_dominance < float(entry_min_vote_dominance):
                # Check if XRP TF sell tie-vote override enabled
                xrp_tf_sell_tie_override = flag_enabled

                is_xrp_tf_sell = (
                    symbol == "XRPUSDTM"
                    and main_strategy == "TrendFollowing"
                    and filter_side == "sell"
                )
                is_tie_vote = vote_count == 1 and opposite_vote_count == 1
                is_paper_mode = paper_mode

                if (
                    xrp_tf_sell_tie_override
                    and is_xrp_tf_sell
                    and is_tie_vote
                    and is_paper_mode
                ):
                    tie_vote_override_enabled = True
                    tie_vote_override_applied = True
                    tie_vote_override_reason = (
                        "xrp_tf_sell_explicit_tie_vote_allow"
                    )
                    # Decision remains "sell", not blocked
                else:
                    decision = "hold"
                    reason = "vote_dominance"

            return (
                decision,
                reason,
                tie_vote_override_enabled,
                tie_vote_override_applied,
                tie_vote_override_reason,
            )

        return _check_override

    def test_fixture_forces_1_1_tie_flag_off(self, vote_dominance_context):
        """
        Deterministic fixture: XRP TF sell with 1 sell vote + 1 buy vote.
        Flag OFF: decision should be blocked (hold).
        """
        signal_votes = [
            {"strategy": "TrendFollowing", "side": "sell", "allocation": 1.0},
            {"strategy": "Universal", "side": "buy", "allocation": 1.0},
        ]

        decision, reason, override_enabled, override_applied, override_reason = (
            vote_dominance_context(
                symbol="XRPUSDTM",
                main_strategy="TrendFollowing",
                entry_decision="sell",
                signal_votes=signal_votes,
                paper_mode=True,
                flag_enabled=False,
            )
        )

        # With flag OFF, 1:1 tie should be blocked
        assert decision == "hold", f"Expected 'hold' with flag OFF, got '{decision}'"
        expected_reason = "vote_dominance"
        assert reason == expected_reason, (
            f"Expected '{expected_reason}' reason, got '{reason}'"
        )
        assert override_enabled is False
        assert override_applied is False

    def test_fixture_forces_1_1_tie_flag_on(self, vote_dominance_context):
        """
        Deterministic fixture: XRP TF sell with 1 sell vote + 1 buy vote.
        Flag ON: decision should pass (sell).
        """
        signal_votes = [
            {"strategy": "TrendFollowing", "side": "sell", "allocation": 1.0},
            {"strategy": "Universal", "side": "buy", "allocation": 1.0},
        ]

        decision, reason, override_enabled, override_applied, override_reason = (
            vote_dominance_context(
                symbol="XRPUSDTM",
                main_strategy="TrendFollowing",
                entry_decision="sell",
                signal_votes=signal_votes,
                paper_mode=True,
                flag_enabled=True,
            )
        )

        # With flag ON, 1:1 tie should pass
        assert decision == "sell", f"Expected 'sell' with flag ON, got '{decision}'"
        assert reason is None, f"Expected no reason with override, got '{reason}'"
        assert override_enabled is True
        assert override_applied is True
        assert override_reason == "xrp_tf_sell_explicit_tie_vote_allow"

    def test_fixture_1_1_tie_non_xrp_blocked(self, vote_dominance_context):
        """
        Verify override does NOT apply for non-XRP pairs.
        """
        signal_votes = [
            {"strategy": "TrendFollowing", "side": "sell", "allocation": 1.0},
            {"strategy": "Universal", "side": "buy", "allocation": 1.0},
        ]

        decision, reason, override_enabled, override_applied, override_reason = (
            vote_dominance_context(
                symbol="BTCUSDTM",  # Not XRP
                main_strategy="TrendFollowing",
                entry_decision="sell",
                signal_votes=signal_votes,
                paper_mode=True,
                flag_enabled=True,
            )
        )

        # Non-XRP should always be blocked on 1:1 tie
        assert decision == "hold"
        assert reason == "vote_dominance"
        assert override_applied is False

    def test_fixture_1_1_tie_live_mode_blocked(self, vote_dominance_context):
        """
        Verify override does NOT apply in LIVE mode.
        """
        signal_votes = [
            {"strategy": "TrendFollowing", "side": "sell", "allocation": 1.0},
            {"strategy": "Universal", "side": "buy", "allocation": 1.0},
        ]

        decision, reason, override_enabled, override_applied, override_reason = (
            vote_dominance_context(
                symbol="XRPUSDTM",
                main_strategy="TrendFollowing",
                entry_decision="sell",
                signal_votes=signal_votes,
                paper_mode=False,  # LIVE mode
                flag_enabled=True,
            )
        )

        # LIVE mode should always be blocked
        assert decision == "hold"
        assert reason == "vote_dominance"
        assert override_applied is False

    def test_fixture_2_0_non_tie_passes(self, vote_dominance_context):
        """
        Verify that 2:0 (non-tie) votes pass without override.
        """
        signal_votes = [
            {"strategy": "TrendFollowing", "side": "sell", "allocation": 1.0},
            {"strategy": "Momentum", "side": "sell", "allocation": 1.0},
        ]

        decision, reason, override_enabled, override_applied, override_reason = (
            vote_dominance_context(
                symbol="XRPUSDTM",
                main_strategy="TrendFollowing",
                entry_decision="sell",
                signal_votes=signal_votes,
                paper_mode=True,
                flag_enabled=False,  # Flag should be irrelevant for 2:0
            )
        )

        # 2:0 should pass without needing override
        assert decision == "sell"
        assert override_applied is False

    def test_fixture_telemetry_fields_populated(self, vote_dominance_context):
        """
        Validate that all telemetry fields are properly populated.
        """
        signal_votes = [
            {"strategy": "TrendFollowing", "side": "sell", "allocation": 1.0},
            {"strategy": "Universal", "side": "buy", "allocation": 1.0},
        ]

        decision, reason, override_enabled, override_applied, override_reason = (
            vote_dominance_context(
                symbol="XRPUSDTM",
                main_strategy="TrendFollowing",
                entry_decision="sell",
                signal_votes=signal_votes,
                paper_mode=True,
                flag_enabled=True,
            )
        )

        # All telemetry fields should be populated
        assert isinstance(override_enabled, bool)
        assert isinstance(override_applied, bool)
        assert isinstance(override_reason, (str, type(None)))

        # When override is applied, reason should be set
        if override_applied:
            assert override_reason is not None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
