.PHONY: test test-live test-actions test-power-cycle test-all

# Address of a real soundbar for the live tests, e.g. make test-live TEMESCAL_HOST=192.168.1.127
TEMESCAL_HOST ?=
TEMESCAL_PORT ?= 9741

test:
	uv run pytest --ignore=tests/live

test-live: check-host
	TEMESCAL_HOST=$(TEMESCAL_HOST) TEMESCAL_PORT=$(TEMESCAL_PORT) uv run pytest tests/live -v -s

# Changes settings, inputs and power, restoring each one; the soundbar must be on
test-actions: check-host
	TEMESCAL_HOST=$(TEMESCAL_HOST) TEMESCAL_PORT=$(TEMESCAL_PORT) TEMESCAL_ACTIONS=1 \
		uv run pytest tests/live/test_actions.py -v -s

# Interactive: asks you twice to unplug the soundbar and plug it back in
test-power-cycle: check-host
	TEMESCAL_HOST=$(TEMESCAL_HOST) TEMESCAL_PORT=$(TEMESCAL_PORT) TEMESCAL_POWER_CYCLE=1 \
		uv run pytest tests/live -v -s -k test_power_cycle

# Everything in a single run, so that no test is skipped: unit tests, then the
# read-only, action and power cycle tests against the soundbar, which must be on
test-all: check-host
	TEMESCAL_HOST=$(TEMESCAL_HOST) TEMESCAL_PORT=$(TEMESCAL_PORT) TEMESCAL_ACTIONS=1 \
		TEMESCAL_POWER_CYCLE=1 uv run pytest -v -s

.PHONY: check-host
check-host:
	@test -n "$(TEMESCAL_HOST)" || { echo "Set TEMESCAL_HOST to the address of the soundbar"; exit 1; }
