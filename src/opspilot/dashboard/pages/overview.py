"""Live telemetry and online detector overview."""

from typing import Any

import pandas as pd
import plotly.express as px
import streamlit as st

from opspilot.dashboard.client import APIClientError, OpsPilotAPIClient


def render(client: OpsPilotAPIClient) -> None:
    st.header("Live metrics")
    try:
        detection = client.get("/v1/detection/status")
        incidents = client.get("/v1/incidents", status="open", limit=100)
    except APIClientError as exc:
        st.error(str(exc))
        return

    columns = st.columns(4)
    columns[0].metric("Detector", detection.get("detector") or "Waiting for alerts")
    columns[1].metric("Open incidents", int(detection.get("open_incidents", 0)))
    columns[2].metric("Last score", _format_number(detection.get("last_score")))
    columns[3].metric("Threshold", _format_number(detection.get("last_threshold")))

    services = ["orders", "payments", "inventory"]
    service = st.selectbox("Service", services)
    minutes = st.slider("Window (minutes)", min_value=5, max_value=360, value=60, step=5)
    try:
        series = client.get(f"/v1/metrics/{service}", minutes=minutes, points=1_000)
    except APIClientError as exc:
        st.error(str(exc))
        return
    frame = pd.DataFrame.from_records(
        [{"ts": item["ts"], **item["values"]} for item in series.get("items", [])]
    )
    if frame.empty:
        st.info("No persisted metrics are available for this time window yet.")
    else:
        frame["ts"] = pd.to_datetime(frame["ts"], utc=True)
        chart_metrics = (
            "latency_ms_p95",
            "error_rate",
            "memory_mb",
            "db_pool_in_use",
            "disk_used_pct",
        )
        for metric in chart_metrics:
            if metric in frame.columns:
                figure = px.line(frame, x="ts", y=metric, title=f"{service}: {metric}")
                st.plotly_chart(figure, use_container_width=True)

    st.subheader("Open alerts")
    if incidents.get("items"):
        st.dataframe(pd.DataFrame(incidents["items"]), use_container_width=True, hide_index=True)
    else:
        st.caption("No open incidents.")


def _format_number(value: Any) -> str:
    return "—" if value is None else f"{float(value):.3f}"
