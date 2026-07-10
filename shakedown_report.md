# Shakedown report

run: 2026-07-09 19:02 UTC | tier: free (local OCR) | ruleset: 1.1.0 @ `467cb20f7bc08ce0` | assets: 11

No scoring, no labels. Engine ran against a synthetic 'perfect echo' of each asset's own structure — engine failures here mean plumbing bugs, not compliance verdicts. Asset defects are deterministic statements about the ads themselves.

## Failures & anomalies

- **EXTRACTION GAP** `1073608245839934`: claims ['clm_3'] contain money/percent figures matching no extracted entity — echo left those quotes empty; check nlp/entities.py recall on this asset's text
- **EXTRACTION GAP** `1322487049287816`: claims ['clm_3', 'clm_4'] contain money/percent figures matching no extracted entity — echo left those quotes empty; check nlp/entities.py recall on this asset's text

## Summary

| asset | media | latency (s) | segs | entities | claims | cv | product | frameworks | fallback | engine |
|---|---|---|---|---|---|---|---|---|---|---|
| 1023652900018510 | carousel (6 cards) | 89.6 | 33 | 14 | 2 | 84 | deposit_account | FTC, Reg_DD, CFPB | no | passed r1 |
| 1047873781233743 | carousel (7 cards) | 135.0 | 35 | 0 | 7 | 119 | deposit_account | FTC, Reg_DD, CFPB | no | passed r1 |
| 1060060903188799 | carousel (6 cards) | 89.3 | 31 | 0 | 0 | 62 | deposit_account | FTC, Reg_DD, CFPB | no | passed r1 |
| 1073608245839934 | carousel (6 cards) | 22.6 | 21 | 0 | 3 | 42 | deposit_account | FTC, Reg_DD, CFPB | no | passed r1 |
| 1192947802913589 | carousel (4 cards) | 66.5 | 25 | 1 | 9 | 90 | deposit_account | FTC, Reg_DD, CFPB | no | passed r1 |
| 1239989448218452 | carousel (6 cards) | 81.9 | 31 | 0 | 0 | 62 | deposit_account | FTC, Reg_DD, CFPB | no | passed r1 |
| 1297773045148944 | carousel (2 cards) | 65.5 | 11 | 4 | 4 | 26 | personal_loan | FTC, TILA, CFPB | no | passed r1 |
| 1322487049287816 | carousel (3 cards) | 103.2 | 18 | 18 | 12 | 87 | unknown | FTC | no | passed r1 |
| 1365822818902156 | carousel (2 cards) | 41.9 | 8 | 0 | 4 | 20 | deposit_account | FTC, Reg_DD, CFPB | no | passed r1 |
| 1381634810455796 | single image | 15.3 | 13 | 1 | 4 | 32 | personal_loan | FTC, TILA, CFPB | no | passed r1 |
| 2828127634031801 | carousel (1 cards) | 9.3 | 1 | 0 | 0 | 2 | unknown | FTC | no | passed r1 |

## Per-asset detail

### 1023652900018510

![1023652900018510](data/shakedown/1023652900018510/1023652900018510_card1.jpg)

- media: carousel (6 cards) | latency: 89.6s
- segments: 33 | claims: 2 | cv findings: 84
- entities: amount: 11, percentage: 2, time_period: 1
- routing: **deposit_account** -> FTC, Reg_DD, CFPB
- routing signal: marketing asset -> FTC; deposit product -> Reg DD; consumer financial product -> CFPB UDAAP
- semantic fallback: routing=False, sem claims=none, embedding=—
- engine: passed round 1 (22 ms) | asset defects: FTC5-STR-002 [medium]

| segment | role | text (first 3, OCR eyeball) |
|---|---|---|
| seg_c1_1 | cta | START |
| seg_c1_2 | headline | BMO's expert bankers know every business is different and offer financial guidance to matc |
| seg_c1_3 | unknown | yes |

### 1047873781233743

![1047873781233743](data/shakedown/1047873781233743/1047873781233743_card1.jpg)

