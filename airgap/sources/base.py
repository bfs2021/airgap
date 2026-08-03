"""Metadata source interface.

Every source (fixture or live DataHub) returns the same normalized
`MetadataGraph`, so nothing downstream needs to know where metadata came from.
"""
from __future__ import annotations

from abc import ABC, abstractmethod

from airgap.model import MetadataGraph


class MetadataSource(ABC):
    #: Human-readable label shown in reports.
    name: str = "source"

    @abstractmethod
    def fetch(self) -> MetadataGraph:
        """Return the fully normalized metadata graph."""
        raise NotImplementedError
