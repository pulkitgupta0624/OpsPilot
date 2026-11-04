.PHONY: demo demo-down demo-logs demo-status

demo:
	python scripts/demo.py

demo-down:
	docker compose down

demo-logs:
	docker compose logs --follow

demo-status:
	docker compose ps
