from __future__ import annotations

import os
import time

import requests
import streamlit as st
from dotenv import load_dotenv

load_dotenv()


API_URL = os.getenv("API_URL", "http://localhost:8010")
API_TOKEN = os.getenv("API_BEARER_TOKEN", "")

RESTAURANTS: dict[int, str] = {
    2: "Mijo's Taqueria",
    4: "Flights Restaurant",
}

CAMPAIGN_TYPES = ["Spotlights", "Menu Items", "Deals"]

CAMPAIGN_TYPE_CAPTIONS = {
    "Spotlights": "Feature an event, chef, or seasonal story",
    "Menu Items": "Showcase a specific dish or drink",
    "Deals": "Promote a discount, BOGO, or offer",
}

# Matches the four campaign_goals values named in the task brief exactly --
# each maps to a distinct visual-direction instruction in
# stages/campaign_parser.py's _GOAL_DIRECTIVES (e.g. "Increase Item Sales" ->
# focus tightly on the item as the hero subject).
GOAL_OPTIONS = [
    "Increase Online Orders",
    "Increase Item Sales",
    "Increase Deal Sales",
    "Increase Guest Visits",
]

GOAL_CAPTIONS = {
    "Increase Online Orders": "Orderable, action-driven shot",
    "Increase Item Sales": "Item is the unmistakable hero subject",
    "Increase Deal Sales": "Makes the offer's value obvious",
    "Increase Guest Visits": "Emphasizes the in-restaurant experience",
}

# Sensible default goal per campaign type; user can override.
_DEFAULT_GOAL_BY_TYPE = {
    "Spotlights": "Increase Guest Visits",
    "Menu Items": "Increase Item Sales",
    "Deals": "Increase Deal Sales",
}

# Matches the audience segments named in the task brief exactly.
AUDIENCE_OPTIONS = ["New", "Potential", "Occasional", "Regular", "Lost"]

# Context tags from the task brief's examples, plus the allergen words real
# payloads deliberately include (e.g. Flights sends Milk/Wheat/Eggs) so the
# Stage 3 allergen filter has something to actually filter in a demo.
TAG_OPTIONS = [
    "Cocktail", "Wine", "Beer", "Chicken", "Spicy", "Dinner", "Lunch",
    "Milk", "Eggs", "Wheat", "Sesame", "Shellfish", "Tree Nuts", "Peanuts", "Soy", "Fish",
]

PLATFORM_OPTIONS = ["website", "kiosk", "qr", "pos"]

# The deal_type values the form supports, with the deal_type_vars shape each
# one really uses. "Free gift with purchase" and "Buy this, get that" match
# the task brief's sample payloads exactly; "% off" was added later and isn't
# schema-constrained on the backend (DealsVars.deal_type is a free string),
# so its shape here is just a reasonable, self-consistent choice.
DEAL_TYPES = ["Free gift with purchase", "Buy this, get that", "% off"]

_CSS = """
<style>
    .block-container { padding-top: 2rem; }
    .stButton > button { border-radius: 6px; font-weight: 600; }
    .stForm { border: 1px solid #E8E8E8; border-radius: 8px; padding: 16px; }
    div[data-testid="stExpander"] { border: 1px solid #E8E8E8; border-radius: 6px; }
    .result-header { font-size: 18px; font-weight: 700; margin: 24px 0 8px; color: #1A1A1A; }
    .alt-text { font-size: 13px; color: #666; font-style: italic; margin-top: 6px; }
    .qa-pass { color: #1A8A3F; font-weight: 600; }
    .qa-fail { color: #C0392B; font-weight: 600; }
</style>
"""


def _init_state() -> None:
    for key, default in [
        ("campaign_type", "Menu Items"),
        ("result", None),
        ("generating", False),
    ]:
        if key not in st.session_state:
            st.session_state[key] = default


def _campaign_type_cards() -> None:
    st.markdown("**Select campaign type**")
    cols = st.columns(3)
    ct = st.session_state.campaign_type

    for col, ctype in zip(cols, CAMPAIGN_TYPES):
        with col:
            is_selected = ct == ctype
            if st.button(
                ctype,
                key=f"card_{ctype}",
                use_container_width=True,
                type="primary" if is_selected else "secondary",
            ):
                if ct != ctype:
                    st.session_state.campaign_type = ctype
                    st.session_state.result = None
                    st.rerun()
            st.caption(CAMPAIGN_TYPE_CAPTIONS[ctype])


def _spotlights_vars() -> dict:
    name = st.text_input("Spotlight name *", placeholder="Local Wednesdays")
    desc = st.text_area(
        "Description *",
        placeholder="Get 15% off on the entire menu",
        height=80,
    )
    # Real payloads send this as "type" (e.g. "Custom Spotlight"), a free-form
    # label rather than a fixed enum -- match that exactly.
    spotlight_type = st.text_input("Type", value="Custom Spotlight")
    return {"name": name, "type": spotlight_type, "description": desc}


