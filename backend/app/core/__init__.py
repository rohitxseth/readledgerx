# Intentionally empty.
#
# `app.core.dependencies` is the composition root: it imports every service,
# repository and client in order to wire them. Re-exporting it here made that
# wiring a side effect of importing *any* `app.core` submodule — so
# `app.services.reading_service` importing `app.core.exceptions` pulled the
# composition root back into a half-initialised services package and raised
# ImportError. Import the wiring explicitly: `from app.core.dependencies import ...`
