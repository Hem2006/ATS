"""
Stitch ATS — Tiny GitHub public-API client for the Investigator Agent.

No auth needed for read-only public endpoints (60 req/hr per IP is more than
enough for a demo). Every function degrades gracefully on 404 / rate limit
so a private or missing profile never crashes the agent.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

import httpx


_UA = "Stitch-ATS-Investigator/1.0"
_TIMEOUT = 12.0


def extract_username(url_or_handle: Optional[str]) -> Optional[str]:
    """
    Accepts anything a candidate might paste and returns the bare GitHub
    username, or None if nothing usable is present.

    Handles:
      https://github.com/torvalds
      github.com/torvalds/
      @torvalds
      torvalds
    """
    if not url_or_handle:
        return None
    s = url_or_handle.strip().rstrip("/")
    m = re.search(r"github\.com/([^/\s?#]+)", s, re.IGNORECASE)
    if m:
        return m.group(1)
    s = s.lstrip("@")
    # Basic sanity — GitHub usernames are alnum + hyphens, 1-39 chars.
    if re.match(r"^[A-Za-z0-9-]{1,39}$", s):
        return s
    return None


def _client() -> httpx.Client:
    # verify=False mirrors the rest of the codebase (corporate SSL friendliness)
    return httpx.Client(
        headers={"User-Agent": _UA, "Accept": "application/vnd.github+json"},
        verify=False,
        timeout=_TIMEOUT,
    )


def fetch_profile(username: str) -> Dict[str, Any]:
    """Return a compact profile dict or {'error': ...}."""
    with _client() as c:
        r = c.get(f"https://api.github.com/users/{username}")
        if r.status_code == 404:
            return {"error": "not_found", "username": username}
        if r.status_code == 403:
            return {"error": "rate_limited", "username": username}
        if r.status_code >= 400:
            return {"error": f"http_{r.status_code}", "username": username}
        d = r.json()
        return {
            "username":   d.get("login"),
            "name":       d.get("name"),
            "bio":        d.get("bio"),
            "company":    d.get("company"),
            "location":   d.get("location"),
            "public_repos": d.get("public_repos", 0),
            "followers":  d.get("followers", 0),
            "following":  d.get("following", 0),
            "created_at": d.get("created_at"),
            "updated_at": d.get("updated_at"),
            "html_url":   d.get("html_url"),
        }


def fetch_repos(username: str, limit: int = 30) -> List[Dict[str, Any]]:
    """Compact per-repo dicts, sorted by most recently updated."""
    with _client() as c:
        r = c.get(
            f"https://api.github.com/users/{username}/repos",
            params={"sort": "updated", "per_page": limit, "type": "owner"},
        )
        if r.status_code >= 400:
            return []
        out = []
        for d in r.json():
            if d.get("fork"):
                continue  # forks aren't evidence of actual work
            out.append({
                "name":     d.get("name"),
                "full_name":d.get("full_name"),
                "language": d.get("language"),
                "stars":    d.get("stargazers_count", 0),
                "forks":    d.get("forks_count", 0),
                "size_kb":  d.get("size", 0),
                "created_at": d.get("created_at"),
                "updated_at": d.get("updated_at"),
                "pushed_at":  d.get("pushed_at"),
                "description": d.get("description"),
                "url":      d.get("html_url"),
                "default_branch": d.get("default_branch") or "main",
            })
        return out


def fetch_readme(full_name: str, branch: str = "main", max_chars: int = 4000) -> Dict[str, Any]:
    """
    Fetch a repo's README. Tries a few common paths / branches because GitHub
    varies. Returns {'content': str} or {'error': ...}.
    """
    urls = [
        f"https://raw.githubusercontent.com/{full_name}/{branch}/README.md",
        f"https://raw.githubusercontent.com/{full_name}/main/README.md",
        f"https://raw.githubusercontent.com/{full_name}/master/README.md",
        f"https://raw.githubusercontent.com/{full_name}/{branch}/readme.md",
    ]
    with _client() as c:
        for u in urls:
            try:
                r = c.get(u)
                if r.status_code == 200 and r.text.strip():
                    return {"content": r.text[:max_chars], "source": u}
            except Exception:
                continue
    return {"error": "no_readme_found", "full_name": full_name}


def summarize_repos(repos: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Reduce a repo list to signals the agent can reason about without
    burning the LLM's context on 30 objects.
    """
    if not repos:
        return {"count": 0, "languages": {}, "total_stars": 0, "oldest": None, "newest": None}
    langs: Dict[str, int] = {}
    total_stars = 0
    dates = []
    for r in repos:
        lang = r.get("language") or "unknown"
        langs[lang] = langs.get(lang, 0) + 1
        total_stars += r.get("stars", 0)
        for k in ("created_at", "updated_at", "pushed_at"):
            if r.get(k):
                dates.append(r[k])
    dates.sort()
    return {
        "count": len(repos),
        "languages": dict(sorted(langs.items(), key=lambda kv: -kv[1])),
        "total_stars": total_stars,
        "oldest": dates[0] if dates else None,
        "newest": dates[-1] if dates else None,
    }
