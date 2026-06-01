"""speech/tests/ — pytest suite for the speech-native core (Phases 5, 6, 10).

All tests run on the deterministic CPU fallback backends (mock codec + echo runtime), so
they pass with no GPU and no Mimi/Moshi weights. Async coroutines are driven via
``asyncio.run`` so the suite does not depend on a particular pytest-asyncio mode config.
"""
