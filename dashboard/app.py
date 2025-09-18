import os, requests, pandas as pd
import streamlit as st
from datetime import date, timedelta

API_BASE = os.getenv("API_BASE","http://localhost:8080")

st.set_page_config(page_title="Hotel Rate Optimizer", layout="wide")

if "token" not in st.session_state:
    st.session_state["token"] = None

st.title("Hotel Rate Optimizer – GM Dashboard")

with st.sidebar:
    st.subheader("Login")
    if st.session_state["token"] is None:
        email = st.text_input("Email", value=os.getenv("ADMIN_EMAIL","admin@example.com"))
        password = st.text_input("Password", type="password")
        if st.button("Login"):
            r = requests.post(f"{API_BASE}/auth/login", json={"email":email, "password":password})
            if r.ok:
                st.session_state["token"] = r.json()["token"]
                st.success("Logged in")
            else:
                st.error(f"Login failed: {r.text}")
    else:
        if st.button("Logout"):
            st.session_state["token"] = None

if st.session_state["token"]:
    col1, col2 = st.columns(2)
    with col1:
        start = st.date_input("Start", date.today())
    with col2:
        end = st.date_input("End", date.today() + timedelta(days=7))

    if st.button("Load Forecast"):
        headers = {"Authorization": f"Bearer {st.session_state['token']}"}
        r = requests.get(f"{API_BASE}/forecast", params={"start": start.isoformat(), "end": end.isoformat()}, headers=headers)
        if r.ok:
            data = r.json()
            df = pd.DataFrame(data)
            st.dataframe(df, use_container_width=True)
            # Charts
            st.subheader("Projected Occupancy by Room Type")
            occ = df.groupby(["stay_date","room_type"])["demand_forecast"].mean().reset_index()
            st.line_chart(occ.pivot(index="stay_date", columns="room_type", values="demand_forecast"))
            st.subheader("Competitor Median vs Recommended ADR")
            comp = df[['stay_date','room_type','competitor_rate','recommended_adr']].copy()
            st.line_chart(comp.set_index('stay_date')[['competitor_rate','recommended_adr']])
            st.download_button("Download CSV", df.to_csv(index=False), "recommendations.csv", "text/csv")
        else:
            st.error(r.text)

    st.divider()
    st.subheader("Daily Rate Brief")
    to_email = st.text_input("Send to email (optional)", value=os.getenv("ADMIN_EMAIL","admin@example.com"))
    if st.button("Generate Brief (no send)"):
        headers = {"Authorization": f"Bearer {st.session_state['token']}"}
        r = requests.post(f"{API_BASE}/brief", json={"send": False, "to_email": to_email}, headers=headers)
        st.write(r.json().get("brief","(no text)"))
    if st.button("Send Daily Rate Brief"):
        headers = {"Authorization": f"Bearer {st.session_state['token']}"}
        r = requests.post(f"{API_BASE}/brief", json={"send": True, "to_email": to_email}, headers=headers)
        st.success("Requested brief send" if r.ok else f"Failed: {r.text}")
else:
    st.info("Please login to continue.")
