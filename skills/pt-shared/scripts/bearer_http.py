"""One bearer JSON call, shared by every pt- skill that reads the Plow API.

Vendored from ld-shared/scripts/bearer_http.py rather than invented: the
redirect refusal is the reason this is a module and not three lines in each
caller -- a bearer header forwarded to wherever a redirect points hands the
instance's credential to somewhere the API did not authenticate.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request

TIMEOUT = 30


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *_args, **_kwargs):
        return None


def open_no_redirect(request: urllib.request.Request, *, timeout: int):
    """Open one request while refusing every redirect before forwarding auth."""
    return urllib.request.build_opener(NoRedirect).open(request, timeout=timeout)


def require(name):
    """Refuse by name -- a blank credential must say which one is blank."""
    value = os.environ.get(name, "").strip()
    if not value:
        sys.exit(f"error: {name} is not set")
    return value


def post_json(base, path, token, label, body):
    """One bearer JSON POST that never follows a redirect; exits loudly, by
    label, on any failure, so a failed call never reads like an empty answer.
    The response body is discarded -- the endpoint may echo submitted text on
    success, and edition text derives from web content of untrusted origin."""
    post_json_read(base, path, token, label, body)


def post_json_read(base, path, token, label, body):
    """Like ``post_json``, but returns the parsed JSON response body.

    Needed for the attachment declare step (``POST .../attachments``), whose
    response carries the ``uid``/``upload_url``/``upload_headers`` the next
    step needs -- unlike a chat-message POST, this response is Plow's own
    structured answer, not an echo of untrusted edition text, so reading it
    is safe by the same reasoning ``post_json`` discards the other kind.
    """
    data = json.dumps(body).encode("utf-8")
    request = urllib.request.Request(
        url=f"{base.rstrip('/')}{path}",
        method="POST",
        data=data,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    )
    try:
        with open_no_redirect(request, timeout=TIMEOUT) as response:
            raw = response.read()
    except urllib.error.HTTPError as exc:
        sys.exit(f"error: {label} returned HTTP {exc.code} {exc.reason}")
    except urllib.error.URLError as exc:
        sys.exit(f"error: POST to {label} failed: {exc.reason}")
    try:
        return json.loads(raw)
    except ValueError as exc:
        sys.exit(f"error: {label} returned a non-JSON response: {exc!r}")


def put_bytes(url, headers, data, label):
    """One PUT of raw bytes to a pre-signed capability URL, no redirect.

    ``url``/``headers`` come verbatim from an attachment-declare response --
    that URL IS the write capability (see the declare step), so no bearer is
    added here; adding one would send this agent's own credential to
    whatever the declare call named, which is Plow's own signed upload
    target, not a host this script chose.
    """
    request = urllib.request.Request(
        url=url, method="PUT", data=data, headers=dict(headers or {}),
    )
    try:
        with open_no_redirect(request, timeout=TIMEOUT) as response:
            response.read()
    except urllib.error.HTTPError as exc:
        sys.exit(f"error: {label} upload returned HTTP {exc.code} {exc.reason}")
    except urllib.error.URLError as exc:
        sys.exit(f"error: {label} upload failed: {exc.reason}")