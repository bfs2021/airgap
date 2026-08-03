from airgap.sources.base import MetadataSource
from airgap.sources.fixture import FixtureSource
from airgap.sources.datahub import DataHubSource

__all__ = ["MetadataSource", "FixtureSource", "DataHubSource", "build_source"]


def build_source(cfg: dict) -> MetadataSource:
    """Construct the metadata source selected in config."""
    kind = cfg.get("source", "fixture")
    if kind == "fixture":
        return FixtureSource(cfg["fixture_path"])
    if kind == "datahub":
        dh = cfg.get("datahub", {})
        return DataHubSource(
            url=dh.get("url", ""),
            token=dh.get("token", ""),
            lineage_depth=int(dh.get("lineage_depth", 4)),
        )
    raise ValueError(f"Unknown source: {kind!r} (expected 'fixture' or 'datahub')")
