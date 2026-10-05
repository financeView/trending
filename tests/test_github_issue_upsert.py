from scripts.issues import github_issues as gi


def test_upsert_lists_by_label_not_search(monkeypatch):
    calls = []
    issues = []

    def fake_api(method, path, *, token, body=None, timeout=30.0):
        calls.append((method, path, body))
        if method == "GET" and "/labels/" in path:
            raise gi.GitHubError("GET %s -> 404" % path, status=404)
        if method == "POST" and path.endswith("/labels"):
            return {"name": body["name"]}
        if method == "GET" and "/issues" in path and "search" not in path:
            return list(issues)
        if method == "POST" and path.endswith("/issues"):
            issues.append({"number": 42, "title": body["title"], "pull_request": None})
            return {"number": 42}
        if method == "PATCH":
            return {"number": 42}
        raise AssertionError((method, path))

    monkeypatch.setattr(gi, "_api", fake_api)
    n1 = gi.upsert_issue(
        title="[L1] 金融 (l1_finance)",
        body="v1",
        labels=["l1-dashboard"],
        token="t",
        repo="o/r",
    )
    assert n1 == 42
    assert not any("/search/" in c[1] for c in calls)
    assert any(c[0] == "POST" and c[1].endswith("/issues") for c in calls)
    n2 = gi.upsert_issue(
        title="[L1] 金融 (l1_finance)",
        body="v2",
        labels=["l1-dashboard"],
        token="t",
        repo="o/r",
    )
    assert n2 == 42
    assert any(c[0] == "PATCH" for c in calls)
    patch = next(c for c in calls if c[0] == "PATCH")
    assert "labels" not in (patch[2] or {})


def test_find_ignores_near_miss_title(monkeypatch):
    def fake_api(method, path, *, token, body=None, timeout=30.0):
        if method == "GET" and "/labels/" in path:
            return {"name": "l1-dashboard"}
        if method == "GET" and "/issues" in path:
            return [
                {"number": 7, "title": "[L1] 金融 (l1_finance) extra"},
                {"number": 8, "title": "[L1] 金融 (l1_finance)"},
            ]
        raise AssertionError((method, path))

    monkeypatch.setattr(gi, "_api", fake_api)
    num = gi.find_issue_by_title(
        repo="o/r",
        title="[L1] 金融 (l1_finance)",
        labels=["l1-dashboard"],
        token="t",
    )
    assert num == 8
