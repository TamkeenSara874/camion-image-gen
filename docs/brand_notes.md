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
| Primary | `#C8410A` | Strip backgrounds, CTA buttons, dominant overlays |
| Accent | `#F5A623` | Price highlights, secondary call-outs |
| Text on primary | `#FFFFFF` | All overlay text on primary backgrounds |

The primary `#C8410A` is a deep terracotta-red derived from the dominant warm tones on the
restaurant's homepage imagery. The accent `#F5A623` is a warm amber that echoes the golden
edges visible in food photography on the site.

### Prompt Engineering Notes

- Hero subjects: tacos, margaritas, chile-spiced meats, guacamole, elotes
- Atmosphere descriptors: warm candlelight, terracotta surfaces, hanging paper lanterns, colorful tiles
- Lighting: warm-toned tungsten key light, golden fill, rich shadow detail
- Composition anchor: rustic wooden table surface with scattered lime wedges or salt rim
- Color grade instruction: "palette anchored in #C8410A with #F5A623 accents, warm adobe shadow detail"

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

---

## Adding a New Restaurant

1. Add a JSON object to `config/restaurant_brands.json` with a new integer key (restaurant ID).
2. Run `python scripts/extract_brand_colors.py --url <website_url>` to extract dominant hex colors.
3. Paste the extracted colors into the new JSON entry.
4. No code changes required. The brand mapper loads all entries at startup via `@lru_cache`.

Required fields: `restaurant_name`, `cuisine_type`, `brand_theme`, `visual_style`,
`website_url`, `brand_colors` (keys: `primary`, `accent`, `text_on_primary`), `currency_symbol`.
