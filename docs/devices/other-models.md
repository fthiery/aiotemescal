# Other models

What others reported about models that have not been tested with aiotemescal,
so that it is not lost until someone writes a page for them (see the README,
"Contributing"). None of it was checked here.

## LG SK8

- `set_power()` does nothing, and the power state is always shown as on, even
  after the remote turned it off ([comment](https://github.com/mjg59/python-temescal/pull/1)
  of 2024-12-26).

## LG DSP11RA

- `set_power(True)` turns it on, but `set_power(False)` does not turn it off,
  and the power state is always shown as on ([comment](https://github.com/mjg59/python-temescal/pull/1)
  of 2025-04-16).

## LG S90QY

- `s_uuid` is reported in `PRODUCT_INFO` rather than in `MAC_INFO_DEV`
  ([home-assistant/core#77856](https://github.com/home-assistant/core/pull/77856)).
