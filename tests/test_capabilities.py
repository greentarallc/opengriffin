"""Capability token: mint, verify, scope-cover, expiry."""

from opengriffin import capabilities as caps


def test_mint_and_verify_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(caps, "CAPS_FILE", tmp_path / "capabilities.json")
    monkeypatch.setattr(caps, "SECRET_PATH", tmp_path / "secret")

    tok = caps.mint("Bash", ttl_seconds=3600, cap_usd=5.0, note="test")
    assert tok["scope"] == "Bash"
    assert tok["cap_usd"] == 5.0

    verified = caps.verify(tok["id"])
    assert verified is not None
    assert verified["id"] == tok["id"]


def test_scope_coverage(tmp_path, monkeypatch):
    monkeypatch.setattr(caps, "CAPS_FILE", tmp_path / "capabilities.json")
    monkeypatch.setattr(caps, "SECRET_PATH", tmp_path / "secret")

    tok = caps.mint("Bash:git*", ttl_seconds=3600)
    assert caps.covers(tok, "Bash:git push")
    assert caps.covers(tok, "Bash:git status")
    assert not caps.covers(tok, "Bash:rm -rf")


def test_expired_token_invalid(tmp_path, monkeypatch):
    monkeypatch.setattr(caps, "CAPS_FILE", tmp_path / "capabilities.json")
    monkeypatch.setattr(caps, "SECRET_PATH", tmp_path / "secret")

    tok = caps.mint("Bash", ttl_seconds=-1)
    assert caps.verify(tok["id"]) is None


def test_revoke_removes_token(tmp_path, monkeypatch):
    monkeypatch.setattr(caps, "CAPS_FILE", tmp_path / "capabilities.json")
    monkeypatch.setattr(caps, "SECRET_PATH", tmp_path / "secret")

    tok = caps.mint("Bash", ttl_seconds=3600)
    assert caps.revoke(tok["id"])
    assert caps.verify(tok["id"]) is None
