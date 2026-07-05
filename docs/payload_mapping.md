# Payload Field Mapping

Documents how each field in the `POST /api/generate-image` request payload is consumed
by the seven-stage pipeline.

---

## Top-Level Fields

| Field | Type | Required | Pipeline Stage | How It Is Used |
|-------|------|----------|---------------|----------------|
| `campaign_type` | string | yes | Stage 1, 3, 4, 6 | Validated against `CAMPAIGN_REGISTRY`; selects YAML prompt template; selects compositor layout (header+full-bleed for Menu Items/Deals, side panel for Spotlights) |
| `campaign_goals` | string | yes | Stage 3, 4 | Mapped through `_GOAL_DIRECTIVES` in `campaign_parser.py` to an explicit visual-composition instruction (`goal_direction`), then injected into the prompt alongside the raw label |
| `campaign_audiences` | list[string] | yes | Stage 3, 4 | Mapped through `_AUDIENCE_TONES` (priority order: Lost > Occasional > Regular > New/Potential) to an explicit tone instruction (`audience_tone`), then injected into the prompt |
| `campaign_guest_tags` | list[string] | no | Stage 3 | Allergen terms filtered out (Stage 3); remaining tags passed to Stage 4 as atmosphere hints |
| `campaign_vars` | object | yes | Stage 1, 3, 4, 6 | Validated by campaign-type schema; parsed into `CampaignContext`; drives compositor overlay content |
| `cta` | boolean | no | Stage 6 | When `true` AND `CTA_OVERLAY_ENABLED=true` in settings, draws a CTA pill. Default: no CTA rendered |
| `channels` | list[string] | yes | Stage 3 | Drives default orientation mapping if `orientation` is omitted; currently Email is primary |
| `campaign_brand_voices` | string | yes | Stage 4 | Injected into prompt as tone/style instruction |
| `restaurantId` | integer | yes | Stage 2, 4, 6 | Looks up `RestaurantBrand` (colors, theme, style, `logo_path`); hex colors and the real logo file flow into the compositor; hex colors also flow into the prompt |
| `orientation` | string | no | Stage 3, 5 | Maps to image size (`1536x1024`, `1024x1536`, `1024x1024`); overrides channel default if set |
| `custom_prompt` | string | no | Stage 3, 4 | Sanitized in Stage 3; appended to the generated image prompt in Stage 4 |

---

## `campaign_vars` by Campaign Type

### Spotlights

| Field | Required | Used By |
|-------|----------|---------|
| `name` | yes | Stage 4 (main_title), Stage 6 (name strip) |
| `description` | yes | Stage 4 (main_offer, atmosphere context) |
| `spotlight_type` | no | Stage 4 (event/chef/seasonal/story context hint) |

### Menu Items

| Field | Required | Used By |
|-------|----------|---------|
| `name` | yes | Stage 4 (main_title, hero subject), Stage 6 (name strip) |
| `description` | yes | Stage 4 (scene description context) |
| `price` | no | Stage 6 (price overlay, right-aligned in strip) |
| `item_category` | no | Stage 4 (food category context) |
| `item_menu` | no | Stage 4 (menu section context) |

### Deals

| Field | Required | Used By |
|-------|----------|---------|
| `name` | yes | Stage 4 (main_title), Stage 6 (name strip) |
| `description` | no | Stage 4 (deal description) |
| `deal_type` | yes | Stage 4 (deal framing context) |
| `deal_type_vars` | yes | Stage 4 (specific offer details injected into prompt) |
| `start_date` | no | Stage 4 (temporal context if present) |
| `end_date` | no | Stage 4 (urgency framing if present) |
| `promo_code` | no | Stage 4 (included in alt_text if present; never rendered in image) |

---

## Field Flow Through the Pipeline

```
payload.restaurantId
    Stage 2: RestaurantBrand (name, colors, theme, style)
         |
         v
payload.campaign_type + payload.campaign_vars
    Stage 1: Schema validation
    Stage 3: CampaignContext (sanitized, normalized, allergen-filtered)
         |
         v
CampaignContext + RestaurantBrand
    Stage 4: ImagePromptResponse (final_image_prompt, alt_text, negative_prompt)
         |
         v
final_image_prompt
    Stage 5: SynthesisResult (image_bytes, model_used, attempt_number)
         |
         v
image_bytes + CampaignContext (name, price, cta_text) + RestaurantBrand.logo_path
    Stage 6: CompositeResult (image_bytes with header/panel logo + text overlay, mime_type=image/jpeg)
         |
         v
composite_bytes
    Upload to R2  ||  Stage 7 QA vision scoring
         |
         v
ImageGenerationResponse (image_url, metrics, qa_scores, alt_text)
```

---

## Fields That Never Reach the Image Model

These fields are explicitly kept out of the image generation prompt to prevent the model
from rendering them as visible text (which would be unreliable and potentially incorrect):

- `price` — rendered only by Stage 6 Pillow compositor with the correct value
- `promo_code` — included in alt_text only; never drawn in the image
- `cta` — compositor flag; CTA text drawn programmatically if enabled
- `campaign_goals` / `campaign_audiences` — mapped to explicit `goal_direction` /
  `audience_tone` strings and given to the LLM as composition/tone guidance; never a
  literal visual instruction the model renders as text
- restaurant logo — never described to the image model (every prompt template ends with
  "no logos anywhere in the scene"); the real logo file is pasted by Stage 6 instead, since
  a diffusion model has no pixel-exact memory of a specific restaurant's mark

---

## Sanitization (Stage 3)

The following user-supplied fields are sanitized before interpolation into prompts:

- `campaign_vars.name`
- `campaign_vars.description`
- `custom_prompt`

Sanitization removes prompt injection patterns (e.g., "ignore previous instructions"),
strips HTML/XML tags, and escapes curly braces that would break f-string templates.
