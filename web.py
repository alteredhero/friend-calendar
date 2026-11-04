"""Static-file helpers: revalidate on every load, and where the static folder lives."""
import os

from fastapi.staticfiles import StaticFiles

from paths import APP_DIR

STATIC_DIR = os.path.join(APP_DIR, "static")

# Browsers (and Cloudflare's edge) must revalidate pages and scripts on every load, so a code
# update can never leave a client running a stale script beside a fresh page. Revalidation is
# cheap: unchanged files come back as a 304 thanks to the ETag.
NO_CACHE = {"Cache-Control": "no-cache"}


class RevalidatingStatic(StaticFiles):
    def file_response(self, *args, **kwargs):
        resp = super().file_response(*args, **kwargs)
        resp.headers.update(NO_CACHE)
        return resp
