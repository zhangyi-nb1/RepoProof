#!/bin/sh
set -eu
python3 -m venv .venv
.venv/bin/python run_tests.py
