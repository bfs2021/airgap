"""MetadataGraph lineage lookups go through an index that follows `edges`."""
from airgap.model import LineageEdge, MetadataGraph


def test_lookups_follow_appended_and_replaced_edges():
    g = MetadataGraph()
    g.edges.append(LineageEdge("a", "b"))
    assert g.downstream("a") == ["b"]
    assert g.upstream("b") == ["a"]

    g.edges.append(LineageEdge("a", "c"))
    g.edges.append(LineageEdge("c", "d"))
    assert g.downstream("a") == ["b", "c"]
    assert g.transitive_downstream("a") == {"b", "c", "d"}

    g.edges = [LineageEdge("x", "a")]
    assert g.downstream("a") == []
    assert g.upstream("a") == ["x"]
    assert g.transitive_downstream("x") == {"a"}


def test_returned_lists_do_not_change_the_graph():
    g = MetadataGraph(edges=[LineageEdge("a", "b")])
    g.downstream("a").append("zzz")
    g.upstream("b").clear()
    assert g.downstream("a") == ["b"]
    assert g.upstream("b") == ["a"]
