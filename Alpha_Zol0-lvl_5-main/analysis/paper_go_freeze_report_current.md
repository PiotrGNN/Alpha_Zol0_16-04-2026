# Paper GO Freeze Report

- classification: PAPER_GO_CANONICALIZED
- readiness_classification: READINESS_CURRENT_CONTRACT_REPRODUCIBLE
- live_classification: LIVE_STILL_HARD_GATED
- created_at_utc: 2026-05-01T19:42:58.030466+00:00

## Artifact integrity
- promotion_manifest: `analysis/paper_go_promotion_manifest_current.json` sha256=`6CD6C7CA2D375661C0B4BE6C0F8772BD43F6FE09BF60426926405D9F1410C356` json_parse_valid=True
- selected_profile: `tmp/paper_go_selected_profile_current.json` sha256=`992B615B122FD15D033FCAD8A87BAD759C615DAA3A50E085000544FECB193162` json_parse_valid=True
- positive_lock: `tmp/paper_go_positive_lock_current.json` sha256=`7964E7459B9E8965257D98AACFB4D9D46C027BEAF8FF7EC1422B0488D50734FA` json_parse_valid=True
- readiness_current: `tmp/paper_go_readiness_current.json` sha256=`AA697D484011D02DB985CD65BFE48E85928963B0644DD7E4DEE7725FE417DDBC` json_parse_valid=True

## Readiness rerun
- command: `python scripts\run_paper_readiness_gate.py --after-env-json tmp\paper_go_selected_profile_current.json --positive-lock-json tmp\paper_go_positive_lock_current.json --json-out tmp\paper_go_readiness_current.json`
- exit_code: `0`
- paper_ready: `True`
- economic_channel_status: `PASS`
- economic_channel_go_no_go: `GO`
- global_verdict: `PROMOTE_CANDIDATE`
- live_ready: `False`

## Natural trade evidence
- status: `LOCKED_POSITIVE_PAPER_PROFILE`
- natural_completed_trades: `11`
- cumulative_net_pnl: `0.15049327650515287`
- profit_factor: `4.597812459512504`
- expectancy: `0.013681206955013897`
- winrate: `0.8181818181818182`

## Threshold / stale-source audit
- readiness_semantics_mutated_in_freeze: `False`
- strategy_mutated_in_freeze: `False`
- threshold_mutated_in_freeze: `False`
- canonical_readiness_used_current_paths_only: `True`
- stale_latest_artifact_used_by_manifest: `False`
- economics_metric_source: `positive_paper_lock`
- positive_lock_contract_status: `PASS`
- profile_contract_status: `PASS`
- profile_sha_matches_lock: `True`

## Final verdict
- PAPER_GO_CANONICALIZED
- READINESS_CURRENT_CONTRACT_REPRODUCIBLE
- LIVE_STILL_HARD_GATED
