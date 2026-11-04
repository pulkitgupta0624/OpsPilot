"""Node-by-node graph and durable audit views."""

import streamlit as st

from opspilot.dashboard.client import APIClientError, OpsPilotAPIClient


def render(client: OpsPilotAPIClient) -> None:
    st.header("Agent trace")
    default_id = st.session_state.get("opspilot_incident_id", "")
    incident_id = st.text_input("Incident ID", value=default_id)
    if not incident_id:
        st.info("Choose an incident on the Incidents page or enter its ID.")
        return
    try:
        result = client.get(f"/v1/incidents/{incident_id}/trace")
    except APIClientError as exc:
        st.error(str(exc))
        return
    st.subheader("Graph events")
    for index, event in enumerate(result.get("trace", []), start=1):
        title = f"{index}. {event.get('node', 'node')} · {event.get('event', 'event')}"
        with st.expander(title, expanded=index == 1):
            st.json(event)
    st.subheader("Audit events")
    st.json(result.get("audit_events", []))