- media: carousel (7 cards) | latency: 135.0s
- segments: 35 | claims: 7 | cv findings: 119
- entities: none
- routing: **deposit_account** -> FTC, Reg_DD, CFPB
- routing signal: marketing asset -> FTC; deposit product -> Reg DD; consumer financial product -> CFPB UDAAP
- semantic fallback: routing=False, sem claims=none, embedding=—
- engine: passed round 1 (3 ms) | asset defects: none

| segment | role | text (first 3, OCR eyeball) |
|---|---|---|
| seg_c1_1 | unknown | us bank |
| seg_c1_2 | headline | Are you loyal? Or just stuck? |
| seg_c1_3 | body | Most banks don't earn loyalty. They rely on the pain of leaving. |

### 1060060903188799

![1060060903188799](data/shakedown/1060060903188799/1060060903188799_card1.jpg)

- media: carousel (6 cards) | latency: 89.3s
- segments: 31 | claims: 0 | cv findings: 62
- entities: none
- routing: **deposit_account** -> FTC, Reg_DD, CFPB
- routing signal: marketing asset -> FTC; deposit product -> Reg DD; consumer financial product -> CFPB UDAAP
- semantic fallback: routing=False, sem claims=none, embedding=—
- engine: passed round 1 (1 ms) | asset defects: none

| segment | role | text (first 3, OCR eyeball) |
|---|---|---|
| seg_c1_1 | headline | BMO's expert bankers are familiar with how different businesses run. |
| seg_c1_2 | unknown | M |
| seg_c1_3 | unknown | BMO |

### 1073608245839934

![1073608245839934](data/shakedown/1073608245839934/1073608245839934_card1.jpg)

- media: carousel (6 cards) | latency: 22.6s
- segments: 21 | claims: 3 | cv findings: 42
- entities: none
- routing: **deposit_account** -> FTC, Reg_DD, CFPB
- routing signal: marketing asset -> FTC; deposit product -> Reg DD; consumer financial product -> CFPB UDAAP
- semantic fallback: routing=False, sem claims=none, embedding=—
- engine: passed round 1 (1 ms) | asset defects: none
- unquotable claims (extraction gaps): ['clm_3']

| segment | role | text (first 3, OCR eyeball) |
|---|---|---|
| seg_c2_1 | headline | VALUE PACK 100 SAVINGS |
| seg_c2_2 | unknown | 280 |
| seg_c2_3 | unknown | 28 |

### 1192947802913589

![1192947802913589](data/shakedown/1192947802913589/1192947802913589_card1.jpg)

- media: carousel (4 cards) | latency: 66.5s
- segments: 25 | claims: 9 | cv findings: 90
- entities: percentage: 1
- routing: **deposit_account** -> FTC, Reg_DD, CFPB
- routing signal: marketing asset -> FTC; deposit product -> Reg DD; consumer financial product -> CFPB UDAAP
- semantic fallback: routing=False, sem claims=none, embedding=—
- engine: passed round 1 (1 ms) | asset defects: FTC5-STR-002 [medium]

| segment | role | text (first 3, OCR eyeball) |
|---|---|---|
| seg_c1_1 | unknown | High-Yield Savings |
| seg_c1_2 | headline | 3 |
| seg_c1_3 | unknown | CCBank |

### 1239989448218452

![1239989448218452](data/shakedown/1239989448218452/1239989448218452_card1.jpg)

- media: carousel (6 cards) | latency: 81.9s
- segments: 31 | claims: 0 | cv findings: 62
- entities: none
- routing: **deposit_account** -> FTC, Reg_DD, CFPB
- routing signal: marketing asset -> FTC; deposit product -> Reg DD; consumer financial product -> CFPB UDAAP
- semantic fallback: routing=False, sem claims=none, embedding=—
- engine: passed round 1 (2 ms) | asset defects: none

