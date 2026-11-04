# Document retrieval suite

- **Run:** 2026-11-04T18:52:38+00:00
- **Embedding model:** `BAAI/bge-small-en-v1.5`
- **Reranker:** `BAAI/bge-reranker-base`
- **Questions:** 15
- **k:** 5

| Arm | Recall@k | MRR | Hit rate | Answer present | p50 ms | p95 ms |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| small + rerank | 0.700 | 0.711 | 0.800 | 0.667 | 2401 | 2507 |
| default + rerank | 0.700 | 0.628 | 0.800 | 0.667 | 4576 | 4774 |
| default | 0.600 | 0.474 | 0.667 | 0.533 | 30 | 35 |
| small | 0.567 | 0.452 | 0.600 | 0.467 | 28 | 45 |

## Reranker decision

**default** — KEEP the reranker

- ΔRecall@k: +0.1000
- ΔMRR: +0.1534
- added latency (p50): +4545.6 ms

**small** — KEEP the reranker

- ΔRecall@k: +0.1333
- ΔMRR: +0.2589
- added latency (p50): +2373.5 ms


## Misses in `small` (3)

### d01 — How does NFIRS define a structure?

Retrieved instead:

- 1. 0.794 NFIRS 5.0 Fire Data Analysis Guidelines and Issues — Types of Fires by Incident Type, p. 21
- 2. 0.628 NFIRS Code Dictionary — Field STRUC_TYPE
- 3. 0.603 NFIRS 5.0 Complete Reference Guide — Structure Type, p. 134
- 4. 0.501 NFIRS 5.0 Complete Reference Guide — Building Status, p. 135
- 5. 0.167 NFIRS 5.0 Fire Data Analysis Guidelines and Issues — Other Property Definitions, p. 25

### d02 — What incident type code is used for a building fire, and what does it exclude?

Retrieved instead:

- 1. 0.995 NFIRS 5.0 Fire Data Analysis Guidelines and Issues — Types of Fires by Incident Type, p. 21
- 2. 0.993 NFIRS 5.0 Fire Data Analysis Guidelines and Issues — Types of Fires by Incident Type, p. 17
- 3. 0.979 NFIRS 5.0 Complete Reference Guide — Section C: Incident Type, p. 42
- 4. 0.924 NFIRS 5.0 Fire Data Analysis Guidelines and Issues — Types of Fires by Incident Type, p. 20
- 5. 0.921 NFIRS 5.0 Design Documentation — Edit Requirements, p. 117

### d11 — Can a firefighter's exposure to chemicals be reported if it caused no injury?

Retrieved instead:

- 1. 0.912 NFIRS 5.0 Design Documentation — System Modules, p. 32
- 2. 0.864 NFIRS 5.0 Complete Reference Guide — Severity, p. 193
- 3. 0.387 NFIRS 5.0 Complete Reference Guide — Station Number, p. 185
- 4. 0.142 NFIRS 5.0 Complete Reference Guide — Taken To, p. 194
- 5. 0.116 NFIRS 5.0 Complete Reference Guide — Where Injury Occurred, p. 204
