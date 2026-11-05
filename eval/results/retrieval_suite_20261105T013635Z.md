# Document retrieval suite

- **Run:** 2026-11-05T01:36:35+00:00
- **Embedding model:** `BAAI/bge-small-en-v1.5`
- **Reranker:** `BAAI/bge-reranker-base`
- **Questions:** 50
- **k:** 5

- **Embedding model:** `BAAI/bge-small-en-v1.5`

Recall@k and MRR carry normal-approximation intervals (they are means);
hit rate and answer-present carry Wilson intervals (they are proportions).

| Arm | Recall@k (95% CI) | MRR (95% CI) | Hit rate | Answer present | p50 ms |
| --- | --- | --- | --- | --- | ---: |
| small + rerank | 0.850 [0.756, 0.944] | 0.712 [0.607, 0.817] | 88.0% [76.2–94.4] | 76.0% [62.6–85.7] | 2366 |
| default + rerank | 0.840 [0.741, 0.939] | 0.670 [0.563, 0.777] | 86.0% [73.8–93.0] | 76.0% [62.6–85.7] | 4338 |
| small | 0.820 [0.716, 0.924] | 0.613 [0.499, 0.727] | 84.0% [71.5–91.7] | 68.0% [54.2–79.2] | 26 |
| default | 0.795 [0.687, 0.903] | 0.601 [0.490, 0.713] | 82.0% [69.2–90.2] | 70.0% [56.2–80.9] | 26 |

## By question origin

Project-authored notes are an easier retrieval target than the external
USFA documents. A headline that does not separate them is flattered.

| Arm | Origin | n | Recall@k | MRR | Hit rate |
| --- | --- | ---: | ---: | ---: | ---: |
| small + rerank | external | 42 | 0.821 | 0.675 | 0.857 |
| small + rerank | methodology | 8 | 1.000 | 0.906 | 1.000 |
| default + rerank | external | 42 | 0.809 | 0.637 | 0.833 |
| default + rerank | methodology | 8 | 1.000 | 0.844 | 1.000 |
| small | external | 42 | 0.786 | 0.571 | 0.809 |
| small | methodology | 8 | 1.000 | 0.833 | 1.000 |
| default | external | 42 | 0.756 | 0.549 | 0.786 |
| default | methodology | 8 | 1.000 | 0.875 | 1.000 |

## Reranker decision

**default** — directionally positive (16 improved / 9 worsened) but NOT ESTABLISHED (sign test p=0.230) at n=50

- ΔRecall@k: +0.0450 (+2.2 of 50 questions; one question = 0.020)
- ΔMRR: +0.0687
- added latency (p50): +4311.5 ms
- paired: 16 improved / 9 worsened, sign test p=0.2295
- significant at 0.05: False

**small** — directionally positive (14 improved / 5 worsened) but NOT ESTABLISHED (sign test p=0.064) at n=50

- ΔRecall@k: +0.0300 (+1.5 of 50 questions; one question = 0.020)
- ΔMRR: +0.0987
- added latency (p50): +2340.0 ms
- paired: 14 improved / 5 worsened, sign test p=0.0636
- significant at 0.05: False


## Misses in `small` (6)

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

### d16 — What does NFIRS mean by an exposure?

Retrieved instead:

- 1. 0.693 NFIRS 5.0 Complete Reference Guide — Station Number, p. 185
- 2. 0.381 NFIRS 5.0 Complete Reference Guide — Section B: Apparatus or Resources, p. 355
- 3. 0.350 NFIRS 5.0 Complete Reference Guide — How NFIRS Works, p. 11
- 4. 0.304 NFIRS 5.0 Complete Reference Guide — Section B: Apparatus or Resources, p. 343
- 5. 0.213 NFIRS 5.0 Complete Reference Guide — Delete/Change/No Activity, p. 29

### d45 — What is the street prefix on an NFIRS address?

Retrieved instead:

- 1. 0.995 NFIRS Code Dictionary — Field STREET_PRE
- 2. 0.992 NFIRS 5.0 Complete Reference Guide — Apartment, Suite, or Room, p. 38
- 3. 0.940 NFIRS 5.0 Complete Reference Guide — Street Type, p. 36
- 4. 0.907 NFIRS 5.0 Design Documentation — System Modules, p. 49
- 5. 0.870 NFIRS 5.0 Complete Reference Guide — State, p. 39
