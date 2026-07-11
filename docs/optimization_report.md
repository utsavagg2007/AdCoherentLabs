# AI Engine Optimization Report

Optimization of the NLP, CV, and rule-engine layers, driven by a
**reproducible synthetic corpus** and a **cross-validation harness** so
every change is measured on held-out data — never tuned to the 6 gold /
30 silver labels.

## Method (no overfitting)

- **`synth/generator.py`** — seeded, reproducible generator. Assembles
  schema-valid ads from *general* marketing/regulatory phrasing (not
  copied from gold/silver), with exact entity char-spans, declared claim
  types, and policy-derived routing. `generate_corpus(n, seed)` is a pure
  function; `tests/test_synth.py` guards span-exactness + reproducibility.
- **`synth/evaluate.py`** — scores the real pipeline in text mode on the
  synthetic **val** split and on **gold**/**silver** as held-out corpora,
  reusing `eval.scorer` with segment-id alignment + value-mode entities.
- **`synth/render.py` + `synth/ocr_eval.py`** — render synthetic ads to
  images with ground-truth layout, then measure OCR fidelity +
  segmentation-role recovery under preprocessing variants, with a
  device/latency benchmark (the layout-dependent objectives text mode
  cannot see).

Guardrail: an improvement is kept only when it helps the **consistently
labeled** synthetic val split (the trustworthy signal) without regressing
gold/silver. Changes that only move a real-corpus number are treated as
suspect (likely fitting a labeling quirk).

## Headline results — cross-validation (text mode)

| corpus | entities F1 | seg role_acc | claims F1 | routing F1 | product_acc |
|---|---|---|---|---|---|
| synth-val (100) | 0.994 | 0.962 | **0.943** | **1.000** | **0.910** |
| gold (6) | 0.720 | 0.667 | 0.378 | 0.952 | 0.833 |
| silver (30) | 0.390 | 0.443 | 0.205 | 0.771 | 0.633 |

Phase-2 deltas on the trustworthy synth-val signal:

| metric | before | after | change |
|---|---|---|---|
| claims precision | 0.910 | 0.957 | **+0.047** (recall held 0.929) |
| routing F1 | 0.961 | 1.000 | **+0.039** |
| routing product_acc | 0.590 | 0.910 | **+0.320** |

## NLP (layers 1–2)

**Entities — multi-currency / magnitude amounts.** The `$`-only amount
pattern missed real international ads. Added `€ £ ₹ ¥` + ISO codes +
magnitude words (`₹1.5 LAKH`→150000, `$75K`→75000, `Rs. 5,000`→5000,
`5,000 USD`→5000, Indian grouping `₹5,00,000`→500000). Ablation: silver
amount **recall up** (the ₹ amounts are now caught); synth & gold amount
F1 stay 1.000. The residual silver "FPs" are duplicate mentions
(the same amount appears in headline+body+disclosure; silver labels it
once) and one OCR styled-digit fragment — not worse real extraction.

**Key finding.** The deterministic entity extractor is **near-ceiling on
consistently labeled text** (synth 0.994). Silver's low entity score is
dominated by *inter-corpus labeling conflicts*, not extraction bugs:
silver labels `4.50% APY` as `apr` while gold's documented guide labels
it `percentage`; silver never labels superlatives; some silver assets
carry unrendered `{{product.brand}}` placeholders. These are data issues,
not model errors — chasing them would be overfitting.

**Claims — precision without recall loss.** Fixed two genuine
mis-categorizations: `save/savings` was in the *comparative* trigger (it
is a performance/pricing claim, not a comparison) and bare `100%` was in
*performance*; tightened bare `than` to require a rival
(`than any/every/other/…`) so "less than 5 minutes" no longer fires.
Ablation: synth-val claims **P 0.910→0.957, recall held at 0.929**.

**Routing product classifier — +0.32 product_acc.** Added generalizable
product synonyms (auto: *car/vehicle financing, refinance your car*;
mortgage: *home loan/financing* — and **removed** bare `refinanc` so
"refinance your car" no longer routes mortgage; card: *rewards/balance
transfer/intro APR*; bnpl: *pay in 4/installments*; deposit: *money
market/CD*; crypto: *web3/staking/digital asset*). Validated on gold
(mortgage asset still routes mortgage) and silver (no regression).

**Segmentation.** Role classification on real ads is **layout-driven**
(headline = big text at top, fine_print = small text). Text mode strips
that signal, so text-mode role accuracy is layout-bounded; the honest
instrument is the render→OCR harness below, where font size and position
exist.

## CV (layer 1) — OCR fidelity, preprocessing, device

_GPU reality:_ the only device is a 2 GB NVIDIA MX450, and the installed
`torch`/`paddle` are **CPU-only builds** (`paddle.is_compiled_with_cuda()
== False`). GPU OCR would require a CUDA `paddlepaddle-gpu` build, which
is marginal on 2 GB VRAM for this workload (deterministic rules + OCR +
MiniLM inference). The ablation therefore benchmarks CPU honestly and
adds a **latency control** (downscaling oversized screenshots) rather than
forcing a fragile CUDA reinstall that would not pay off.

**Preprocessing ablation (5 real gold screenshots, size-capped to 1300px):**

| variant | word_recall | char_sim | role_acc | over_seg | s/asset |
|---|---|---|---|---|---|
| **raw** | **0.994** | 0.670 | 0.667 | 1.58 | 19.3 |
| otsu | 0.831 | 0.730 | 0.769 | 1.55 | 17.1 |

**Useful negative result:** Otsu binarization *hurts* OCR word recall on
real ad screenshots (0.994 → 0.831) — it destroys anti-aliased and
colored text. Classic binarization/denoising helps *scanned/noisy
documents*, not *born-digital creatives*. The pipeline already OCRs
**raw**, which is optimal here (99.4% word recall), so the correct action
is **not** to add a binarization step. (`otsu`'s higher char_sim/role_acc
is an artifact of emitting fewer, cleaner lines while dropping ~16% of
words — the wrong trade for a recall-first layer.)

**Latency + device.** ~19 s/asset on CPU even at 1300px confirms the
review's 9–135 s concern. The measured lever is **downscaling oversized
screenshots** before OCR: capping the longest side to ~1300–1600px
retained 0.994 word recall while cutting work. Added as an opt-in
`max_dim` to `cv.ocr.run_ocr_local` (default off, so the validated
pipeline is unchanged; enable for latency). GPU would help latency, but
only with a CUDA `paddlepaddle-gpu` build and more than 2 GB VRAM —
neither available here.

## Rule engine (layer 4)

The engine's guarantees are bounded by upstream recall (its own
`ALL-GRD-007` flags extraction gaps). The phase-1 fixes (dollar-amount
pricing trigger, disclosure-misrole suppression, APY convention) and
phase-2 claim/entity/routing gains directly increase what the checks can
act on. ECOA/FDIC now route, so `checks_regb`/`checks_fdic328` are
genuinely exercisable. The mutation matrix + determinism guard remain
green (`eval/test_rule_engine.py`).

## Reproduce

```bash
python -m synth.generator --n 400 --seed 7 --out data/synth --noise   # corpus
python -m synth.evaluate  --n 400 --seed 7 --entities                 # NLP CV
python -m synth.ocr_eval  --source gold                               # OCR/CV
python -m pytest tests/test_synth.py -q                               # guards
```
