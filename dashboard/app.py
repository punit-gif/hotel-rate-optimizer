import os
import requests
import pandas as pd
import streamlit as st
from datetime import date, timedelta

# -----------------------------
# Config / API base detection
# -----------------------------
DEFAULT_API = "https://hotel-rate-optimizer-production.up.railway.app"
API_BASE = (
    os.getenv("API_BASE")
    or os.getenv("VITE_API_BASE")
    or os.getenv("HOTEL_API_BASE")
    or DEFAULT_API
).rstrip("/")

ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "gm@yourhotel.com")

# Streamlit setup
st.set_page_config(page_title="Hotel Rate Optimizer", layout="wide")
st.title("Hotel Rate Optimizer – GM Dashboard")

if "token" not in st.session_state:
    st.session_state["token"] = None

# Reusable HTTP helpers
SESSION = requests.Session()
SESSION.headers.update({"Accept": "application/json"})

def api_url(path: str) -> str:
    if not path.startswith("/"):
        path = "/" + path
    return f"{API_BASE}{path}"

def get_headers(include_auth: bool = True) -> dict:
    h = {"Content-Type": "application/json"}
    if include_auth and st.session_state.get("token"):
        h["Authorization"] = f"Bearer {st.session_state['token']}"
    return h

def show_error(prefix: str, resp: requests.Response):
    # Trim noisy HTML bodies so the error is readable
    text = resp.text
    if "<html" in text.lower():
        text = text[:200] + ("..." if len(text) > 200 else "")
    st.error(f"{prefix}: {resp.status_code} {text}")

# Sidebar: Auth
with st.sidebar:
    st.subheader("Login")
    st.caption(f"API base: {API_BASE}")
    if st.session_state["token"] is None:
        email = st.text_input("Email", value=ADMIN_EMAIL)
        password = st.text_input("Password", type="password")
        if st.button("Login", use_container_width=True):
            try:
                r = SESSION.post(
                    api_url("/auth/login"),
                    json={"email": email, "password": password},
                    timeout=15,
                )
                if r.ok:
                    data = r.json()
                    st.session_state["token"] = data.get("token")
                    if not st.session_state["token"]:
                        st.error("Login succeeded but no token returned.")
                    else:
                        st.success("Logged in.")
                else:
                    show_error("Login failed", r)
            except Exception as e:
                st.error(f"Login error: {e}")
    else:
        if st.button("Logout", use_container_width=True):
            st.session_state["token"] = None
            st.success("Logged out.")

if st.session_state["token"]:
    col1, col2 = st.columns(2)
    with col1:
        start = st.date_input("Start", date.today())
    with col2:
        end = st.date_input("End", date.today() + timedelta(days=7))

    # Load Forecast button
    if st.button("Load Forecast", type="primary"):
        try:
            # Prefer Authorization header; also send token as query fallback
            params = {
                "start": start.isoformat(),
                "end": end.isoformat(),
                "token": st.session_state.get("token"),  # harmless if API ignores it
            }
            r = SESSION.get(
                api_url("/forecast"),
                params=params,
                headers=get_headers(include_auth=True),
                timeout=20,
            )
            if r.ok:
                data = r.json()
                if not data:
                    st.warning("No forecast rows returned for selected range.")
                else:
                    df = pd.DataFrame(data)
                    st.dataframe(df, use_container_width=True)

                    st.subheader("Projected Occupancy by Room Type")
                    occ = (
                        df.groupby(["stay_date", "room_type"])["demand_forecast"]
                        .mean()
                        .reset_index()
                    )
                    # Pivot for chart
                    occ_pvt = occ.pivot(
                        index="stay_date",
                        columns="room_type",
                        values="demand_forecast",
                    )
                    st.line_chart(occ_pvt)

                    st.subheader("Competitor Median vs Recommended ADR")
                    # This assumes the API fields are named as below:
                    # competitor_rate, recommended_adr
                    comp_cols = [
                        c for c in ["stay_date", "competitor_rate", "recommended_adr"] if c in df.columns
                    ]
                    if set(comp_cols) == {"stay_date", "competitor_rate", "recommended_adr"}:
                        comp = df[comp_cols].copy()
                        comp = comp.groupby("stay_date")[["competitor_rate", "recommended_adr"]].mean()
                        st.line_chart(comp)
                    else:
                        st.info("Competitor/ADR series not present in API response.")

                    st.download_button(
                        "Download CSV",
                        df.to_csv(index=False).encode("utf-8"),
                        "recommendations.csv",
                        "text/csv",
                    )
            else:
                show_error("Forecast load failed", r)
        except Exception as e:
            st.error(f"Forecast error: {e}")

    st.divider()
    st.subheader("Daily Rate Brief")
    to_email = st.text_input("Send to email (optional)", value=ADMIN_EMAIL)

    cols = st.columns(2)
    with cols[0]:
        if st.button("Generate Brief (no send)"):
            try:
                r = SESSION.post(
                    api_url("/brief"),
                    json={"send": False, "to_email": to_email},
                    headers=get_headers(include_auth=True),
                    timeout=30,
                )
                if r.ok:
                    # Robust JSON parsing
                    try:
                        j = r.json()
                        st.write(j.get("brief", "(no text)"))
                    except Exception:
                        st.write(r.text)
                else:
                    show_error("Brief generation failed", r)
            except Exception as e:
                st.error(f"Brief error: {e}")

    with cols[1]:
        if st.button("Send Daily Rate Brief"):
            try:
                r = SESSION.post(
                    api_url("/brief"),
                    json={"send": True, "to_email": to_email},
                    headers=get_headers(include_auth=True),
                    timeout=30,
                )
                if r.ok:
                    st.success("Brief send requested.")
                else:
                    show_error("Brief send failed", r)
            except Exception as e:
                st.error(f"Brief send error: {e}")

else:
    st.info("Please login to continue.")
