import pytest

from later.security import check_token, item_token, topic_for


@pytest.fixture(autouse=True)
def secret(monkeypatch):
    monkeypatch.setenv("LATER_SECRET", "s3cret")


def test_token_round_trip():
    assert check_token("abc", item_token("abc"))


def test_token_is_per_item_and_per_secret(monkeypatch):
    t = item_token("abc")
    assert not check_token("abd", t)
    monkeypatch.setenv("LATER_SECRET", "other")
    assert not check_token("abc", t)


@pytest.mark.parametrize("bad", [None, "", "x" * 24])
def test_bad_tokens_rejected(bad):
    assert not check_token("abc", bad)


def test_topic_is_private_and_stable():
    a = topic_for("visitor-1")
    assert a == topic_for("visitor-1") and a != topic_for("visitor-2")
    assert a.startswith("later-") and len(a) == 26 and "visitor" not in a


def test_missing_secret_fails_loudly(monkeypatch):
    monkeypatch.delenv("LATER_SECRET")
    with pytest.raises(RuntimeError):
        item_token("abc")
