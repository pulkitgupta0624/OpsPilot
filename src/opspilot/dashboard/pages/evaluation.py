"""Local evaluation report viewer."""

import streamlit as st

from opspilot.dashboard.client import APIClientError, OpsPilotAPIClient


def render(client: OpsPilotAPIClient) -> None:
    st.header("Evaluation reports")
    try:
        result = client.get("/v1/evals/latest")
    except APIClientError as exc:
        st.error(str(exc))
        return
    reports = result.get("reports", [])
    if not reports:
        st.info("No local evaluation reports are available yet.")
        return
    filename = st.selectbox("Report", [item["filename"] for item in reports])
    report = next(item for item in reports if item["filename"] == filename)
    if filename.endswith(".md"):
        st.markdown(report["content"])
    else:
        st.code(report["content"], language="json" if filename.endswith(".json") else "text")
