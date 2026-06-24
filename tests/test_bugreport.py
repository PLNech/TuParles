"""Prefilled GitHub bug-report URL (#87) — pure, offline, no token.

Per the project's #87 decision: a public repo can't ship a usable token, so we
build a `.../issues/new?title=…&body=…` URL the user opens. These tests pin the
encoding and that the environment block rides along.
"""

from urllib.parse import parse_qs, urlparse

from tuparles import bugreport


def test_points_at_the_repo_new_issue():
    url = bugreport.issue_url("test")
    parsed = urlparse(url)
    assert parsed.netloc == "github.com"
    assert parsed.path == "/PLNech/TuParles/issues/new"


def test_title_and_body_are_url_encoded():
    url = bugreport.issue_url("crash sur é & ô", "ça plante", include_env=False)
    q = parse_qs(urlparse(url).query)
    assert q["title"] == ["crash sur é & ô"]  # parse_qs round-trips the encoding
    assert q["body"] == ["ça plante"]
    assert "%20" in url and "%26" in url  # spaces and & actually escaped in the raw URL


def test_environment_block_appended_by_default():
    url = bugreport.issue_url("titre", "corps")
    body = parse_qs(urlparse(url).query)["body"][0]
    assert "corps" in body
    assert "### Environnement" in body
    assert "TuParles :" in body and "Session :" in body


def test_environment_block_has_session_and_versions():
    block = bugreport.environment_block()
    assert "Python :" in block and "OS :" in block
    assert ("Wayland" in block) or ("X11" in block)


def test_include_env_false_omits_block():
    body = parse_qs(urlparse(bugreport.issue_url("t", "b", include_env=False)).query)[
        "body"
    ][0]
    assert "Environnement" not in body