def _menu_items_vars() -> dict:
    name = st.text_input("Item name *", placeholder="2 Carne Asada Tacos")
    desc = st.text_area(
        "Description *",
        placeholder="with Cilantro and Onions",
        height=80,
    )
    col_p, col_c = st.columns([1, 2])
    with col_p:
        price = st.text_input("Price (optional)", placeholder="5.75")
    with col_c:
        # Real payloads use free-form categories (e.g. "Street Tacos",
        # "Catering") rather than a fixed picklist.
        categories_raw = st.text_input(
            "Item categories (comma-separated)", placeholder="Street Tacos"
        )
    item_menu = st.text_input("Menu section (optional)", placeholder="Main Menu")
    categories = [c.strip() for c in categories_raw.split(",") if c.strip()]
    return {
        "name": name,
        "description": desc,
        "price": price or None,
        "item_category": categories,
        "item_menu": item_menu or None,
    }


def _deal_type_vars(deal_type: str) -> dict:
    """Structured inputs matching the exact deal_type_vars shape each real
    sample payload uses for this deal_type -- not a generic JSON blob."""
    if deal_type == "Free gift with purchase":
        col1, col2 = st.columns(2)
        with col1:
            purchase_items = st.text_input(
                "Purchase item(s) (comma-separated)", placeholder="Baja Fish Taco"
            )
            no_of_items = st.number_input("Qty to purchase", min_value=1, value=1, step=1)
        with col2:
            gift_items = st.text_input(
                "Gift item(s) (comma-separated)", placeholder="Baja Fish Taco"
            )
            gift_items_count = st.number_input("Gift quantity", min_value=1, value=1, step=1)
        return {
            "purchase_type": "Item",
            "purchase_items": [i.strip() for i in purchase_items.split(",") if i.strip()],
            "no_of_items": int(no_of_items),
            "gift_items": [i.strip() for i in gift_items.split(",") if i.strip()],
            "gift_items_count": int(gift_items_count),
        }

    if deal_type == "Buy this, get that":
        col1, col2 = st.columns(2)
        with col1:
            purchase_items = st.text_input(
                "Purchase item(s) (comma-separated)", placeholder="Around the World Flight"
            )
            purchase_item_count = st.number_input("Qty to purchase", min_value=1, value=1, step=1)
            get_type = st.selectbox("Reward type", ["Category", "Item"])
        with col2:
            get_items = st.text_input(
                "Reward item(s)/category (comma-separated)", placeholder="Signature Drink Flights"
            )
            get_items_count = st.number_input("Reward quantity", min_value=1, value=1, step=1)
            save_amount = st.text_input("Save amount", placeholder="24")
        return {
            "purchase_type": "Item",
            "purchase_items": [i.strip() for i in purchase_items.split(",") if i.strip()],
            "purchase_item_count": int(purchase_item_count),
            "get_type": get_type,
            "get_items": [i.strip() for i in get_items.split(",") if i.strip()],
            "get_items_count": int(get_items_count),
            "save_amount": save_amount or None,
            "save_amount_item": "1",
        }

    # "% off"
    col1, col2 = st.columns(2)
    with col1:
        percent = st.number_input("Percent off", min_value=1, max_value=100, value=20, step=5)
        applies_to_type = st.selectbox("Applies to", ["Entire order", "Category", "Item"])
    with col2:
        applies_to = st.text_input(
            "Item(s)/category (comma-separated, leave blank for entire order)",
            placeholder="Margaritas",
        )
        min_spend = st.text_input("Minimum spend (optional)", placeholder="20")
    return {
        "percent": int(percent),
        "applies_to_type": applies_to_type,
        "applies_to": [i.strip() for i in applies_to.split(",") if i.strip()],
        "min_spend": min_spend or None,
    }


def _deals_vars(deal_type: str) -> dict:
    name = st.text_input("Deal name *", placeholder="Buy 1 Get 1 Free test")
    desc = st.text_area(
        "Description (optional)",
        placeholder="Buy 1 Baja Fish Taco and get one free!",
        height=68,
    )
    st.caption(f"Deal variables — {deal_type}")
    deal_vars = _deal_type_vars(deal_type)

    platforms = st.multiselect("Platforms", PLATFORM_OPTIONS, default=["website"])

    col_sd, col_ed = st.columns(2)
    with col_sd:
        start_date = st.text_input("Start date", placeholder="2026-06-18")
    with col_ed:
        end_date = st.text_input("End date", placeholder="2026-08-31")
    promo_code = st.text_input("Promo code (optional, leave blank for none)", placeholder="")

    return {
        "name": name,
        "description": desc or None,
        "deal_type": deal_type,
        "deal_type_vars": deal_vars,
        "platforms": platforms,
        "start_date": start_date or None,
        "end_date": end_date or None,
        "promo_code": promo_code or None,
    }


