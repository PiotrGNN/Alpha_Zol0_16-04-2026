---
applyTo: "tmp/**,results/**,reports/**,autopsy/**,analysis/**/*.json,analysis/**/*.md"
---

# Artifact Evidence Contract

Artifacts are evidence, not decoration.

Each produced artifact should include:
- source paths
- command used
- run id and timestamp
- key metrics
- contamination reasons (if any)

Profitability claim rule:
- Do not claim profitability unless clean-runtime criteria are satisfied.
- Observed PnL alone is insufficient for clean profitability proof.
- Prefer explicit REJECT/CONTAMINATED over forced PASS.
