# Document retrieval suite

- **Run:** 2026-11-04T21:45:57+00:00
- **Embedding model:** `BAAI/bge-small-en-v1.5`
- **Reranker:** `BAAI/bge-reranker-base`
- **Questions:** 15
- **k:** 5

| Arm | Recall@k | MRR | Hit rate | Answer present | p50 ms | p95 ms |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| small + rerank | 0.667 | 0.572 | 0.733 | 0.533 | 2465 | 2601 |
| default + rerank | 0.667 | 0.552 | 0.733 | 0.600 | 4684 | 4810 |
| small | 0.633 | 0.424 | 0.667 | 0.400 | 29 | 54 |
| default | 0.600 | 0.397 | 0.667 | 0.533 | 48 | 55 |

## By question origin

Project-authored notes are an easier retrieval target than the external
USFA documents. A headline that does not separate them is flattered.

| Arm | Origin | n | Recall@k | MRR | Hit rate |
| --- | --- | ---: | ---: | ---: | ---: |
| small + rerank | external | 12 | 0.583 | 0.528 | 0.667 |
| small + rerank | methodology | 3 | 1.000 | 0.750 | 1.000 |
| default + rerank | external | 12 | 0.583 | 0.507 | 0.667 |
| default + rerank | methodology | 3 | 1.000 | 0.733 | 1.000 |
| small | external | 12 | 0.542 | 0.336 | 0.583 |
| small | methodology | 3 | 1.000 | 0.778 | 1.000 |
| default | external | 12 | 0.500 | 0.301 | 0.583 |
| default | methodology | 3 | 1.000 | 0.778 | 1.000 |

## Reranker decision

**default** — directionally positive (+1.0 questions of 15), UNDERPOWERED -- re-measure against the 50-question golden set at M4

- ΔRecall@k: +0.0667 (+1.0 of 15 questions; one question = 0.067)
- ΔMRR: +0.1555
- added latency (p50): +4635.5 ms
- underpowered: True

**small** — directionally positive (+0.5 questions of 15), UNDERPOWERED -- re-measure against the 50-question golden set at M4

- ΔRecall@k: +0.0334 (+0.5 of 15 questions; one question = 0.067)
- ΔMRR: +0.1478
- added latency (p50): +2436.4 ms
- underpowered: True


## Misses in `small` (4)

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

### d13 — What does the NFIRS incident type field record?

Retrieved instead:

- 1. 0.414 FireSight Methodology — 1. Data sources
- 2. 0.391 NFIRS 5.0 Complete Reference Guide — Section B: Location Type, p. 31
- 3. 0.364 NFIRS 5.0 Design Documentation — User Defined Transactions, p. 145
- 4. 0.328 NFIRS 5.0 Design Documentation — Reporting Requirements, p. 325
- 5. 0.152 NFIRS 5.0 Fire Data Analysis Guidelines and Issues — NFIRS PDR Files, p. 6
