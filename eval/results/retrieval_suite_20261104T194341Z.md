# Document retrieval suite

- **Run:** 2026-11-04T19:43:41+00:00
- **Embedding model:** `BAAI/bge-small-en-v1.5`
- **Reranker:** `BAAI/bge-reranker-base`
- **Questions:** 15
- **k:** 5

| Arm | Recall@k | MRR | Hit rate | Answer present | p50 ms | p95 ms |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| small + rerank | 0.700 | 0.644 | 0.800 | 0.667 | 2433 | 2529 |
| default + rerank | 0.700 | 0.594 | 0.800 | 0.667 | 4560 | 4640 |
| default | 0.600 | 0.441 | 0.667 | 0.533 | 31 | 40 |
| small | 0.533 | 0.386 | 0.600 | 0.467 | 31 | 54 |

## By question origin

Project-authored notes are an easier retrieval target than the external
USFA documents. A headline that does not separate them is flattered.

| Arm | Origin | n | Recall@k | MRR | Hit rate |
| --- | --- | ---: | ---: | ---: | ---: |
| small + rerank | external | 11 | 0.636 | 0.621 | 0.727 |
| small + rerank | project | 4 | 0.875 | 0.708 | 1.000 |
| default + rerank | external | 11 | 0.636 | 0.553 | 0.727 |
| default + rerank | project | 4 | 0.875 | 0.708 | 1.000 |
| default | external | 11 | 0.545 | 0.374 | 0.636 |
| default | project | 4 | 0.750 | 0.625 | 0.750 |
| small | external | 11 | 0.500 | 0.344 | 0.545 |
| small | project | 4 | 0.625 | 0.500 | 0.750 |

## Reranker decision

**default** — directionally positive (+1.5 questions of 15), UNDERPOWERED -- re-measure against the 50-question golden set at M4

- ΔRecall@k: +0.1000 (+1.5 of 15 questions; one question = 0.067)
- ΔMRR: +0.1533
- added latency (p50): +4528.3 ms
- underpowered: True

**small** — directionally positive (+2.5 questions of 15), UNDERPOWERED -- re-measure against the 50-question golden set at M4

- ΔRecall@k: +0.1667 (+2.5 of 15 questions; one question = 0.067)
- ΔMRR: +0.2588
- added latency (p50): +2402.0 ms
- underpowered: True


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
