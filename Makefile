.PHONY: test test-live test-actions test-power-cycle

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

.PHONY: check-host
check-host:
	@test -n "$(TEMESCAL_HOST)" || { echo "Set TEMESCAL_HOST to the address of the soundbar"; exit 1; }
