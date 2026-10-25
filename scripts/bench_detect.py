#!/usr/bin/env python3
"""Time run_rules on the worst-case chain from issue #5.

A linear chain of datasets: the first has a PII-tagged `email` column, every
later hop copies it without the tag, and no dataset has an owner. Each hop is
an R1 finding and an R2 finding, and every finding's blast radius covers the
rest of the chain.

    python scripts/bench_detect.py            # 500, 1000 and 2000 datasets
    python scripts/bench_detect.py 4000       # custom sizes
"""
from __future__ import annotations

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from airgap.detect import run_rules  # noqa: E402
from airgap.model import Asset, Field, FieldLineage, LineageEdge, MetadataGraph  # noqa: E402

CFG = {
    "detection": {
        "pii_markers": ["PII"],
        "human_facing_types": ["dashboard", "chart"],
        "severity": {"critical_blast_radius": 3, "high_blast_radius": 1},
    }
}


def chain(n: int) -> MetadataGraph:
    g = MetadataGraph()
    urns = [f"urn:li:dataset:(urn:li:dataPlatform:hive,bench.t{i:05d},PROD)" for i in range(n)]
    for i, urn in enumerate(urns):
        tags = ("PII",) if i == 0 else ()
        g.add_asset(Asset(urn=urn, name=f"bench.t{i:05d}", fields=(Field("email", tags=tags),)))
    for up, down in zip(urns, urns[1:]):
        g.edges.append(LineageEdge(upstream=up, downstream=down))
        g.field_edges.append(FieldLineage(up, "email", down, "email"))
    return g


def main(argv: list[str]) -> int:
    sizes = [int(a) for a in argv] or [500, 1000, 2000]
    print(f"{'datasets':>9} {'findings':>9} {'run_rules':>10}")
    for n in sizes:
        g = chain(n)
        t0 = time.perf_counter()
        findings = run_rules(g, CFG)
        dt = time.perf_counter() - t0
        print(f"{n:>9} {len(findings):>9} {dt:>9.2f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
