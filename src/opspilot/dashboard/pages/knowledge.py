"""Cited retrieval inspection page."""

import streamlit as st

from opspilot.dashboard.client import APIClientError, OpsPilotAPIClient


def render(client: OpsPilotAPIClient) -> None:
    st.header("Knowledge search")
    with st.form("knowledge-search"):
        query = st.text_input("Symptoms or question")
        service = st.selectbox("Service filter", ["Any", "orders", "payments", "inventory"])
        fault_type = st.selectbox(
            "Fault filter",
            [
                "Any",
                "memory_leak",
                "db_pool_exhaustion",
                "slow_dependency",
                "bad_deployment",
                "disk_full",
            ],
        )
        submitted = st.form_submit_button("Search verified knowledge")
    if not submitted:
        return
    payload = {"query": query, "k": 5}
    if service != "Any":
        payload["service"] = service
    if fault_type != "Any":
        payload["fault_type"] = fault_type
    try:
        result = client.post("/v1/kb/search", payload)
    except APIClientError as exc:
        st.error(str(exc))
        return
    for number, item in enumerate(result.get("results", []), start=1):
        st.markdown(f"**{number}. {item['doc_id']} · {item['section']}**")
        st.caption(f"Score: {float(item['score']):.4f}")
        st.write(item["text"])
        st.code(f"[{item['citation']['doc_id']} | {item['citation']['section']}]")