def _generation_form(ct: str) -> dict | None:
    # Deal type has to be picked *outside* the form: widgets inside
    # st.form() don't trigger a script rerun until the form is submitted,
    # so a selectbox in there can't dynamically swap the fields shown below
    # it (the whole point of DEAL_TYPES) -- it would keep showing whichever
    # deal type's fields were visible on the last actual rerun.
    deal_type: str | None = None
    if ct == "Deals":
        st.divider()
        deal_type = st.selectbox("Deal type *", DEAL_TYPES, key="deal_type_sel")
        st.caption("Choose this first — it determines which fields appear in Campaign content below.")

    with st.form("gen_form", clear_on_submit=False):
        col_r, col_o = st.columns([3, 1])
        with col_r:
            restaurant_id = st.selectbox(
                "Restaurant",
                options=list(RESTAURANTS.keys()),
                format_func=lambda x: RESTAURANTS[x],
            )
        with col_o:
            orientation = st.selectbox("Orientation", ["Landscape", "Portrait", "Square"])

        col_goal, col_aud = st.columns(2)
        with col_goal:
            default_goal = _DEFAULT_GOAL_BY_TYPE.get(ct, GOAL_OPTIONS[0])
            goal = st.selectbox("Campaign goal", GOAL_OPTIONS, index=GOAL_OPTIONS.index(default_goal))
            st.caption(GOAL_CAPTIONS[goal])
        with col_aud:
            audiences = st.multiselect("Target audiences *", AUDIENCE_OPTIONS, default=["New"])

        col_voice, col_tags = st.columns([1, 2])
        with col_voice:
            brand_voice = st.text_input("Brand voice", value="Casual, Friendly")
        with col_tags:
            guest_tags = st.multiselect("Guest tags (optional)", TAG_OPTIONS)

        st.divider()
        st.markdown("**Campaign content**")

        if ct == "Spotlights":
            campaign_vars = _spotlights_vars()
        elif ct == "Menu Items":
            campaign_vars = _menu_items_vars()
        else:
            campaign_vars = _deals_vars(deal_type)

        with st.expander("Advanced options"):
            custom_prompt = st.text_area(
                "Custom prompt (appended to AI-generated prompt)",
                placeholder="Use dramatic backlighting. Focus on the golden crust.",
                height=68,
            )
            cta = st.checkbox("Enable CTA overlay")

        submitted = st.form_submit_button(
            "Generate Image",
            type="primary",
            use_container_width=True,
        )

    if not submitted:
        return None

    name = (campaign_vars.get("name") or "").strip()
    if not name:
        st.warning("Campaign name is required.")
        return None
    if not audiences:
        st.warning("Select at least one target audience.")
        return None
    if ct != "Deals":
        desc = (campaign_vars.get("description") or "").strip()
        if not desc:
            st.warning("Description is required.")
            return None

    return {
        "campaign_type": ct,
        "campaign_goals": goal,
        "campaign_audiences": audiences,
        "campaign_guest_tags": guest_tags,
        "campaign_vars": campaign_vars,
        "cta": cta,
        "channels": ["Email"],
        "campaign_brand_voices": brand_voice,
        "restaurantId": restaurant_id,
        "orientation": orientation,
        "custom_prompt": custom_prompt.strip() if custom_prompt.strip() else None,
    }


def _start_job(payload: dict) -> str | None:
    """POSTs the campaign, which now only starts a background job and
    returns immediately (image generation itself commonly takes 45-100s,
    well past what's reasonable to block a single HTTP request on)."""
    if not API_TOKEN:
        st.error(
            "API_BEARER_TOKEN is not set. Add it to your .env file and restart the app."
        )
        return None
    try:
        resp = requests.post(
            f"{API_URL}/api/generate-image",
            json=payload,
            headers={"Authorization": f"Bearer {API_TOKEN}"},
            timeout=30,
        )
    except requests.exceptions.ConnectionError:
        st.error(
            f"Cannot connect to the backend at {API_URL}. "
            "Start it with: uvicorn main:app --reload --port 8010"
        )
        return None
    except requests.exceptions.Timeout:
        st.error("Starting the job timed out.")
        return None

    if resp.status_code == 202:
        return resp.json()["job_id"]

    try:
        detail = resp.json().get("detail", resp.text)
    except Exception:
        detail = resp.text
    st.error(f"Error {resp.status_code}: {detail}")
    return None


