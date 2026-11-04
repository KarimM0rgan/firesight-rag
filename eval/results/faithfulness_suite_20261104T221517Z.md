# Answer faithfulness suite

- **Run:** 2026-11-04T22:15:17+00:00
- **Model:** `claude-sonnet-5`  ·  **Arm:** small
- **Questions:** 15 (13 answered, 2 refused, 13 judged)

| Metric | Value |
| --- | --- |
| Faithfulness (answers with zero unsupported claims) | 84.6% |
| Mean unsupported claims per answer | 0.231 |
| Citation rate (answers carrying any citation) | 100.0% |
| Citation validity (every citation was retrieved) | 23.1% |
| Judge failures | 0 |
| Latency p50 | 2819 ms |
| Cost | $0.27129 total, $0.01809 per question |

## By question origin

| Origin | n judged | Faithfulness |
| --- | ---: | ---: |
| external | 11 | 81.8% |
| methodology | 2 | 100.0% |

## Unfaithful answers and fabricated citations (10)

### d01 — How does NFIRS define a structure?

- unsupported claims: 0 of 1
- **citations not in retrieved set:** ['NFIRS 5.0 Complete Reference Guide — Structure Type']

```
A structure is defined as an assembly of materials forming a construction for occupancy or use to serve a specific purpose, including but not limited to buildings, open platforms, bridges, roof assemblies over open storage or process areas, tents, air-supported structures, and grandstands [NFIRS 5.0 Complete Reference Guide — Structure Type].
```

### d02 — What incident type code is used for a building fire, and what does it exclude?

- unsupported claims: 2 of 4
  - as discussed in later sections
  - distinct from general building fires
- **citations not in retrieved set:** ['NFIRS 5.0 Fire Data Analysis Guidelines and Issues — Types of Fires by Incident Type']

```
Building fires are a subset of structure fires, which fall under Incident Type codes 111–123 [NFIRS 5.0 Fire Data Analysis Guidelines and Issues — Types of Fires by Incident Type]. Within this range, Confined Fires (113–118) and Mobile Structure Fires (120–123) are treated as separate subsets, as discussed in later sections, distinct from general building fires [NFIRS 5.0 Fire Data Analysis Guidelines and Issues — Types of Fires by Incident Type].
```

### d03 — How many characters is an FDID and who assigns it?

- unsupported claims: 0 of 2
- **citations not in retrieved set:** ['NFIRS 5.0 Complete Reference Guide — Fire Department Identification (FDID)']

```
The FDID (Fire Department Identification) is a five-character identifier, and it is assigned by the State [NFIRS 5.0 Complete Reference Guide — Fire Department Identification (FDID)]. This is corroborated by the FireSight Methodology, which also describes FDID as "a five-character identifier assigned by each state" [FireSight Methodology — 2. Department identity].
```

### d05 — Is reporting to NFIRS mandatory for fire departments?

- unsupported claims: 0 of 2
- **citations not in retrieved set:** ['NFIRS 5.0 Design Documentation — The Data-based Decision-making Process', 'NFIRS 5.0 Design Documentation — System Design Objectives']

```
Fire incident reporting is mandatory in many states, with state incident data sent to the National Fire Data Center at the U.S. Fire Administration for analysis [NFIRS 5.0 Design Documentation — The Data-based Decision-making Process]. Additionally, the USFA and many states are mandated by law to collect fire information, relying on the fire service to meet that requirement through NFIRS [NFIRS 5.0 Design Documentation — System Design Objectives].
```

### d06 — For which incident type codes is the detector field required to be completed?

- unsupported claims: 0 of 2
- **citations not in retrieved set:** ['NFIRS 5.0 Complete Reference Guide — Detector', 'NFIRS 5.0 Design Documentation — Edit Requirements']

```
The detector field (H2 Detector) is required for all confined fires, specifically Incident Type codes 113–118 [NFIRS 5.0 Complete Reference Guide — Detector]. This is consistent with an edit requirement noting that if Detector = 1, the Presence of Detectors field must also be completed if the Structure Fire Module exists for the incident [NFIRS 5.0 Design Documentation — Edit Requirements].
```

### d07 — Which NFIRS module is completed for wildland or vegetation fires?

