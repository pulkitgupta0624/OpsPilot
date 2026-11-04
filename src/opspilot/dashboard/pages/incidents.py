"""Incident list, alert timeline, and human approval controls."""

import pandas as pd
import streamlit as st

from opspilot.dashboard.client import APIClientError, OpsPilotAPIClient


def render(client: OpsPilotAPIClient) -> None:
    st.header("Incidents")
    status = st.selectbox("Status", ["all", "open", "resolved", "escalated"])
    params = {"limit": 100}
    if status != "all":
        params["status"] = status
    try:
        result = client.get("/v1/incidents", **params)
    except APIClientError as exc:
        st.error(str(exc))
        return
    items = result.get("items", [])
    if not items:
        st.info("No incidents match this filter.")
        return
    st.dataframe(pd.DataFrame(items), use_container_width=True, hide_index=True)
    incident_id = st.selectbox("Incident details", [item["id"] for item in items])
    st.session_state["opspilot_incident_id"] = incident_id
    try:
        detail = client.get(f"/v1/incidents/{incident_id}")
    except APIClientError as exc:
        st.error(str(exc))
        return

    incident = detail.get("incident", {})
    st.subheader(str(incident.get("summary", incident_id)))
    st.json(incident)
    st.markdown("#### Alert timeline")
    alert_rows = detail.get("alerts", [])
    if alert_rows:
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "detected_at": alert.get("detected_at"),
                        "service": alert.get("service"),
                        "source": alert.get("source"),
                        "detector": alert.get("detector"),
                        "score": alert.get("score"),
                        "features": ", ".join(
                            item.get("name", "") for item in alert.get("suspect_features", [])
                        ),
                    }
                    for alert in alert_rows
                ]
            ),
            use_container_width=True,
            hide_index=True,
        )

    agent = detail.get("agent") or {}
    if agent:
        st.markdown("#### Current agent plan")
        st.json(
            {
                "status": agent.get("status"),
                "plan": agent.get("plan"),
                "policy": agent.get("policy"),
                "previous_execution": agent.get("execution"),
                "verification": agent.get("verification"),
            }
        )
    if agent.get("status") == "waiting_approval":
        _approval_form(client, incident_id)


def _approval_form(client: OpsPilotAPIClient, incident_id: str) -> None:
    st.markdown("#### Human approval")
    with st.form(f"approval-{incident_id}"):
        reviewer = st.text_input("Reviewer", max_chars=120)
        comment = st.text_area("Review comment", max_chars=2_000)
        choice = st.radio("Decision", ["Approve", "Reject"], horizontal=True)
        submitted = st.form_submit_button("Submit decision")
    if not submitted:
        return
    if not reviewer.strip():
        st.error("Enter the reviewer name before submitting.")
        return
    try:
        outcome = client.post(
            f"/v1/incidents/{incident_id}/approval",
            {"approved": choice == "Approve", "reviewer": reviewer, "comment": comment},
        )
    except APIClientError as exc:
        st.error(str(exc))
        return
    st.success(f"Decision recorded. Agent status: {outcome.get('status', 'unknown')}.")
    st.json(outcome)
