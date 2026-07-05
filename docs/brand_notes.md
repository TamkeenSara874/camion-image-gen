# Restaurant Brand Notes

Brand data extracted from live restaurant websites and stored in `config/restaurant_brands.json`.
These notes document the research rationale behind each brand's configuration.

---

## Restaurant 2 — Mijo's Taqueria

**Website:** https://www.mijostaqueria.com
**Cuisine:** Mexican

### Brand Identity

Mijo's Taqueria presents itself as a vibrant, festive neighborhood taqueria with strong roots in
Mexican folk culture. The restaurant's visual language centers on warmth, community, and authentic
street-food energy translated into a sit-down dining experience.

### Visual Style

- Rustic wood textures and terracotta tile patterns
- Hand-painted folk art motifs (papel picado, Talavera-inspired patterns)
- Warm, saturated lighting with earthy orange-red dominance
- Colorful but grounded — festive without being garish

### Brand Colors

| Role | Hex | Usage |
|------|-----|-------|
| Primary | `#4D6D22` | Header bar / panel backgrounds, dominant overlays |
| Accent | `#DCCEC4` | Price highlights, offer call-outs |
| Text on primary | `#FFFFFF` | All overlay text on primary backgrounds |

**Revision note:** the original values (`#C8410A` terracotta-red / `#F5A623` amber) were
extracted from the restaurant's website photography (`scripts/extract_brand_colors.py --url`),
which pulled warm tones from food imagery rather than the actual logo. The logo itself (the
sombrero mascot badge, `config/logos/2.png`) is green, not orange or red — so the compositor's
header/panel color didn't match the brand mark shown right next to it. Corrected by extracting
the real palette from the logo file (`scripts/extract_brand_colors.py --logo-path config/logos/2.png`),
which returns `#3B3E39` (near-black charcoal outline), `#8CC143` (vivid green), `#DCCEC4`
(mascot skin tone), `#708D47` (olive green) as the dominant swatches.

`#8CC143` (the most prevalent green) is too light to use directly as a large-area fill with
white overlay text — contrast against white is only ~1.4:1, well under the ~4.5:1 target.
`#4D6D22` is the same hue (~85°) at a lightness adjusted for legibility (contrast ~5.9:1 against
white, vs. ~5.0:1 for the old orange). `#DCCEC4` (the mascot's actual skin tone) is used as
accent since it reads clearly on both the black photo scrim (Menu Items/Deals) and the green
panel itself (Spotlights) — the vivid green swatch, tried first, had good contrast against the
scrim but poor contrast against the new green panel (green-on-green).

### Prompt Engineering Notes

- Hero subjects: tacos, margaritas, chile-spiced meats, guacamole, elotes
- Atmosphere descriptors: warm candlelight, terracotta surfaces, hanging paper lanterns, colorful tiles
- Lighting: warm-toned tungsten key light, golden fill, rich shadow detail
- Composition anchor: rustic wooden table surface with scattered lime wedges or salt rim
- Color grade instruction: "palette anchored in #4D6D22 with #DCCEC4 accents, warm adobe shadow detail"

### Logo

`config/logos/2.png` — the real logo actually rendered in Mijo's site header (sombrero
mascot badge), sourced via `scripts/fetch_brand_logo.py`. This is a static asset, never
model-generated: the image model is explicitly instructed to draw no logos (see
`prompts/*.yaml`), because a diffusion model has no pixel-exact memory of a specific small
business's mark and would otherwise hallucinate a plausible-looking fake. The compositor
pastes this file directly onto a white rounded card in the header bar / panel badge.

---

## Restaurant 4 — Flights Restaurant

**Website:** https://www.flightsrestaurant.com
**Cuisine:** American Eclectic

### Brand Identity

Flights Restaurant is a contemporary, wine-forward dining concept positioned at the upscale-casual
tier. The name refers to tasting flights — small portions of multiple items served together — which
reflects the restaurant's philosophy of exploration and variety. The visual identity is refined and
editorial, favoring restraint over exuberance.

### Visual Style

- Clean architectural lines and negative space
- Deep navy/midnight blue with warm gold accents
- Elegant plating on neutral ceramic ware
- Low-key, intimate lighting — dark backgrounds with a single highlight on the subject
- Minimal surface clutter; hero subjects are isolated and given breathing room

### Brand Colors

| Role | Hex | Usage |
|------|-----|-------|
| Primary | `#1A2744` | Strip backgrounds, dark overlays |
| Accent | `#C9A96E` | Price text, highlights, warm contrast elements |
| Text on primary | `#FFFFFF` | All overlay text on dark backgrounds |

The primary `#1A2744` is a deep navy extracted from the dominant dark tones in Flights' website
header and imagery. The accent `#C9A96E` is a warm champagne-gold matching the wine glass
reflections and accent lighting seen throughout the restaurant's photography.

### Prompt Engineering Notes

- Hero subjects: wine flights, artisan cocktails, composed entreés, charcuterie boards
- Atmosphere descriptors: polished dark wood surfaces, candlelit intimacy, stemware in soft focus
- Lighting: single-source soft-box key light from upper-left, dark background, no fill
- Composition anchor: dark slate or marble surface, minimal props
- Color grade instruction: "palette anchored in #1A2744 with #C9A96E accents, deep jewel-tone shadows"

### Logo

`config/logos/4.png` — the real "FLIGHTS Restaurant & Bar" wordmark rendered in the site
header, sourced via `scripts/fetch_brand_logo.py`. Same rule as Mijo's: never model-generated,
always the static asset, composited on a white card for legibility against the navy brand color.

---

## Adding a New Restaurant

1. Add a JSON object to `config/restaurant_brands.json` with a new integer key (restaurant ID).
2. Run `python scripts/fetch_brand_logo.py --url <website_url> --restaurant-id <id>` FIRST to
   source the real logo into `config/logos/<id>.png`. Every restaurant in this system is hosted
   on AIO's own site builder, so this works automatically for any future AIO restaurant client
   without modification (see the script's docstring for the fallback path for non-AIO sites).
3. Run `python scripts/extract_brand_colors.py --logo-path config/logos/<id>.png` to extract the
   brand palette **from the logo itself**, not `--url` (website photography can produce a
   palette that doesn't match the actual logo at all — see the Mijo's revision note above for
   exactly this failure mode). Pick primary/accent from the printed swatches, verifying contrast
   against white text (target >=4.5:1 for primary; check both against a black photo scrim and
   against the primary panel color for accent, since accent renders on both).
4. Paste the chosen colors and the printed `logo_path` into the new JSON entry.
5. No code changes required. The brand mapper loads all entries at startup via `@lru_cache`.

If step 3 is skipped or the logo isn't sourced yet, `logo_path` can be omitted entirely (or left
pointing at a file that doesn't exist yet) — the compositor degrades gracefully to a typed
restaurant-name badge instead of crashing or inventing a logo.

Required fields: `restaurant_name`, `cuisine_type`, `brand_theme`, `visual_style`,
`website_url`, `brand_colors` (keys: `primary`, `accent`, `text_on_primary`), `currency_symbol`.
Optional: `logo_path` (relative to repo root).
