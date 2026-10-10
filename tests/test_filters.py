import pytest

from sentinel_engine.filters import (
    authorize_chunks,
    build_bedrock_filter,
    build_chroma_where,
    build_managed_search_config,
    build_vector_search_config,
    chunk_authorized,
    document_tags,
    normalize_tags,
)


def test_single_tag_bedrock_filter_is_a_bare_condition():
    assert build_bedrock_filter({"finance"}) == {"equals": {"key": "tag_finance", "value": True}}


def test_multi_tag_bedrock_filter_is_a_sorted_or():
    assert build_bedrock_filter(["public", "finance"]) == {
        "orAll": [
            {"equals": {"key": "tag_finance", "value": True}},
            {"equals": {"key": "tag_public", "value": True}},
        ]
    }


def test_filters_are_order_independent():
    assert build_bedrock_filter(["b", "a", "c"]) == build_bedrock_filter({"c", "a", "b"})
    assert build_chroma_where(["b", "a"]) == build_chroma_where(("a", "b"))


@pytest.mark.parametrize("builder", [build_bedrock_filter, build_chroma_where])
def test_empty_scope_never_becomes_match_all(builder):
    with pytest.raises(ValueError):
        builder(set())


@pytest.mark.parametrize("bad", ["", "*", 'finance" OR 1=1', "a b", "a,b", "x" * 200, "-lead"])
def test_invalid_tags_are_rejected(bad):
    with pytest.raises(ValueError):
        build_bedrock_filter({bad})


def test_iam_style_tags_are_valid():
    assert normalize_tags(["Project:Omega", "dept.finance"]) == ["Project:Omega", "dept.finance"]


def test_mcp_and_gateway_paths_push_identical_filters():
    tags = {"finance", "engineering", "public"}
    standard = build_vector_search_config(tags, 5)["vectorSearchConfiguration"]["filter"]
    managed = build_managed_search_config(tags, 5)["managedSearchConfiguration"]["filter"]
    assert standard == managed


def test_chroma_where_shape():
    assert build_chroma_where({"finance", "public"}) == {
        "$or": [{"tag_finance": {"$eq": True}}, {"tag_public": {"$eq": True}}]
    }


def test_document_tags_prefers_access_tags_field():
    meta = {"access_tags": "finance,engineering", "tag_public": True}
    assert document_tags(meta) == {"finance", "engineering"}


def test_document_tags_falls_back_to_tag_keys():
    assert document_tags({"tag_finance": True, "tag_hr": False}) == {"finance"}


def test_untagged_chunk_is_never_authorized():
    assert not chunk_authorized({"title": "orphan"}, {"public"})


def test_authorize_chunks_drops_what_the_scope_cannot_see():
    chunks = [
        {"text": "a", "metadata": {"access_tags": "public"}, "score": 0.9},
        {"text": "b", "metadata": {"access_tags": "finance"}, "score": 0.8},
        {"text": "c", "metadata": {}, "score": 0.7},
    ]
    assert [c["text"] for c in authorize_chunks(chunks, {"public"})] == ["a"]
