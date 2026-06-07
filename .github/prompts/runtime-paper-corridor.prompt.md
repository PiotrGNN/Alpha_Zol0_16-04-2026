# RUNTIME_PAPER_CORRIDOR

Use this prompt for deterministic PAPER runtime validation.

Runtime constraints:
- Set LIVE=0.
- Set USE_MOCK exactly as explicitly requested.
- Do not seed or fallback unless explicitly requested.
- Do not mutate threshold/readiness settings.

Required report fields:
- run id
- DB/JSON/CSV artifact paths
- return code
- shutdown classification
- open count
- close count
- contamination markers

Quality rule:
- Never infer clean profitability from observed PnL alone.
