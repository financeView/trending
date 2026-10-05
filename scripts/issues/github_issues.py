"""Minimal GitHub Issues REST helper (create-or-replace body)."""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Optional, Sequence


class GitHubError(RuntimeError):
    def __init__(self, message: str, *, status: int = 0) -> None:
        super().__init__(message)
        self.status = status


def _api(
    method: str,
    path: str,
    *,
    token: str,
    body: Optional[dict] = None,
    timeout: float = 30.0,
) -> Any:
    url = "https://api.github.com" + path
    data = None if body is None else json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": "Bearer %s" % token,
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "trending-p1-issues",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw) if raw else None
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")
        raise GitHubError(
            "%s %s -> %s %s" % (method, path, e.code, detail), status=int(e.code)
        ) from e


def ensure_labels(*, repo: str, labels: Sequence[str], token: str) -> None:
    for name in labels:
        quoted = urllib.parse.quote(name)
        try:
            _api("GET", "/repos/%s/labels/%s" % (repo, quoted), token=token)
        except GitHubError as e:
            if e.status != 404:
                raise
            _api(
                "POST",
                "/repos/%s/labels" % repo,
                token=token,
                body={"name": name, "color": "0e8a16"},
            )


def find_issue_by_title(
    *,
    repo: str,
    title: str,
    labels: Sequence[str],
    token: str,
) -> Optional[int]:
    """Exact title among issues with the given labels (all states). Not Search API."""
    label_q = urllib.parse.quote(",".join(labels))
    page = 1
    while True:
        path = (
            "/repos/%s/issues?labels=%s&state=all&per_page=100&page=%d"
            % (repo, label_q, page)
        )
        data = _api("GET", path, token=token) or []
        if not isinstance(data, list):
            return None
        for item in data:
            if item.get("title") == title and not item.get("pull_request"):
                return int(item["number"])
        if len(data) < 100:
            return None
        page += 1


def upsert_issue(
    *,
    title: str,
    body: str,
    labels: Sequence[str],
    token: str,
    repo: str,
) -> int:
    """Create or PATCH issue body. Returns issue number."""
    ensure_labels(repo=repo, labels=labels, token=token)
    num = find_issue_by_title(repo=repo, title=title, labels=labels, token=token)
    if num is None:
        created = _api(
            "POST",
            "/repos/%s/issues" % repo,
            token=token,
            body={"title": title, "body": body, "labels": list(labels)},
        )
        return int(created["number"])
    _api(
        "PATCH",
        "/repos/%s/issues/%d" % (repo, num),
        token=token,
        body={"body": body, "state": "open"},
    )
    return num


def default_repo() -> str:
    return os.environ.get("GITHUB_REPOSITORY", "").strip()


def default_token() -> str:
    return os.environ.get("GITHUB_TOKEN", "").strip() or os.environ.get(
        "GH_TOKEN", ""
    ).strip()
