"""Packaging metadata."""
import os
import re

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_datahub_lite_extra_installs_duckdb():
    # acryl-datahub 1.7.0.14 moved DuckDB out of its datahub-lite extra into a
    # separate duckdb extra; without it `datahub lite` cannot open its database.
    with open(os.path.join(_ROOT, "pyproject.toml"), encoding="utf-8") as fh:
        text = fh.read()
    line = re.search(r"^datahub-lite = \[(.*)\]$", text, re.M)
    assert line, "datahub-lite extra not found in pyproject.toml"
    extras = re.search(r'"acryl-datahub\[([^\]]*)\]', line.group(1))
    assert extras and {"datahub-lite", "duckdb"} <= {e.strip() for e in extras.group(1).split(",")}
