from __future__ import annotations

import json
import os
import time

import requests
import streamlit as st


API_URL = os.getenv("API_URL", "http://localhost:8000")
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

AUDIENCE_OPTIONS = ["All Guests", "Regulars", "New", "Potential", "VIP", "Lapsed"]

TAG_OPTIONS = [
    "Cocktail", "Wine", "Beer", "Mexican Food Lovers", "Seafood Lovers",
    "Vegetarian", "Vegan", "Family", "Date Night",
]

DEAL_TYPE_DEFAULTS: dict[str, dict] = {
    "$ or %OFF": {"discount_type": "percent", "discount_value": 25, "items": "all cocktails"},
    "BOGO": {"item": "Baja Fish Taco", "qualifying_item": "any taco"},
    "Fixed Price": {"fixed_price": 29, "description": "3 courses"},
    "Bundle Deal": {"bundle_items": ["appetizer", "entree", "dessert"], "bundle_price": 45},
}

DEAL_TYPES = list(DEAL_TYPE_DEFAULTS.keys())

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
    name = st.text_input("Spotlight name *", placeholder="Weekend Fiesta")
    desc = st.text_area(
        "Description *",
        placeholder="Join us every weekend for live music, fresh margaritas, and chef's special tacos.",
        height=80,
    )
    spotlight_type = st.selectbox("Spotlight type", ["event", "chef", "seasonal", "story"])
    return {"name": name, "description": desc, "spotlight_type": spotlight_type}


def _menu_items_vars() -> dict:
    name = st.text_input("Item name *", placeholder="Baja Fish Taco")
    desc = st.text_area(
        "Description *",
        placeholder="Crispy beer-battered fish, fresh pico, avocado crema on a warm corn tortilla.",
        height=80,
    )
    col_p, col_c = st.columns([1, 2])
    with col_p:
        price = st.text_input("Price (optional)", placeholder="12")
    with col_c:
        categories = st.multiselect(
            "Item categories",
            ["Tacos", "Burritos", "Cocktails", "Wine", "Beer", "Salads",
             "Burgers", "Seafood", "Desserts", "Appetizers", "Pasta"],
        )
    item_menu = st.text_input("Menu section (optional)", placeholder="Main Menu")
    return {
        "name": name,
        "description": desc,
        "price": price or None,
        "item_category": categories,
        "item_menu": item_menu or None,
    }


def _deals_vars(deal_type_key: str) -> dict:
    name = st.text_input("Deal name *", placeholder="Happy Hour Savings")
    desc = st.text_area(
        "Description (optional)",
        placeholder="Enjoy 25% off all cocktails and wines during happy hour.",
        height=60,
    )
    deal_type = st.selectbox("Deal type *", DEAL_TYPES, key="deal_type_sel")
    default_vars = json.dumps(DEAL_TYPE_DEFAULTS.get(deal_type, {}), indent=2)
    deal_vars_str = st.text_area("Deal variables (JSON)", value=default_vars, height=80)
    col_sd, col_ed = st.columns(2)
    with col_sd:
        start_date = st.text_input("Start date", placeholder="2026-07-01")
    with col_ed:
        end_date = st.text_input("End date", placeholder="2026-08-31")
    promo_code = st.text_input("Promo code (optional)", placeholder="SUMMER25")

    try:
        deal_vars = json.loads(deal_vars_str) if deal_vars_str.strip() else {}
    except json.JSONDecodeError:
        deal_vars = {}

    return {
        "name": name,
        "description": desc or None,
        "deal_type": deal_type,
        "deal_type_vars": deal_vars,
        "start_date": start_date or None,
        "end_date": end_date or None,
        "promo_code": promo_code or None,
    }


def _generation_form(ct: str) -> dict | None:
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

        col_aud, col_voice = st.columns(2)
        with col_aud:
            audiences = st.multiselect("Target audiences *", AUDIENCE_OPTIONS, default=["All Guests"])
        with col_voice:
            brand_voice = st.text_input("Brand voice", value="Casual, Friendly")

        guest_tags = st.multiselect("Guest tags (optional)", TAG_OPTIONS)

        st.divider()
        st.markdown("**Campaign content**")

        if ct == "Spotlights":
            campaign_vars = _spotlights_vars()
        elif ct == "Menu Items":
            campaign_vars = _menu_items_vars()
        else:
            campaign_vars = _deals_vars(ct)

        with st.expander("Advanced options"):
            custom_prompt = st.text_area(
                "Custom prompt (appended to AI-generated prompt)",
                placeholder="Use dramatic backlighting. Focus on the golden crust.",
                height=60,
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
        "campaign_goals": "Increase Sales",
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


def _call_api(payload: dict) -> dict | None:
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
            timeout=180,
        )
    except requests.exceptions.ConnectionError:
        st.error(
            f"Cannot connect to the backend at {API_URL}. "
            "Start it with: uvicorn main:app --reload --port 8000"
        )
        return None
    except requests.exceptions.Timeout:
        st.error("Request timed out after 3 minutes.")
        return None

    if resp.status_code == 200:
        return resp.json()

    try:
        detail = resp.json().get("detail", resp.text)
    except Exception:
        detail = resp.text
    st.error(f"Error {resp.status_code}: {detail}")
    return None


def _result_panel(data: dict) -> None:
    st.divider()
    col_img, col_meta = st.columns([5, 3])

    with col_img:
        st.image(data["image_url"], use_container_width=True)
        if data.get("alt_text"):
            st.markdown(f'<p class="alt-text">{data["alt_text"]}</p>', unsafe_allow_html=True)
        st.link_button("Open full image", data["image_url"])

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
        page_title="Camion Image Generator",
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
        with st.spinner("Generating image... this takes up to 30 seconds."):
            result = _call_api(payload)
        if result:
            st.session_state.result = result

    if st.session_state.result:
        _result_panel(st.session_state.result)


if __name__ == "__main__":
    main()
