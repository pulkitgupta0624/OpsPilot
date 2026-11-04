"""Guarded demo fault injection page."""

import streamlit as st

from opspilot.dashboard.client import APIClientError, OpsPilotAPIClient


def render(client: OpsPilotAPIClient) -> None:
    st.header("Chaos control")
    st.warning(
        "This demo control injects faults into the local simulator only. "
        "The server must explicitly enable the chaos API."
    )
    with st.form("fault-injection"):
        service = st.selectbox("Service", ["orders", "payments", "inventory"])
        fault_type = st.selectbox(
            "Fault",
            [
                "memory_leak",
                "db_pool_exhaustion",
                "slow_dependency",
                "bad_deployment",
                "disk_full",
            ],
        )
        duration = st.slider(
            "Duration (seconds)", min_value=30, max_value=1_800, value=300, step=30
        )
        intensity = st.slider("Intensity", min_value=0.3, max_value=1.5, value=1.0, step=0.1)
        acknowledged = st.checkbox("I understand this changes simulator state.")
        submitted = st.form_submit_button("Inject fault", disabled=not acknowledged)
    if not submitted:
        return
    try:
        result = client.post(
            "/v1/simulator/faults",
            {
                "service": service,
                "fault_type": fault_type,
                "duration_seconds": duration,
                "intensity": intensity,
            },
        )
    except APIClientError as exc:
        st.error(str(exc))
        return
    st.success("Simulator accepted the fault request.")
    st.json(result)