| segment | role | text (first 3, OCR eyeball) |
|---|---|---|
| seg_c1_1 | headline | BMO's expert bankers are familiar with how different businesses run. |
| seg_c1_2 | unknown | M |
| seg_c1_3 | unknown | BMO |

### 1297773045148944

![1297773045148944](data/shakedown/1297773045148944/1297773045148944_card1.jpg)

- media: carousel (2 cards) | latency: 65.5s
- segments: 11 | claims: 4 | cv findings: 26
- entities: fee: 2, guarantee_term: 2
- routing: **personal_loan** -> FTC, TILA, CFPB
- routing signal: marketing asset -> FTC; credit product (personal_loan) -> TILA advertising rules + CFPB
- semantic fallback: routing=False, sem claims=none, embedding=—
- engine: passed round 1 (6 ms) | asset defects: none

| segment | role | text (first 3, OCR eyeball) |
|---|---|---|
| seg_c1_1 | headline | PAY DOWN DEBT, THESMART WAY. |
| seg_c1_2 | headline | OTHERS SoFi |
| seg_c1_3 | body | High interest rates Origination & late fees Lengthy process Credit score hit just to check |

### 1322487049287816

![1322487049287816](data/shakedown/1322487049287816/1322487049287816_card1.jpg)

- media: carousel (3 cards) | latency: 103.2s
- segments: 18 | claims: 12 | cv findings: 87
- entities: amount: 18
- routing: **unknown** -> FTC
- routing signal: marketing asset -> FTC
- semantic fallback: routing=False, sem claims=none, embedding=—
- engine: passed round 1 (1 ms) | asset defects: none
- unquotable claims (extraction gaps): ['clm_3', 'clm_4']

| segment | role | text (first 3, OCR eyeball) |
|---|---|---|
| seg_c1_1 | unknown | Tilt |
| seg_c1_2 | body | Tilt can send you |
| seg_c1_3 | headline | +$400 |

### 1365822818902156

![1365822818902156](data/shakedown/1365822818902156/1365822818902156_card1.jpg)

- media: carousel (2 cards) | latency: 41.9s
- segments: 8 | claims: 4 | cv findings: 20
- entities: none
- routing: **deposit_account** -> FTC, Reg_DD, CFPB
- routing signal: marketing asset -> FTC; deposit product -> Reg DD; consumer financial product -> CFPB UDAAP
- semantic fallback: routing=False, sem claims=none, embedding=—
- engine: passed round 1 (1 ms) | asset defects: none

| segment | role | text (first 3, OCR eyeball) |
|---|---|---|
| seg_c1_1 | unknown | _ |
| seg_c1_2 | headline | V |
| seg_c1_3 | unknown | AMERICAN EXPRESS |

### 1381634810455796

![1381634810455796](data/shakedown/1381634810455796.jpg)

- media: single image | latency: 15.3s
- segments: 13 | claims: 4 | cv findings: 32
- entities: percentage: 1
- routing: **personal_loan** -> FTC, TILA, CFPB
- routing signal: marketing asset -> FTC; credit product (personal_loan) -> TILA advertising rules + CFPB
- semantic fallback: routing=False, sem claims=none, embedding=—
- engine: passed round 1 (2 ms) | asset defects: FTC5-STR-002 [medium]

| segment | role | text (first 3, OCR eyeball) |
|---|---|---|
| seg_1 | body | Rupee on time Cush. Fast. Sorted. |
| seg_2 | unknown | Low |
| seg_3 | unknown | 300 (Poor) |

### 2828127634031801

![2828127634031801](data/shakedown/2828127634031801/2828127634031801_card1.jpg)

- media: carousel (1 cards) | latency: 9.3s
- segments: 1 | claims: 0 | cv findings: 2
- entities: none
- routing: **unknown** -> FTC
- routing signal: marketing asset -> FTC
- semantic fallback: routing=False, sem claims=none, embedding=—
- engine: passed round 1 (1 ms) | asset defects: none

| segment | role | text (first 3, OCR eyeball) |
|---|---|---|
| seg_1 | unknown | VISA |
