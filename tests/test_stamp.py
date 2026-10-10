import pytest

from sentinel_engine.ingest.stamp import stamp_metadata, validate_doc_id


def test_stamp_adds_tag_keys_and_access_tags():
    assert stamp_metadata(["public", "finance"], {"title": "Q4", "page": 2}) == {
        "title": "Q4",
        "page": 2,
        "tag_finance": True,
        "tag_public": True,
        "access_tags": "finance,public",
    }


@pytest.mark.parametrize(
    "metadata",
    [{"access_tags": "public"}, {"tag_public": True}, {"bad key": "x"}, {"nested": {"a": 1}}],
)
def test_caller_cannot_override_the_access_stamp(metadata):
    with pytest.raises(ValueError):
        stamp_metadata(["finance"], metadata)


@pytest.mark.parametrize("tags", [[], ["sentinel_admin"], ["*"], ['finance"']])
def test_document_tags_must_be_valid_and_unreserved(tags):
    with pytest.raises(ValueError):
        stamp_metadata(tags)


@pytest.mark.parametrize("doc_id", ["../x", "a/b", ".hidden", "", "a b", None])
def test_doc_ids_cannot_become_paths(doc_id):
    with pytest.raises(ValueError):
        validate_doc_id(doc_id)


def test_ordinary_doc_ids_pass():
    assert validate_doc_id("finance_q4-2025.v2") == "finance_q4-2025.v2"
