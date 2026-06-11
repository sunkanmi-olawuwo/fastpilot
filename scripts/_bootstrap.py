"""Shared script bootstrap: sys.path + OS trust store.

Importing this module (a) puts ``final-submission/`` on sys.path so scripts can
``import app.config`` when run from the repo root, and (b) injects the OS trust
store into Python's SSL so HTTPS to Qdrant Cloud / Redis Cloud works on managed
machines — the same fix every week-3/week-4 cloud script applies via their
``_network.configure_system_trust_store()`` helper.
"""

import sys
from pathlib import Path

_SUBMISSION_DIR = Path(__file__).resolve().parent.parent
if str(_SUBMISSION_DIR) not in sys.path:
    sys.path.insert(0, str(_SUBMISSION_DIR))

try:
    import truststore

    truststore.inject_into_ssl()
except ModuleNotFoundError:
    print("[warn] truststore not installed; HTTPS uses Python's default CA bundle")
