# Gold Label Format

One JSON file per asset in `data/gold/*.json`. Each file is a hand-labeled
`AssetRepresentation` (see `schema.py`) — the same contract the CV+NLP layers
emit, so gold and prediction are directly comparable field-for-field.

Validate a label before committing it:

```bash
python -c "import json, schema; schema.AssetRepresentation.model_validate(json.load(open('data/gold/my_label.json'))); print('valid')"
```

## Template

```json
{
  "asset_id": "asset_0001",

  "segments": [
    {
      "segment_id": "seg_1",
      "text": "Earn 4.50% APY on every dollar",
      "role": "headline",
      "source": "html",
      "bbox": {"x": 0.05, "y": 0.08, "width": 0.9, "height": 0.12},
      "ocr_confidence": null
    },
    {
      "segment_id": "seg_2",
      "text": "APY accurate as of 06/01/2026. Rates may change. Member FDIC.",
      "role": "disclosure",
      "source": "html",
      "bbox": {"x": 0.05, "y": 0.9, "width": 0.9, "height": 0.05},
      "ocr_confidence": null
    }
  ],

  "entities": [
    {
      "entity_id": "ent_1",
      "entity_type": "percentage",
      "raw_text": "4.50% APY",
      "normalized_value": 4.5,
      "segment_id": "seg_1",
      "char_span": {"start": 5, "end": 14}
    }
  ],

  "claim_candidates": [
    {
      "claim_id": "clm_1",
      "claim_type": "pricing",
      "text": "Earn 4.50% APY on every dollar",
      "segment_id": "seg_1",
      "char_span": {"start": 0, "end": 30},
      "entity_ids": ["ent_1"],
      "pattern_id": null
    }
  ],

  "cv_findings": [
    {
      "finding_id": "cvf_1",
      "measurement": "contrast_ratio",
      "value": 4.8,
      "segment_id": "seg_2",
      "related_segment_id": null,
      "method": "wcag2_relative_luminance"
    }
  ],

  "routing": {
    "product_type": "deposit_account",
    "frameworks": ["Reg_DD", "FTC"],
    "signal": "APY rate in headline + deposit product -> Reg DD; marketing claim -> FTC"
  },

  "provenance": {
    "cv_version": "gold",
    "nlp_version": "gold",
    "ruleset_hash": "gold",
    "timestamp": "2026-07-03T00:00:00Z"
  }
}
```

## Field-by-field labeling rules

### Segments
- `segment_id`: `seg_<n>`, unique within the asset. Every other list references these.
- `text`: **verbatim** — char spans index into this exact string. Do not normalize whitespace or fix typos in the source asset.
- `role`: one of `headline | body | disclosure | fine_print | cta | legal | unknown`. When torn between `disclosure` and `fine_print`: `disclosure` is content required by regulation; `fine_print` is any small/de-emphasized text.
- `source`: `text | html | ocr`. Set `ocr_confidence` (0–1) only for `ocr`.
- `bbox`: normalized [0,1] coordinates, origin top-left; `x+width <= 1`, `y+height <= 1`. Use `null` for non-visual assets.

### Entities
- `entity_type`: `apr | fee | rate | amount | percentage | superlative | endorsement_marker | optout_marker | guarantee_term | time_period`.
- `char_span`: half-open `[start, end)` into the segment's `text`; `text[start:end]` must equal `raw_text` exactly. Use Python slicing to verify.
- `normalized_value`: percentages/APR/rate as the number (`4.5` for "4.50%"), fee/amount in USD, time_period in days. `null` for non-numeric types (superlative, endorsement_marker, optout_marker, guarantee_term).

### Claim candidates
- Label **every** span a reasonable compliance reviewer would want examined — the layer is scored with a high-recall bias, so over-label rather than under-label.
- `claim_type`: `performance | comparative | guarantee | endorsement | pricing | risk_free`.
- `entity_ids`: every entity the claim rests on; `[]` if none.
- `pattern_id`: `null` in gold labels (it records which extractor pattern fired; gold has none).

### CV findings
- Numbers only, never judgments. Bounds: `contrast_ratio` in [1, 21], `text_height_percent` in [0, 100], `disclosure_proximity` >= 0, `marker_presence` exactly 0.0 or 1.0.
- `disclosure_proximity`: `segment_id` = the claim segment, `related_segment_id` = the disclosure segment measured against it.
- Omit the list (or use `[]`) for non-visual assets.

### Routing
- `frameworks`: **all** frameworks that plausibly apply (at least one; FTC applies to nearly all marketing). Values: `FTC | CFPB | TILA | SEC | FINRA | CAN-SPAM | ECOA | FCRA | Reg_DD | TCPA` — exact strings, note `CAN-SPAM` hyphen and `Reg_DD` underscore.
- `signal`: one human-readable sentence explaining *why* — this is the audit trail.

### Provenance
- Use the literal string `"gold"` for `cv_version`, `nlp_version`, `ruleset_hash`, and the labeling date as `timestamp`. This marks the record as hand-labeled, not system output.

## Defaults for optional fields

The eval runner tolerates omitted optional fields. If a gold file omits
`entities`, `claim_candidates`, or `cv_findings`, they default to `[]`
(meaning "the asset truly contains none" — not "unlabeled"). `bbox`,
`ocr_confidence`, `pattern_id`, `related_segment_id`, and `method` default
to `null`. `segments`, `routing`, `asset_id` are required.
