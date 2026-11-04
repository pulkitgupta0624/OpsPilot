"""Streamlit entry point for the API-backed OpsPilot dashboard."""

import os

import streamlit as st

from opspilot.dashboard.client import APIClientError, OpsPilotAPIClient
from opspilot.dashboard.pages import chaos, evaluation, incidents, knowledge, overview, trace


def main() -> None:
    st.set_page_config(page_title="OpsPilot", page_icon="🛰️", layout="wide")
    st.title("OpsPilot")
    st.caption("Incident operations for the local simulator")
    with st.sidebar:
        st.header("Connection")
        api_url = st.text_input(
            "API URL", value=os.getenv("OPSPILOT_API_URL", "http://127.0.0.1:8000")
        )
        api_key = os.getenv("OPSPILOT_API_KEY") or st.text_input(
            "API key", type="password", key="opspilot-api-key"
        )
        page = st.radio(
            "Page",
            ["Overview", "Incidents", "Agent Trace", "Knowledge", "Chaos Control", "Evaluation"],
        )

    if not api_key:
        st.info("Set OPSPILOT_API_KEY or enter the key in the sidebar to connect.")
        return
    client = OpsPilotAPIClient(api_url, api_key)
    try:
        health = client.get("/ready")
    except APIClientError as exc:
        st.error(f"API is not ready: {exc}")
        return
    st.sidebar.success(f"API ready · {health.get('database', 'unknown')} database")

    renderers = {
        "Overview": overview.render,
        "Incidents": incidents.render,
        "Agent Trace": trace.render,
        "Knowledge": knowledge.render,
        "Chaos Control": chaos.render,
        "Evaluation": evaluation.render,
    }
    renderers[page](client)


if __name__ == "__main__":
    main()
