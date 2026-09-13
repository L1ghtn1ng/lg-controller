"""Test environment isolation."""

from __future__ import annotations

import os
import tempfile

os.environ.setdefault("LGTV_STATE_DIR", tempfile.mkdtemp(prefix="lgtv-controller-tests-"))
