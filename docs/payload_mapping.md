# Payload Field Mapping

Documents how each field in the `POST /api/generate-image` request payload is consumed
by the seven-stage pipeline.

---

## Top-Level Fields

| Field | Type | Required | Pipeline Stage | How It Is Used |
|-------|------|----------|---------------|----------------|
| `campaign_type` | string | yes | Stage 1, 3, 4 | Validated against `CAMPAIGN_REGISTRY`; selects YAML prompt template; drives compositor layout |
| `campaign_goals` | string | yes | Stage 4 | Injected into prompt template as campaign objective context |
| `campaign_audiences` | list[string] | yes | Stage 4 | Injected into prompt as audience descriptor; influences tone of background scene |
| `campaign_guest_tags` | list[string] | no | Stage 3 | Allergen terms filtered out (Stage 3); remaining tags passed to Stage 4 as atmosphere hints |
| `campaign_vars` | object | yes | Stage 1, 3, 4, 6 | Validated by campaign-type schema; parsed into `CampaignContext`; drives compositor overlay content |
| `cta` | boolean | no | Stage 6 | When `true` AND `CTA_OVERLAY_ENABLED=true` in settings, draws a CTA strip. Default: no CTA rendered |
| `channels` | list[string] | yes | Stage 3 | Drives default orientation mapping if `orientation` is omitted; currently Email is primary |
| `campaign_brand_voices` | string | yes | Stage 4 | Injected into prompt as tone/style instruction |
| `restaurantId` | integer | yes | Stage 2, 4, 5 | Looks up `RestaurantBrand` (colors, theme, style); hex colors flow into prompt and compositor |
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
image_bytes + CampaignContext.overlay_fields (name, price, cta_text)
    Stage 6: CompositeResult (image_bytes with text overlay, mime_type=image/jpeg)
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
- `campaign_goals` — context for prompt tone only; not a visual instruction

---

## Sanitization (Stage 3)

The following user-supplied fields are sanitized before interpolation into prompts:

- `campaign_vars.name`
- `campaign_vars.description`
- `custom_prompt`

Sanitization removes prompt injection patterns (e.g., "ignore previous instructions"),
strips HTML/XML tags, and escapes curly braces that would break f-string templates.
