"""Airgap CLI.

    airgap audit                     # audit the bundled fixture (default)
    airgap audit --config my.yaml    # explicit config (else ./config.yaml, else bundled)
    airgap audit --source datahub --url https://... --token ...
    airgap audit --no-llm            # deterministic only, skip Ollama
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from importlib import resources

import yaml

from airgap.detect import run_rules
from airgap.detect.findings import Severity
from airgap.remediate import generate_patches
from airgap.report import write_graph_html, write_markdown
from airgap.sources import build_source

#: File name looked up in the current working directory.
CONFIG_FILENAME = "config.yaml"
#: Default output directory, relative to the current working directory.
DEFAULT_OUT = "outputs"

_COLOR = {
    Severity.CRITICAL: "\033[91m",
    Severity.HIGH: "\033[93m",
    Severity.MEDIUM: "\033[33m",
    Severity.LOW: "\033[90m",
}
_RESET = "\033[0m"


def resolve_config(explicit: str | None) -> str | None:
    """Pick the config file to load.

    Precedence: an explicit ``--config`` path, then ``./config.yaml`` in the
    current working directory, then the default config bundled with the
    package (returned as ``None``).
    """
    if explicit:
        return explicit
    if os.path.isfile(CONFIG_FILENAME):
        return os.path.abspath(CONFIG_FILENAME)
    return None


def _load_config(path: str | None) -> dict:
    if path is None:
        text = resources.files("airgap.data").joinpath(CONFIG_FILENAME).read_text(
            encoding="utf-8"
        )
        return yaml.safe_load(text) or {}
    with open(path, "r", encoding="utf-8") as fh:
        cfg = yaml.safe_load(fh) or {}
    # Resolve fixture path relative to the config file's directory.
    base = os.path.dirname(os.path.abspath(path))
    fp = cfg.get("fixture_path", "")
    if fp and not os.path.isabs(fp):
        cfg["fixture_path"] = os.path.join(base, fp)
    return cfg


def _apply_overrides(cfg: dict, args: argparse.Namespace) -> dict:
    if args.source:
        cfg["source"] = args.source
    if args.url:
        cfg.setdefault("datahub", {})["url"] = args.url
    if args.token:
        cfg.setdefault("datahub", {})["token"] = args.token
    if args.no_llm:
        cfg.setdefault("ollama", {})["enabled"] = False
    if args.model:
        cfg.setdefault("ollama", {})["model"] = args.model
    return cfg


def _enrich_with_llm(findings, cfg) -> None:
    from airgap.llm import LocalLLM

    oll = cfg.get("ollama", {})
    llm = LocalLLM(
        url=oll.get("url", "http://localhost:11434"),
        model=oll.get("model", "qwen2.5:7b"),
        timeout=int(oll.get("timeout_seconds", 120)),
    )
    if not llm.available():
        print(
            "  ! Ollama not reachable at "
            f"{oll.get('url')} — writing deterministic report without prose.",
            file=sys.stderr,
        )
        return
    print(f"  · Explaining findings locally via Ollama ({llm.model})...")
    for f in findings:
        f.explanation = llm.enrich(f)


def _print_summary(findings) -> None:
    print()
    print("  Airgap — governance findings")
    print("  " + "-" * 46)
    if not findings:
        print("  ✓ No governance leaks detected.")
        return
    for f in findings:
        color = _COLOR.get(f.severity, "")
        print(
            f"  {color}{f.severity:<8}{_RESET} {f.id}  {f.title}"
            f"  (blast radius: {f.blast_radius})"
        )
    print()


def cmd_audit(args: argparse.Namespace) -> int:
    args.out = os.path.abspath(args.out)
    config_path = resolve_config(args.config)
    cfg = _apply_overrides(_load_config(config_path), args)
    print(f"  · Config: {config_path or 'bundled default (airgap/data/config.yaml)'}")

    source = build_source(cfg)
    print(f"  · Fetching metadata from source: {source.name}")
    graph = source.fetch()
    print(
        f"  · Loaded {len(graph.assets)} assets, {len(graph.edges)} lineage edges, "
        f"{len(graph.field_edges)} column-level edges"
    )

    findings = run_rules(graph, cfg)
    print(f"  · Detection complete: {len(findings)} finding(s)")

    if cfg.get("ollama", {}).get("enabled", True):
        _enrich_with_llm(findings, cfg)

    os.makedirs(args.out, exist_ok=True)
    json_path = os.path.join(args.out, "findings.json")
    md_path = os.path.join(args.out, "report.md")
    html_path = os.path.join(args.out, "lineage_graph.html")
    with open(json_path, "w", encoding="utf-8") as fh:
        json.dump(
            {"source": source.name, "findings": [f.to_dict() for f in findings]},
            fh,
            indent=2,
        )
    write_markdown(findings, source.name, md_path)
    write_graph_html(findings, graph, source.name, html_path)
    patches = generate_patches(findings, args.out)

    _print_summary(findings)
    print(f"  → {json_path}")
    print(f"  → {md_path}")
    print(f"  → {html_path}")
    print(f"  → {len(patches)} remediation patch(es) in {os.path.join(args.out, 'patches')}/")

    if args.fail_on_critical and any(f.severity == Severity.CRITICAL for f in findings):
        return 2
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="airgap",
        description="Local-first data governance & PII lineage auditor for DataHub.",
    )
    sub = p.add_subparsers(dest="command", required=True)

    a = sub.add_parser("audit", help="Run a governance audit.")
    a.add_argument(
        "--config",
        help="Path to a config file (default: ./config.yaml if present, "
        "otherwise the bundled default config)",
    )
    a.add_argument(
        "--source",
        choices=["fixture", "datahub-lite", "datahub"],
        help="Override source",
    )
    a.add_argument("--url", help="DataHub URL (for --source datahub)")
    a.add_argument("--token", help="DataHub access token")
    a.add_argument("--model", help="Override Ollama model")
    a.add_argument("--no-llm", action="store_true", help="Skip the local LLM layer")
    a.add_argument(
        "--out",
        default=DEFAULT_OUT,
        help="Output directory, relative to the current directory (default: ./outputs)",
    )
    a.add_argument(
        "--fail-on-critical",
        action="store_true",
        help="Exit non-zero if any CRITICAL finding (CI mode)",
    )
    a.set_defaults(func=cmd_audit)
    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
