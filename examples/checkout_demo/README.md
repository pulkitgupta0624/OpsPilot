# Northstar Checkout Demo

This is the first real-application extension for OpsPilot: a small checkout system
made of independent `orders`, `payments`, and `inventory` services. It gives OpsPilot
a concrete application to monitor in later phases.

## What works in Phase 1

- A browser checkout page and an OpenAPI API at `http://127.0.0.1:8080`.
- Orders call inventory to reserve stock, then payments to charge the order.
- Each service owns a separate SQLite database stored in its own Docker volume.
- `Idempotency-Key` prevents a repeated checkout request from creating a second order
  or charge.
- If payment fails after inventory reservation, orders releases the reservation and
  records a failed order.
- JSON request logs carry the same `X-Request-ID` across service calls.
- A local-only payments control can add delay or reject charges for a controlled demo.

This phase is intentionally separate from the root OpsPilot Compose stack. It does not
yet send telemetry or alerts to OpsPilot. The next extension phase adds OpenTelemetry,
Prometheus, and Alertmanager integration.

## Start the checkout app

From the repository root in PowerShell:

```powershell
Set-Location examples/checkout_demo
docker compose up --build --detach
docker compose ps
docker compose logs --tail 50 orders payments inventory
```

Open the checkout page at `http://127.0.0.1:8080`. The orders API documentation is at
`http://127.0.0.1:8080/docs`. Payments is exposed only on loopback port 8082 so the
local demo can control a fault; inventory stays on the private Compose network.

## Place an order from PowerShell

```powershell
$checkoutKey = [guid]::NewGuid().ToString()
$checkoutBody = @{ sku = "coffee-beans"; quantity = 1 } | ConvertTo-Json
Invoke-RestMethod `
  -Method Post `
  -Uri "http://127.0.0.1:8080/api/orders" `
  -Headers @{ "Idempotency-Key" = $checkoutKey } `
  -ContentType "application/json" `
  -Body $checkoutBody
```

The expected status is `confirmed`. To verify idempotency, resend the same request
with the same `$checkoutKey`; it should return the existing order. Use a new key for a
new order.

## Demonstrate payment failure and compensation

Reject payment charges in the local demo:

```powershell
Invoke-RestMethod `
  -Method Put `
  -Uri "http://127.0.0.1:8082/admin/faults" `
  -ContentType "application/json" `
  -Body '{"latency_ms":0,"reject_charges":true}'
```

Place another order with a new key. It should be recorded as `failed`, and the
inventory reservation should be released. Inspect recent orders and stock:

```powershell
Invoke-RestMethod -Uri "http://127.0.0.1:8080/api/orders"
Invoke-RestMethod -Uri "http://127.0.0.1:8080/api/products"
```

Reset the payments fault after the demo:

```powershell
Invoke-RestMethod -Method Delete -Uri "http://127.0.0.1:8082/admin/faults"
```

You can also add a visible delay, up to four seconds, by setting `latency_ms` in the
fault configuration. Use this only to demonstrate the local sample application.

## Stop the demo

```powershell
docker compose down
```

This stops the containers and keeps the three service databases. To erase all saved
demo orders, charges, reservations, and stock changes, remove the volumes explicitly:

```powershell
docker compose down --volumes
```

## Phase 1 boundary

The checkout app is a local demo workload, not a production commerce system. Its
database is SQLite, its catalog is seeded sample data, and payment processing is a
local stub. Fault controls are reachable on `127.0.0.1` only. OpenTelemetry and OpsPilot
incident ingestion are planned for the next phase.
