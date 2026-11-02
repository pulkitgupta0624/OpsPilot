"""Inventory service ASGI application; run with ``uvicorn`` for the live demo."""

from opspilot.simulator.services.common.app import create_service_app

app = create_service_app("inventory")