def _poll_job(job_id: str) -> dict | None:
    """Polls the job status endpoint once a second, driving a live progress
    bar from the backend's real per-stage progress until the job reaches a
    terminal state. Returns the final result dict on success, or None (with
    the error already shown) on failure."""
    headers = {"Authorization": f"Bearer {API_TOKEN}"}
    progress_bar = st.progress(0, text="Queued")

    while True:
        try:
            resp = requests.get(
                f"{API_URL}/api/generate-image/{job_id}", headers=headers, timeout=10
            )
        except requests.exceptions.RequestException as exc:
            progress_bar.empty()
            st.error(f"Lost connection while checking progress: {exc}")
            return None

        if resp.status_code != 200:
            progress_bar.empty()
            st.error(f"Error {resp.status_code}: {resp.text}")
            return None

        body = resp.json()
        pct = body["progress"]
        progress_bar.progress(pct / 100, text=f"{body['stage']} ({pct}%)")

        if body["status"] == "complete":
            progress_bar.progress(1.0, text="Done (100%)")
            progress_bar.empty()
            return body["result"]
        if body["status"] == "failed":
            progress_bar.empty()
            st.error(f"Generation failed: {body.get('error', 'Unknown error')}")
            return None

        time.sleep(1.0)


def _result_panel(data: dict) -> None:
    st.divider()
    col_img, col_meta = st.columns([5, 3])

    with col_img:
        st.image(data["image_url"], use_container_width=True)
        if data.get("alt_text"):
            st.markdown(f'<p class="alt-text">{data["alt_text"]}</p>', unsafe_allow_html=True)

        dl_col, link_col = st.columns(2)
        with link_col:
            st.link_button("Open full image", data["image_url"], use_container_width=True)
        with dl_col:
            try:
                img_bytes = requests.get(data["image_url"], timeout=30).content
                safe_name = (
                    data.get("restaurant_name", "campaign")
                    .replace("'", "")
                    .replace(" ", "_")
                )
                safe_type = data.get("campaign_type", "image").replace(" ", "_")
                st.download_button(
                    "Download image",
                    data=img_bytes,
                    file_name=f"{safe_name}_{safe_type}.jpg",
                    mime="image/jpeg",
                    use_container_width=True,
                )
            except Exception:
                pass

    with col_meta:
        st.markdown("**Generation details**")

        metrics = data.get("metrics", {})
        latency_s = metrics.get("total_latency_ms", 0) / 1000
        cost = metrics.get("total_cost_usd", 0.0)
        clip = data.get("clip_score")
        qa_passed = data.get("qa_passed", True)
        qa_retries = data.get("qa_retries", 0)
        qa_scores = data.get("qa_scores") or {}

        m1, m2 = st.columns(2)
        m1.metric("Latency", f"{latency_s:.1f}s")
        m2.metric("Cost", f"${cost:.4f}")

        m3, m4 = st.columns(2)
        m3.metric("Model", data.get("model_used", "-"))
        m4.metric("Attempt", data.get("attempt_number", 1))

        if clip is not None:
            m5, m6 = st.columns(2)
            m5.metric("CLIP score", f"{clip:.3f}")
            m6.metric("Orientation", "Preserved" if data.get("orientation_preserved") else "Degraded")

        qa_label = "Passed" if qa_passed else f"Failed (retries: {qa_retries})"
        qa_class = "qa-pass" if qa_passed else "qa-fail"
        st.markdown(
            f"**QA:** <span class='{qa_class}'>{qa_label}</span>",
            unsafe_allow_html=True,
        )

        if qa_scores.get("brand_fidelity") is not None:
            b1, b2 = st.columns(2)
            b1.metric("Brand fidelity", f"{qa_scores['brand_fidelity']}/5")
            b2.metric("Composition", f"{qa_scores.get('composition', '-')}/5")

        with st.expander("Generated prompt"):
            st.code(data.get("generated_prompt", ""), language=None)

        breakdown = metrics.get("stage_breakdown", [])
        if breakdown:
            with st.expander("Stage breakdown"):
                for s in breakdown:
                    cost_str = f"${s['cost_usd']:.5f}" if s["cost_usd"] else "free"
                    st.text(f"{s['stage']:<22} {s['latency_ms']}ms  {cost_str}")


def main() -> None:
    st.set_page_config(
        page_title="Campaign Image Generator",
        page_icon="icon.png",  # swap for any emoji string or image path
        layout="wide",
        initial_sidebar_state="collapsed",
    )
    st.markdown(_CSS, unsafe_allow_html=True)
    _init_state()

    st.markdown("## Campaign Image Generator")
    st.caption("Generate campaign images for restaurant marketing. Powered by Camion AI.")
    st.divider()

    _campaign_type_cards()
    st.write("")

    ct = st.session_state.campaign_type
    payload = _generation_form(ct)

    if payload is not None:
        job_id = _start_job(payload)
        if job_id:
            result = _poll_job(job_id)
            if result:
                st.session_state.result = result

    if st.session_state.result:
        _result_panel(st.session_state.result)


if __name__ == "__main__":
    main()
