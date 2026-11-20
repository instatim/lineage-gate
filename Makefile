.PHONY: setup build gate monitor demo demo-auto test

setup:
	uv sync

build:
	uv run dbt build --project-dir warehouse --profiles-dir warehouse

gate:
	uv run python controls/lineage_gate.py

monitor:
	uv run python controls/write_monitor.py

demo:
	uv run python demo/demo.py

demo-auto:
	uv run python demo/demo.py --auto

test:
	uv run pytest
