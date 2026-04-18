import inspect
import logging
import os


# PositionManager.py – Śledzenie pozycji


class PositionManager:
    def __init__(self, portfolio_nft=None):
        # Keep both a list (for sequence-based algorithms/tests) and a map
        # (for quick lookups and dashboard).
        self.positions = []  # list of position dicts
        self._positions_map = {}  # symbol -> position dict
        self.closed = []
        # Alias used by API layer (keep in sync with closed list)
        self.closed_positions = self.closed
        self.portfolio_nft = (
            portfolio_nft if portfolio_nft is not None else self._build_portfolio_nft()
        )

    def _build_portfolio_nft(self):
        enabled = str(os.environ.get("PORTFOLIO_NFT_ENABLED", "1")).strip().lower()
        if enabled in {"0", "false", "no", "off"}:
            return None
        try:
            from portfolio.PortfolioNFT import PortfolioNFT

            return PortfolioNFT(log_path=os.environ.get("PORTFOLIO_NFT_LOG_PATH"))
        except Exception as exc:
            logging.warning("PositionManager: PortfolioNFT init failed: %s", exc)
            return None

    def _emit_portfolio_snapshot(self, event_name, position):
        if self.portfolio_nft is None:
            return None
        try:
            nft = self.portfolio_nft.mint_strategy_snapshot(
                event=event_name,
                position=position,
                active_positions=self.positions,
                closed_positions=self.closed,
            )
            logging.info(
                "PositionManager: portfolio snapshot minted event=%s symbol=%s hash=%s",
                event_name,
                (position or {}).get("symbol") if isinstance(position, dict) else None,
                nft.get("hash") if isinstance(nft, dict) else None,
            )
            return nft
        except Exception as exc:
            logging.warning(
                "PositionManager: portfolio snapshot mint failed event=%s error=%s",
                event_name,
                exc,
            )
            return None

    def _is_paper_trace_enabled(self):
        return os.environ.get("LIVE", "0") != "1"

    def _snapshot_position(self, position):
        if isinstance(position, dict):
            return dict(position)
        return None

    def _is_zero_shaped(self, position):
        if not isinstance(position, dict):
            return False
        amount = position.get("amount")
        qty = position.get("qty")
        size = position.get("size")
        try:
            amount_f = float(amount) if amount is not None else None
        except Exception:
            amount_f = None
        qty_zero = qty in (None, "", 0, 0.0)
        size_zero = size in (None, "", 0, 0.0)
        return bool(amount_f == 0.0 and qty_zero and size_zero)

    def _trace(
        self,
        event_name,
        *,
        symbol,
        position=None,
        before=None,
        after=None,
        source_branch=None,
        write_reason=None,
        caller=None,
        extra=None,
    ):
        if not self._is_paper_trace_enabled():
            return
        before_snapshot = self._snapshot_position(before)
        target_after = after if after is not None else position
        after_snapshot = self._snapshot_position(target_after)
        before_object_id = id(before) if isinstance(before, dict) else None
        after_object_id = id(target_after) if isinstance(target_after, dict) else None
        payload = {
            "symbol": symbol,
            "trade_id": (
                (after_snapshot or before_snapshot or {}).get("trade_id")
                if (after_snapshot or before_snapshot)
                else None
            ),
            "caller": caller,
            "source_branch": source_branch,
            "before_snapshot": before_snapshot,
            "after_snapshot": after_snapshot,
            "before_object_id": before_object_id,
            "after_object_id": after_object_id,
            "same_object_id": (
                before_object_id == after_object_id
                if before_object_id is not None and after_object_id is not None
                else None
            ),
            "is_zero_shaped_before": self._is_zero_shaped(before),
            "is_zero_shaped_after": self._is_zero_shaped(target_after),
            "write_reason": write_reason,
        }
        payload["found_in_map"] = position is not None
        payload["object_id"] = after_object_id
        payload["snapshot"] = after_snapshot
        payload["keys_present"] = (
            sorted(list(after_snapshot.keys()))
            if isinstance(after_snapshot, dict)
            else None
        )
        payload["is_none_return"] = position is None and after is None
        if isinstance(extra, dict):
            payload.update(extra)
        try:
            logging.info("%s %s", event_name, payload)
        except Exception as exc:
            logging.debug(
                "PositionManager: trace emit failed event=%s error=%s",
                event_name,
                exc,
            )

    def _caller_label(self, depth=2):
        try:
            frame = inspect.stack()[depth]
            return f"{frame.function}:{frame.lineno}"
        except Exception:
            return None

    def _sync_map_from_list(self):
        if self._is_paper_trace_enabled():
            caller = self._caller_label(2)
            for pos in self.positions:
                symbol = pos.get("symbol") if isinstance(pos, dict) else None
                self._trace(
                    "position_manager_sync_map_from_list",
                    symbol=symbol,
                    position=pos,
                    source_branch="_sync_map_from_list",
                    write_reason="rebuild_map_from_list",
                    caller=caller,
                )
        new_map = {}
        malformed_count = 0
        duplicate_symbols = set()
        for pos in self.positions:
            if not isinstance(pos, dict):
                malformed_count += 1
                continue
            symbol = pos.get("symbol")
            if not symbol:
                malformed_count += 1
                continue
            if symbol in new_map:
                duplicate_symbols.add(symbol)
            new_map[symbol] = pos
        if malformed_count or duplicate_symbols:
            logging.warning(
                (
                    "PositionManager: skipped malformed/duplicate positions "
                    "during map sync malformed_count=%s duplicate_symbols=%s"
                ),
                malformed_count,
                sorted(duplicate_symbols),
            )
        self._positions_map = new_map
        self._sync_list_from_map()

    def _sync_list_from_map(self):
        if self._is_paper_trace_enabled():
            caller = self._caller_label(2)
            for symbol, pos in self._positions_map.items():
                self._trace(
                    "position_manager_sync_list_from_map",
                    symbol=symbol,
                    position=pos,
                    source_branch="_sync_list_from_map",
                    write_reason="rebuild_list_from_map",
                    caller=caller,
                )
        self.positions = list(self._positions_map.values())

    def update_position(self, symbol, order):
        # order: {amount, side, price, timestamp}
        pos = self._positions_map.get(symbol)
        caller = self._caller_label(2)
        side = str(order.get("side", "")).lower()
        strategy = order.get("strategy")
        sl = order.get("sl")
        tp = order.get("tp")
        alpha_micro_exploration = order.get("alpha_micro_exploration")
        ai_vote = order.get("ai_vote")
        ai_weight = order.get("ai_weight")
        trade_id = order.get("trade_id")
        anchor_id = order.get("anchor_id")
        ab_arm_id = order.get("ab_arm_id")
        ab_forced_on_anchor = order.get("ab_forced_on_anchor")
        open_snapshot = order.get("open_snapshot")
        allocation_usdt = order.get("allocation_usdt")
        leverage = order.get("leverage")
        execution_model_open = order.get("execution_model_open")
        fee_rate_open = order.get("fee_rate_open")
        maker_filled_open = order.get("maker_filled_open")
        passthrough_fields = (
            "entry_regime",
            "entry_main_strategy",
            "entry_signal_score",
            "entry_signal_score_abs",
            "entry_signal_score_abs_bucket",
            "entry_expected_edge_after_fee",
            "entry_router_lead",
            "entry_state_snapshot_id",
            "entry_reason",
            "decision_router_path",
            "selection_source",
            "canonical_bucket",
            "canonical_bucket_key",
            "router_top1",
            "router_top2",
            "router_weight_top1",
            "router_weight_top2",
            "router_lead_margin",
            "override_reason",
            "volatility_atr_value",
            "volatility_atr_bucket",
            "realized_vol_value",
            "realized_vol_bucket",
            "mr_pocket_symbol",
            "mr_pocket_side",
            "mr_pocket_regime",
            "mr_pocket_atr_bucket",
            "mr_pocket_score_bucket",
            "mr_pocket_tuple",
            "mr_gate_action",
            "mr_gate_reason",
            "mr_gate_runtime_decision_unchanged",
            "trend_strength_value",
            "trend_strength_bucket",
            "ema_spread_normalized",
            "breakout_distance",
            "local_extreme_distance",
            "decision_ts",
            "fill_ts_open",
            "fill_ts_close",
            "decision_to_fill_delay_ms",
            "arrival_mid_open",
            "arrival_mid_close",
            "fill_price_open",
            "close_fill_price",
            "best_bid",
            "best_ask",
            "best_bid_size",
            "best_ask_size",
            "best_bid_at_decision_open",
            "best_ask_at_decision_open",
            "best_bid_at_fill_open",
            "best_ask_at_fill_open",
            "best_bid_size_at_fill_open",
            "best_ask_size_at_fill_open",
            "best_bid_at_decision_close",
            "best_ask_at_decision_close",
            "best_bid_at_fill_close",
            "best_ask_at_fill_close",
            "spread_abs",
            "spread_bps",
            "spread_bps_bucket",
            "arrival_to_fill_bps_open",
            "arrival_to_fill_bps_close",
            "signed_slippage_bps",
            "fill_to_mid_markout_1",
            "fill_to_mid_markout_5",
            "fill_to_mid_markout_60",
            "top_of_book_depth_proxy",
            "top_of_book_depth_decision_open",
            "top_of_book_depth_fill_open",
            "top_of_book_depth_decision_close",
            "top_of_book_depth_fill_close",
            "entry_unavailable_components",
            "tca_unavailable_components",
            "decision_quote_open",
            "fill_quote_open",
            "decision_quote_close",
            "fill_quote_close",
            "runtime_isolation_status",
            "runtime_isolation_reason",
            "runtime_isolation_key",
            "runtime_isolation_disabled_until",
        )
        if not strategy or str(strategy).lower() == "unknown":
            strategy = "Universal"
        if side in ["buy", "sell", "long", "short"]:
            # Open or update position
            entry_price = (
                order.get("fill_price")
                or order.get("price")
                or order.get("entry_price")
            )
            if not pos:
                new_pos = {
                    "symbol": symbol,
                    "side": side,
                    "amount": order.get("amount", 0),
                    "entry_price": entry_price,
                    "timestamp": order.get("timestamp"),
                }
                if strategy is not None:
                    new_pos["strategy"] = strategy
                if order.get("fill_price") is not None:
                    new_pos["fill_price"] = order.get("fill_price")
                if order.get("fee_cost_open") is not None:
                    new_pos["fee_cost_open"] = order.get("fee_cost_open")
                if fee_rate_open is not None:
                    new_pos["fee_rate_open"] = fee_rate_open
                if execution_model_open is not None:
                    new_pos["execution_model_open"] = execution_model_open
                if maker_filled_open is not None:
                    new_pos["maker_filled_open"] = maker_filled_open
                if order.get("order_id") is not None:
                    new_pos["entry_order_id"] = order.get("order_id")
                if allocation_usdt is not None:
                    new_pos["allocation_usdt"] = allocation_usdt
                if leverage is not None:
                    new_pos["leverage"] = leverage
                if sl is not None:
                    new_pos["sl"] = sl
                if tp is not None:
                    new_pos["tp"] = tp
                if alpha_micro_exploration is not None:
                    new_pos["alpha_micro_exploration"] = bool(
                        alpha_micro_exploration
                    )
                if ai_vote is not None:
                    new_pos["ai_vote"] = ai_vote
                if ai_weight is not None:
                    new_pos["ai_weight"] = ai_weight
                if trade_id is not None:
                    new_pos["trade_id"] = trade_id
                if anchor_id is not None:
                    new_pos["anchor_id"] = anchor_id
                if ab_arm_id is not None:
                    new_pos["ab_arm_id"] = ab_arm_id
                if ab_forced_on_anchor is not None:
                    new_pos["ab_forced_on_anchor"] = bool(ab_forced_on_anchor)
                if isinstance(open_snapshot, dict):
                    new_pos["open_snapshot"] = dict(open_snapshot)
                for field_name in passthrough_fields:
                    if order.get(field_name) is not None:
                        new_pos[field_name] = order.get(field_name)
                self._positions_map[symbol] = new_pos
                self._trace(
                    "position_manager_map_write",
                    symbol=symbol,
                    position=new_pos,
                    before=None,
                    after=new_pos,
                    source_branch="update_position:new",
                    write_reason="assignment_into_positions_map",
                    caller=caller,
                )
            else:
                before = dict(pos)
                # Update amount/side, keep entry_price if not closing
                pos.update(
                    {"side": side, "amount": order.get("amount", pos.get("amount", 0))}
                )
                if strategy is not None:
                    pos["strategy"] = strategy
                if order.get("fill_price") is not None:
                    pos["fill_price"] = order.get("fill_price")
                    pos["entry_price"] = entry_price
                if order.get("fee_cost_open") is not None:
                    pos["fee_cost_open"] = order.get("fee_cost_open")
                if fee_rate_open is not None:
                    pos["fee_rate_open"] = fee_rate_open
                if execution_model_open is not None:
                    pos["execution_model_open"] = execution_model_open
                if maker_filled_open is not None:
                    pos["maker_filled_open"] = maker_filled_open
                if order.get("order_id") is not None:
                    pos["entry_order_id"] = order.get("order_id")
                if allocation_usdt is not None:
                    pos["allocation_usdt"] = allocation_usdt
                if leverage is not None:
                    pos["leverage"] = leverage
                if sl is not None:
                    pos["sl"] = sl
                if tp is not None:
                    pos["tp"] = tp
                if alpha_micro_exploration is not None:
                    pos["alpha_micro_exploration"] = bool(alpha_micro_exploration)
                if ai_vote is not None:
                    pos["ai_vote"] = ai_vote
                if ai_weight is not None:
                    pos["ai_weight"] = ai_weight
                if trade_id is not None:
                    pos["trade_id"] = trade_id
                if anchor_id is not None:
                    pos["anchor_id"] = anchor_id
                if ab_arm_id is not None:
                    pos["ab_arm_id"] = ab_arm_id
                if ab_forced_on_anchor is not None:
                    pos["ab_forced_on_anchor"] = bool(ab_forced_on_anchor)
                if isinstance(open_snapshot, dict):
                    pos["open_snapshot"] = dict(open_snapshot)
                for field_name in passthrough_fields:
                    if order.get(field_name) is not None:
                        pos[field_name] = order.get(field_name)
                self._trace(
                    "position_manager_map_update",
                    symbol=symbol,
                    position=pos,
                    before=before,
                    after=pos,
                    source_branch="update_position:mutate",
                    write_reason="in_place_update_into_positions_map",
                    caller=caller,
                )
            self._sync_list_from_map()
            if not pos:
                self._emit_portfolio_snapshot("position_open", new_pos)
        elif side == "close":
            # Close position
            if pos:
                before = dict(pos)
                close_price = (
                    order.get("price")
                    or order.get("close_price")
                    or order.get("exit_price")
                )
                pos["close_price"] = close_price
                pos["close_timestamp"] = order.get("timestamp")
                if order.get("realized_pnl") is not None:
                    pos["realized_pnl"] = order.get("realized_pnl")
                if order.get("fee_cost") is not None:
                    pos["fee_cost"] = order.get("fee_cost")
                if order.get("funding_cost") is not None:
                    pos["funding_cost"] = order.get("funding_cost")
                if pos.get("realized_pnl") is None:
                    try:
                        entry = pos.get("entry_price") or pos.get("price")
                        amount = pos.get("amount")
                        if (
                            entry is not None
                            and close_price is not None
                            and amount is not None
                        ):
                            side = str(pos.get("side", "")).lower()
                            entry_f = float(entry)
                            close_f = float(close_price)
                            amt_f = float(amount)
                            if side in ("sell", "short"):
                                pnl = (entry_f - close_f) * amt_f
                            else:
                                pnl = (close_f - entry_f) * amt_f
                            pos["realized_pnl"] = pnl
                    except Exception as exc:
                        logging.warning(
                            (
                                "PositionManager: close pnl recompute failed "
                                "symbol=%s error=%s"
                            ),
                            symbol,
                            exc,
                        )
                self.closed.append(pos)
                del self._positions_map[symbol]
                self._sync_list_from_map()
                self._trace(
                    "position_manager_map_delete",
                    symbol=symbol,
                    position=None,
                    before=before,
                    after=None,
                    source_branch="update_position:close",
                    write_reason="delete_from_positions_map",
                    caller=caller,
                )
                self._emit_portfolio_snapshot("position_close", pos)

    def get_position(self, symbol):
        pos = self._positions_map.get(symbol)
        caller = self._caller_label(2)
        self._trace(
            "position_manager_get_position",
            symbol=symbol,
            position=pos,
            source_branch="get_position",
            write_reason="read_positions_map",
            caller=caller,
        )
        return pos

    def get_status(self):
        if not self._positions_map:
            return "none"
        if len(self._positions_map) == 1:
            # Return single side string for convenience in simple tests
            return next(iter(self._positions_map.values()))["side"]
        return {s: p["side"] for s, p in self._positions_map.items()}

    # Backwards-compatible API expected by tests
    def open_position(self, position: dict):
        symbol = position.get("symbol")
        if not symbol:
            raise ValueError("Position must include a symbol")
        caller = self._caller_label(2)
        entry = {
            "symbol": symbol,
            "side": position.get("side"),
            "amount": position.get("amount", 0),
            "entry_price": position.get("entry_price"),
            "timestamp": position.get("timestamp"),
        }
        strategy = position.get("strategy")
        if not strategy or str(strategy).lower() == "unknown":
            strategy = "Universal"
        entry["strategy"] = strategy
        if position.get("sl") is not None:
            entry["sl"] = position.get("sl")
        if position.get("tp") is not None:
            entry["tp"] = position.get("tp")
        if position.get("alpha_micro_exploration") is not None:
            entry["alpha_micro_exploration"] = bool(
                position.get("alpha_micro_exploration")
            )
        if position.get("ai_vote") is not None:
            entry["ai_vote"] = position.get("ai_vote")
        if position.get("ai_weight") is not None:
            entry["ai_weight"] = position.get("ai_weight")
        if position.get("trade_id") is not None:
            entry["trade_id"] = position.get("trade_id")
        if position.get("anchor_id") is not None:
            entry["anchor_id"] = position.get("anchor_id")
        if position.get("ab_arm_id") is not None:
            entry["ab_arm_id"] = position.get("ab_arm_id")
        if position.get("ab_forced_on_anchor") is not None:
            entry["ab_forced_on_anchor"] = bool(position.get("ab_forced_on_anchor"))
        if isinstance(position.get("open_snapshot"), dict):
            entry["open_snapshot"] = dict(position.get("open_snapshot"))
        self._positions_map[symbol] = entry
        self._trace(
            "position_manager_map_write",
            symbol=symbol,
            position=entry,
            before=None,
            after=entry,
            source_branch="open_position",
            write_reason="assignment_into_positions_map",
            caller=caller,
        )
        self._sync_list_from_map()
        self._emit_portfolio_snapshot("position_open", entry)

    def close_position(
        self,
        symbol_or_position,
        timestamp=None,
        price=None,
        realized_pnl=None,
        fee_cost=None,
        funding_cost=None,
    ):
        # Accept either a symbol or a position dict
        if isinstance(symbol_or_position, dict):
            symbol = symbol_or_position.get("symbol")
        else:
            symbol = symbol_or_position
        pos = self._positions_map.get(symbol)
        caller = self._caller_label(2)
        if pos:
            before = dict(pos)
            try:
                logging.info(
                    "position_manager_close_pre_delete %s",
                    {
                        "symbol": symbol,
                        "trade_id": pos.get("trade_id"),
                        "amount_before": pos.get("amount"),
                        "side_before": pos.get("side"),
                        "position_object_id": id(pos),
                        "timestamp": timestamp,
                        "price": price,
                        "realized_pnl": realized_pnl,
                        "fee_cost": fee_cost,
                        "funding_cost": funding_cost,
                    },
                )
            except Exception as exc:
                logging.debug(
                    "PositionManager: pre-delete trace emit failed symbol=%s error=%s",
                    symbol,
                    exc,
                )
            if price is not None:
                pos["close_price"] = price
            if fee_cost is not None:
                pos["fee_cost"] = fee_cost
            if funding_cost is not None:
                pos["funding_cost"] = funding_cost
            if realized_pnl is not None:
                pos["realized_pnl"] = realized_pnl
            if pos.get("realized_pnl") is None and price is not None:
                try:
                    entry = pos.get("entry_price") or pos.get("price")
                    amount = pos.get("amount")
                    side = str(pos.get("side", "")).lower()
                    if entry is not None and amount is not None:
                        if side in ("sell", "short"):
                            pnl = (float(entry) - float(price)) * float(amount)
                        else:
                            pnl = (float(price) - float(entry)) * float(amount)
                        pos["realized_pnl"] = pnl
                except Exception as exc:
                    logging.warning(
                        (
                            "PositionManager: close_position pnl recompute failed "
                            "symbol=%s error=%s"
                        ),
                        symbol,
                        exc,
                    )
            pos["close_timestamp"] = timestamp
            self.closed.append(pos)
            del self._positions_map[symbol]
            self._sync_list_from_map()
            self._trace(
                "position_manager_map_delete",
                symbol=symbol,
                position=None,
                before=before,
                after=None,
                source_branch="close_position",
                write_reason="delete_from_positions_map",
                caller=caller,
            )
            self._emit_portfolio_snapshot("position_close", pos)
            try:
                logging.info(
                    "position_manager_close_post_delete %s",
                    {
                        "symbol": symbol,
                        "trade_id": pos.get("trade_id"),
                        "amount_after": pos.get("amount"),
                        "side_after": pos.get("side"),
                        "position_object_id": id(pos),
                        "get_position_after": self.get_position(symbol),
                    },
                )
            except Exception as exc:
                logging.debug(
                    "PositionManager: post-delete trace emit failed symbol=%s error=%s",
                    symbol,
                    exc,
                )
