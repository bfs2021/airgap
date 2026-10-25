"""DataHubLiteSource reads the catalog with one `datahub lite export` (#26).

A fake `datahub` executable stands in for the real CLI, so these tests need
neither DataHub nor DuckDB. It logs every subcommand it is asked to run.
"""
import json
import os
import stat
import sys

import pytest

from airgap.sources.datahub_lite import DataHubLiteFormatError, DataHubLiteSource

DS = "urn:li:dataset:(urn:li:dataPlatform:postgres,app.users,PROD)"
DOWN = "urn:li:dataset:(urn:li:dataPlatform:snowflake,wh.mart,PROD)"
DASH = "urn:li:dashboard:(looker,sales)"

DOCS = {
    DS: {
        "datasetProperties": {"name": "users"},
        "schemaMetadata": {"fields": [
            {"fieldPath": "email", "globalTags": {"tags": [{"tag": "urn:li:tag:PII"}]}},
        ]},
    },
    DOWN: {
        "datasetProperties": {"name": "mart"},
        "schemaMetadata": {"fields": [{"fieldPath": "email"}]},
        "upstreamLineage": {
            "upstreams": [{"dataset": DS}],
            "fineGrainedLineages": [{
                "upstreams": [f"urn:li:schemaField:({DS},email)"],
                "downstreams": [f"urn:li:schemaField:({DOWN},email)"],
            }],
        },
    },
    DASH: {"dashboardInfo": {"title": "Sales", "datasets": [DOWN]}},
}


def _mcps(docs):
    return [
        {"entityType": "x", "entityUrn": urn, "changeType": "UPSERT",
         "aspectName": name, "aspect": {"json": value}}
        for urn, aspects in docs.items()
        for name, value in aspects.items()
    ]


_FAKE = '''#!{python}
import json, sys
spec = json.load(open({spec!r}))
args = sys.argv[1:]
with open({log!r}, "a") as fh:
    fh.write(args[1] + "\\n")
if args[1] == "export":
    if spec["export"] is None:
        sys.stderr.write("Error: export is broken\\n")
        sys.exit(1)
    with open(args[args.index("--file") + 1], "w") as fh:
        fh.write(spec["export"])
elif args[1] == "list-urns":
    print("\\n".join(spec["docs"]))
elif args[1] == "get":
    urn = args[args.index("--urn") + 1]
    print(json.dumps(dict(spec["docs"][urn], urn=urn)))
'''


@pytest.fixture
def fake(tmp_path):
    """Build a fake datahub CLI; returns (source, log_lines)."""
    def make(export, docs=DOCS):
        spec, log = tmp_path / "spec.json", tmp_path / "calls.log"
        spec.write_text(json.dumps({"export": export, "docs": docs}))
        log.write_text("")
        exe = tmp_path / "datahub"
        exe.write_text(_FAKE.format(python=sys.executable, spec=str(spec), log=str(log)))
        exe.chmod(exe.stat().st_mode | stat.S_IXUSR)
        src = DataHubLiteSource(str(exe))
        return src, lambda: log.read_text().split()
    if os.name == "nt":
        pytest.skip("the fake datahub script needs a POSIX shebang")
    return make


def _shape(graph):
    return (
        sorted((a.urn, a.name, a.entity_type, a.fields) for a in graph.assets.values()),
        sorted(graph.edges, key=repr),
        sorted(graph.field_edges, key=repr),
    )


def test_one_export_call_reads_the_whole_catalog(fake):
    src, calls = fake(json.dumps(_mcps(DOCS)))
    graph = src.fetch()
    assert calls() == ["export"]
    assert len(graph.assets) == 3
    assert len(graph.edges) == 2 and len(graph.field_edges) == 1
    assert graph.assets[DS].fields[0].tags == ("PII",)


def test_export_and_per_urn_reads_give_the_same_graph(fake):
    src, calls = fake(json.dumps(_mcps(DOCS)))
    via_export = _shape(src.fetch())
    src, calls = fake(None)
    via_get = _shape(src.fetch())
    assert via_export == via_get


def test_failed_export_falls_back_to_per_urn_reads(fake, capsys):
    src, calls = fake(None)
    graph = src.fetch()
    assert calls() == ["export", "list-urns", "get", "get", "get"]
    assert len(graph.assets) == 3
    err = capsys.readouterr().err
    assert "export is broken; reading entities one by one instead (slower)." in err


@pytest.mark.parametrize(
    "export, detail",
    [
        ("not json", "not valid JSON"),
        (json.dumps({"entities": []}), "expected a JSON list, got dict"),
        (json.dumps(["urn:li:x"]), "item 0 is a str"),
        (json.dumps([{"aspectName": "a", "aspect": {"json": {}}}]), "no string 'entityUrn'"),
        (json.dumps([{"entityUrn": DS, "aspect": {"json": {}}}]), "no string 'aspectName'"),
        (json.dumps([{"entityUrn": DS, "aspectName": "a", "aspect": {"value": "{}"}}]),
         "no object at 'aspect.json'"),
        (json.dumps([]), "no entities, but `datahub lite list-urns` lists some"),
    ],
)
def test_unexpected_export_format_fails_loudly(fake, export, detail):
    src, calls = fake(export)
    with pytest.raises(DataHubLiteFormatError) as info:
        src.fetch()
    msg = str(info.value)
    assert "`datahub lite export` returned an unexpected format" in msg
    assert detail in msg
    assert "get" not in calls()  # no silent fallback on a format problem


def test_cli_reports_an_unexpected_export_format_as_an_error(fake, tmp_path, monkeypatch, capsys):
    from airgap.cli import main

    src, _ = fake(json.dumps({"entities": []}))
    cfg = tmp_path / "cfg.yaml"
    cfg.write_text(f"source: datahub-lite\ndatahub_lite:\n  bin: {src.datahub_bin}\n")
    monkeypatch.chdir(tmp_path)
    assert main(["audit", "--config", str(cfg), "--out", str(tmp_path / "out")]) == 1
    last = capsys.readouterr().err.strip().splitlines()[-1]
    assert last.startswith("airgap: error: `datahub lite export` returned an unexpected format")
    assert "expected a JSON list, got dict" in last


def test_empty_export_of_an_empty_catalog_is_an_empty_graph(fake):
    src, calls = fake(json.dumps([]), docs={})
    assert len(src.fetch().assets) == 0
    assert calls() == ["export", "list-urns"]


def test_export_temp_file_is_removed(fake, tmp_path, monkeypatch):
    import tempfile

    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    src, _ = fake(json.dumps(_mcps(DOCS)))
    src.fetch()
    assert not list(tmp_path.glob("airgap-lite-export-*"))
