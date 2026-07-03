# Quality Review

Documents the automated QA gate design and its calibration against human judgment.

---

## Automated QA Gate

The pipeline runs a two-tier QA check on every generated image before returning a response.

### Tier 0 — CLIP Item-Alignment Score

Model: ViT-B/32 (open_clip, pretrained="openai")
Input: raw synthesis bytes (before text overlay), item text = `"{name} {description}"`
Output: cosine similarity score in range [-1, 1]; food images typically score 0.15-0.35

Pass threshold: `clip_score >= 0.20`

CLIP provides a fast, free, deterministic signal that the generated scene contains the correct
food subject. It does not share failure modes with the image generation model, avoiding
correlated blind spots from using OpenAI to evaluate its own output.

### Tier 1 — OCR Allergen Check

Tool: pytesseract (local, CPU, deterministic)
Input: raw synthesis bytes
Check: case-insensitive intersection of extracted text with `ALLERGEN_SET`

```python
ALLERGEN_SET = {
    "milk", "eggs", "wheat", "sesame", "shellfish",
    "tree nuts", "peanuts", "soy", "fish", "gluten",
}
```

Pass condition: none of the allergen words appear in the OCR output.

This check is deterministic — the same image produces the same result every run.
It is free and does not require an API call.

### Tier 2 — Vision QA (gpt-4.1-mini)

Model: gpt-4.1-mini (detail=high)
Input: final composite image (after text overlay)
Output: JSON with `stray_model_text`, `brand_fidelity_score` (1-5), `composition_score` (1-5), `issues`

Pass condition:
```
NOT stray_model_text
AND brand_fidelity_score >= 4  (configurable via QA_BRAND_FIDELITY_THRESHOLD)
```

The composition score is logged but does not affect the pass/fail verdict. It is included
for trend analysis across batch runs.

### Combined Pass Logic

```python
qa_passed = (
    ocr_passed                       # Tier 1
    and not stray_model_text         # Tier 2
    and brand_fidelity_score >= 4    # Tier 2
)
```

CLIP failure is a soft signal — it triggers a synthesis retry rather than a hard rejection,
because CLIP has limited semantic depth for food-specific vocabulary.

---

## Retry Routing

When QA fails, the pipeline classifies the failure before retrying:

| Category | Condition | Retry Action |
|----------|-----------|-------------|
| SYNTHESIS | stray text, OCR fail, or CLIP < 0.20 | Re-run Stages 4+5+6 with feedback suffix |
| COMPOSITOR | text truncated, no synthesis fail | Re-run Stage 6 only (cheaper) |
| BOTH | text truncated AND synthesis fail | Re-run Stages 4+5+6 |

Default `QA_RETRY_LIMIT=2`. After the limit, the image is returned with `qa_passed=false`.

---

## Human Calibration

To calibrate the automated gate against human judgment, score a sample of generated images
manually and compare verdicts. Run `python run_batch.py` to generate images for all 6
payloads, then fill in the table below.

### Scoring Rubric (Human)

Score each image as PASS or FAIL based on:
- The hero food subject is clearly visible and matches the campaign item
- No garbled, misspelled, or hallucinated text appears in the food scene background
- The restaurant atmosphere is recognizable (warm festive for Mijo's; refined dark for Flights)
- Image quality is suitable for an email marketing campaign

### Calibration Results

| Payload | Auto verdict | Auto CLIP | Auto brand/5 | Human verdict | Notes |
|---------|-------------|-----------|--------------|---------------|-------|
| mijos_1_spotlights | | | | | |
| mijos_2_menu_items | | | | | |
| mijos_3_deals | | | | | |
| flights_1_spotlights | | | | | |
| flights_2_menu_items | | | | | |
| flights_3_deals | | | | | |

**Agreement rate:** X/6 (fill in after calibration)

### Interpretation

- 6/6 agreement: gate is well-calibrated; thresholds are appropriate
- 4-5/6 agreement: acceptable; review disagreements to tune thresholds
- Below 4/6: review CLIP threshold (0.20) and brand fidelity threshold (4/5)

Common disagreements to watch for:
- Auto=FAIL, Human=PASS: CLIP threshold too strict for abstract food items
- Auto=PASS, Human=FAIL: stray text missed by gpt-4.1-mini vision (try detail=high)

---

## Configuration

| Setting | Default | Effect |
|---------|---------|--------|
| `QA_ENABLED` | `true` | Disable to skip all QA checks |
| `QA_BRAND_FIDELITY_THRESHOLD` | `4` | Minimum brand score to pass (1-5) |
| `QA_RETRY_LIMIT` | `2` | Max regeneration attempts on failure |
| `CLIP_THRESHOLD` | `0.20` (code constant) | Minimum CLIP score for soft pass |
