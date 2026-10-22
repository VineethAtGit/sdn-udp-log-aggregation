#!/usr/bin/env python3
"""
baseline_controller.py - the comparison baseline (contract section 4).

Same controller as sdn_controller.py (learning switch, per-severity forwarding
flows, identical STATS logging) but it NEVER installs priority/queue rules, so
all traffic shares the bottleneck equally.

  RUN_ID=baseline_heavy_1 ryu-manager controller/baseline_controller.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sdn_controller import SeveritySDNController  # noqa: E402


class BaselineController(SeveritySDNController):
    MODE = "baseline"