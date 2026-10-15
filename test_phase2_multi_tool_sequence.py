"""Offline multi-tool E2E proof (Phase 2).

Two tests using tmp_path + the REAL OSManager/ActionExecutor
(no mocks for execution, no network):

  (a) doc_create_txt then doc_read back verifies content;
  (b) file copy then read-back (resolve) verifies content.

Uses ``invoke_sequence`` from ``agent_framework_adapter`` when
importable, else drives ``ActionExecutor`` directly with the same
stop-on-first-failure semantics.

Deliberately NOT marked ``live``: it performs real filesystem work
but stays inside ``tmp_path`` and makes no network, provider or GUI
call, so it belongs in the fast default run.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, List
