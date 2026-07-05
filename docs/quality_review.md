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
manually and compare verdicts. Run `python run_batch.py` to generate images for all payloads,
then fill in the Human verdict / Notes columns below by opening each R2 URL in
`outputs/batch_summary.json` and looking at it.

### Scoring Rubric (Human)

Score each image as PASS or FAIL based on:
- The hero food subject is clearly visible and matches the campaign item
- No garbled, misspelled, or hallucinated text appears in the food scene background
- The restaurant atmosphere is recognizable (warm festive for Mijo's; refined dark for Flights)
- Image quality is suitable for an email marketing campaign

### Calibration Results

Auto columns are pulled directly from `outputs/batch_summary.json` (real generation run,
2026-07-05, after the compositor redesign described below). Human verdict is a real
visual review of each downloaded image (`outputs/*.jpg`), not a placeholder.

| Payload | Auto verdict | Auto CLIP | Auto brand/5 | Human verdict | Notes |
|---------|-------------|-----------|--------------|---------------|-------|
| mijos_1_spotlights | PASS | 0.284 | 5/5 | PASS | Margarita pitcher + taco spread scene reads as a weekend fiesta; logo badge crisp |
| mijos_2_menu_items | PASS | 0.317 | 5/5 | PASS | Fish taco is the unmistakable hero; price/name legible over scrim |
| mijos_3_deals | PASS | 0.294 | 4/5 | PASS | Multiple taco plates convey BOGO value; offer wraps cleanly across two lines |
| mijos_4_menu_items_alt | PASS | 0.307 | 5/5 | PASS | Passed on retry 1 (first attempt flagged text in the food scene, not an allergen leak) |
| flights_1_spotlights | PASS | 0.260 | 5/5 | PASS | Wine + charcuterie atmosphere shot; logo card reads clearly against navy header |
| flights_2_menu_items | PASS | 0.238 | 5/5 | PASS | Beer + wine pairing clearly matches item name; price prominent |
| flights_3_deals | PASS | 0.246 | 5/5 | PASS | Cocktail spread conveys "25% off all cocktails" value; no orphaned text |

**Agreement rate:** 7/7 (100%) -- automated gate matches human judgment on this run.

**What changed since the 2026-07-03 run:** that run used a single hardcoded left-panel
layout (42-48% opaque brand-color block) for every campaign type, and no real restaurant
logo -- only typed restaurant-name text. Images across campaign types looked visually
identical aside from panel width. The current run uses per-campaign-type layouts (header
bar + full-bleed photo + gradient caption for Menu Items/Deals; refined panel for
Spotlights) and composites each restaurant's real sourced logo. See README
"Campaign Layouts & Brand Identity" for details.

### Follow-up correction: Mijo's brand color (2026-07-05, same day)

Human review caught that Mijo's header/panel color (`#C8410A`, orange/terracotta) didn't
match the restaurant's actual logo, which is green. Root cause and fix are documented in
`docs/brand_notes.md`; short version: the original color was extracted from website
*photography*, not the logo itself. Corrected to `#4D6D22` (primary) / `#DCCEC4` (accent),
derived directly from the logo file. All 4 Mijo's payloads were regenerated:

| Payload | Auto verdict | Auto CLIP | Auto brand/5 | Human verdict | Notes |
|---------|-------------|-----------|--------------|---------------|-------|
| mijos_1_spotlights | PASS | 0.308 | 5/5 | PASS | Green panel now reads as a clear match to the logo; margarita pitcher scene unchanged in quality |
| mijos_2_menu_items | PASS | 0.318 | 5/5 | PASS | Passed on retry 1 (first attempt flagged model-rendered price/name text in the scene, not a color issue) |
| mijos_3_deals | PASS | 0.295 | 5/5 | PASS | Clean on first attempt; offer wraps correctly across two lines |
| mijos_4_menu_items_alt (attempt 1) | FAIL | 0.299 | 5/5 | -- | Rejected on both retries: gpt-image-2 kept rendering stray text in the food scene background despite the "no text" prompt mandate. Not related to the color fix -- this is the pre-existing image-model text-hallucination risk the QA gate exists to catch. Illustrates the gate doing its job: a flawed image was caught and not silently shipped. |
| mijos_4_menu_items_alt (attempt 2, re-run) | PASS | 0.322 | 5/5 | PASS | Clean on first attempt (each run independently samples a new background) |

Corrected images downloaded to `outputs/mijos_*_green.jpg`. New R2 URLs recorded in
`outputs/mijos_green_rerun.json` and `outputs/mijos_4_retry2.json`. Final state: 4/4
Mijo's payloads passing QA with the corrected green theme.

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
