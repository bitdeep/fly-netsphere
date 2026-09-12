# Convenience targets. Everything runs inside Docker; the host only needs Docker + the NVIDIA container runtime.
SECONDS ?= 60
TAKE    ?= out/take_$(shell date -u +%Y%m%dT%H%M%SZ)
VIEW    ?= third-person

.PHONY: setup build run take verify render probe-gpu

setup:            ## download flybody (pinned commit + patch) and the Figshare policies/dataset
	scripts/fetch_flybody.sh
	scripts/fetch_data.sh

build: setup      ## build the locked image (hash-verified wheels)
	docker compose build fly

run:              ## simulate, render and verify a 60 s take into out/<timestamp>
	docker compose run --rm fly

take:             ## SECONDS=.. TAKE=out/name VIEW=third-person|first-person
	docker compose run --rm fly bash scripts/simulate_city.sh $(SECONDS) $(TAKE) $(VIEW)

verify:           ## TAKE=out/name  independent check of an existing take
	docker compose run --rm fly python scripts/verify_take.py $(TAKE) --seconds $(SECONDS)

render:           ## TAKE=out/name  re-render recorded states with another camera
	docker compose run --rm fly python scripts/render_city.py $(TAKE) --view $(VIEW)

probe-gpu:        ## short CUDA flight probe (compiles kernels on first run)
	docker compose run --rm fly python scripts/probe_cuda_flight.py