- unsupported claims: 0 of 2
- **citations not in retrieved set:** ['NFIRS 5.0 Complete Reference Guide — Preparation of Modules', 'NFIRS 5.0 Design Documentation — System Modules']

```
The Wildland Fire Module (NFIRS-8) is completed to report incidents that involve wildland or vegetation fires, and it is used in lieu of the Fire Module for such incidents [NFIRS 5.0 Complete Reference Guide — Preparation of Modules]. This is confirmed elsewhere, noting the module must be used in conjunction with the Basic Module (NFIRS-1) and replaces the Fire Module (NFIRS-2) for wildland fire incidents [NFIRS 5.0 Design Documentation — System Modules].
```

### d08 — Which NFIRS module reports injuries or deaths to civilians?

- unsupported claims: 0 of 4
- **citations not in retrieved set:** ['NFIRS 5.0 Design Documentation — System Modules', 'NFIRS 5.0 Complete Reference Guide — Description of Modules']

```
The Civilian Fire Casualty Module (NFIRS-4) is used to report injuries or deaths to civilians or other emergency personnel (such as police officers or non-fire department EMS personnel) that occur in conjunction with a fire incident [NFIRS 5.0 Design Documentation — System Modules]. It must be used alongside the Basic Module, the Fire Module, and, if applicable, the Structure Fire Module, and is specifically for fire-related injuries/fatalities; non-fire-related civilian injuries are reported instead on the EMS Module (NFIRS-6) [NFIRS 5.0 Design Documentation — System Modules][NFIRS 5.0 Complete Reference Guide — Description of Modules].
```

### d10 — How did the definition of a building fire change in NFIRS 5.0 compared with earlier versions?

- unsupported claims: 0 of 6
- **citations not in retrieved set:** ['NFIRS 5.0 Fire Data Analysis Guidelines and Issues — Types of Fires by Incident Type']

```
In earlier NFIRS versions, the term "structure" commonly referred to buildings where people live and work, but NFIRS 5.0 redefined "building fire" to include only incidents where the Structure Type is 1 or 2 (enclosed building, or fixed portable/mobile structure), distinguishing these from other structures like fences and sheds [NFIRS 5.0 Fire Data Analysis Guidelines and Issues — Types of Fires by Incident Type]. Additionally, starting with 2008 data, Incident Type 112 (fire in structure, other than in a building) was excluded from building fire counts, whereas prior to 2008 it had been included because such incidents were often found to be miscoded building fires [NFIRS 5.0 Fire Data Analy
```

### d11 — Can a firefighter's exposure to chemicals be reported if it caused no injury?

- unsupported claims: 1 of 5
  - meaning no actual injury needs to have occurred for it to be documented
- **citations not in retrieved set:** ['NFIRS 5.0 Complete Reference Guide — Station Number', 'NFIRS 5.0 Complete Reference Guide — Taken To', 'NFIRS 5.0 Complete Reference Guide — Severity', 'NFIRS 5.0 Design Documentation — System Modules']

```
Yes. A health exposure occurs when fire service personnel come in contact with a toxic substance or harmful physical agent through any route of entry into the body (e.g., inhalation, ingestion, skin absorption, direct contact), and these exposures can be reported regardless of the presence of clinical signs and symptoms [NFIRS 5.0 Complete Reference Guide — Station Number]; [NFIRS 5.0 Complete Reference Guide — Taken To]. Such exposures are treated as "report only," the lowest severity code, meaning no actual injury needs to have occurred for it to be documented [NFIRS 5.0 Complete Reference Guide — Taken To]; [NFIRS 5.0 Complete Reference Guide — Severity]. This aligns with the Fire Service
```

### d13 — What does the NFIRS incident type field record?

- unsupported claims: 0 of 2
- **citations not in retrieved set:** ['NFIRS 5.0 Fire Data Analysis Guidelines and Issues — Unique Identifiers']

```
The passages do not directly define what the Incident Type (INC_TYPE) field records, but they do note that Incident Type code "110" (undefined structure fire) is a conversion-only code from NFIRS 4.1, used when older data is mapped into the NFIRS 5.0 system [NFIRS 5.0 Fire Data Analysis Guidelines and Issues — Unique Identifiers]. Beyond this specific conversion detail, the corpus does not contain a general description of what the Incident Type field records, so I can't provide a complete grounded answer to that broader question.
```
