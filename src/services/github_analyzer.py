"""Fetch and analyse a candidate's public GitHub repositories.

Uses the public REST API. With ``GITHUB_TOKEN`` (in ``.env``) the rate limit
goes from 60 req/h to 5000 req/h, which is plenty for MVP usage.

We only download a small README excerpt (~5 KB) per repo and sniff the
languages and topics. The README plus the repo metadata is then used to
build a list of detected technologies and a rough relevance score against
the target job posting.
"""
from __future__ import annotations

import base64
import logging
import re
from collections.abc import Iterable

import requests

from ..models.candidate import GitHubProject
from ..models.job import JobPosting

logger = logging.getLogger(__name__)

_API = "https://api.github.com"
_USER_AGENT = "ApplyPilotAI/0.1"
_README_LIMIT = 5000  # bytes
_DEFAULT_MAX_REPOS = 15
_DEFAULT_TIMEOUT = 20


# Technology keywords sniffed from README excerpts and topics. Lowercase.
_TECH_KEYWORDS: tuple[str, ...] = (
    "python", "java", "javascript", "typescript", "go", "rust", "c#", "c++",
    "ruby", "php", "kotlin", "swift",
    "fastapi", "django", "flask", "express", "react", "vue", "angular",
    "next.js", "nextjs", "node.js", "nodejs",
    "pytest", "unittest", "jest", "vitest", "mocha", "selenium", "playwright",
    "cypress", "appium",
    "postman", "rest api", "graphql", "grpc",
    "postgres", "postgresql", "mysql", "mongodb", "sqlite", "redis",
    "docker", "kubernetes", "terraform", "ansible",
    "github actions", "gitlab ci", "jenkins", "circleci",
    "aws", "azure", "gcp", "google cloud",
    "openai", "anthropic", "groq", "mistral", "ollama", "langchain", "llama-index",
    "rag", "vector database", "pgvector", "faiss", "chroma", "pinecone",
    "pytorch", "tensorflow", "scikit-learn", "pandas", "numpy",
    "powerbi", "tableau", "looker", "dbt", "airflow", "spark",
    "linux", "bash", "ci/cd", "tdd", "bdd", "page object",
)


class GitHubError(RuntimeError):
    """Raised when the GitHub REST API returns an unrecoverable error."""


def _headers(token: str | None) -> dict[str, str]:
    h = {"User-Agent": _USER_AGENT, "Accept": "application/vnd.github+json"}
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h


def _detect_techs(text: str, extra: Iterable[str] = ()) -> list[str]:
    if not text and not list(extra):
        return []
    haystack = (text or "").lower() + " " + " ".join(s.lower() for s in extra)
    found: list[str] = []
    for keyword in _TECH_KEYWORDS:
        if re.search(rf"(?<![a-z0-9]){re.escape(keyword)}(?![a-z0-9])", haystack):
            found.append(keyword)
    return found


def _score_relevance(project: GitHubProject, job: JobPosting | None) -> tuple[float, str]:
    if job is None:
        return 0.0, ""
    job_terms = {
        s.lower()
        for s in (job.required_skills + job.nice_to_have_skills + job.technologies + job.ats_keywords)
    }
    if not job_terms:
        return 0.0, ""
    project_terms = set()
    project_terms.update(t.lower() for t in project.detected_technologies)
    project_terms.update(t.lower() for t in project.topics)
    project_terms.update(t.lower() for t in project.languages)
    if project.primary_language:
        project_terms.add(project.primary_language.lower())

    overlap = job_terms & project_terms
    if not overlap:
        return 0.0, ""
    score = min(len(overlap) / 5.0, 1.0)
    reason = "Matches: " + ", ".join(sorted(overlap)[:5])
    return score, reason


def fetch_github_projects(
    username: str,
    token: str | None = None,
    *,
    max_repos: int = _DEFAULT_MAX_REPOS,
    job: JobPosting | None = None,
    timeout: int = _DEFAULT_TIMEOUT,
) -> list[GitHubProject]:
    """Return up to ``max_repos`` analysed public repositories."""
    username = (username or "").strip().lstrip("@")
    if not username:
        return []
    headers = _headers(token)

    try:
        resp = requests.get(
            f"{_API}/users/{username}/repos",
            params={"sort": "updated", "per_page": max_repos, "type": "owner"},
            headers=headers,
            timeout=timeout,
        )
    except requests.RequestException as exc:
        raise GitHubError(f"Network error contacting GitHub: {exc}") from exc

    if resp.status_code == 404:
        raise GitHubError(f"GitHub user '{username}' not found.")
    if resp.status_code == 403:
        msg = resp.json().get("message", "rate limited") if resp.text else "rate limited"
        raise GitHubError(
            f"GitHub returned 403 ({msg}). Add a GITHUB_TOKEN to .env to raise the limit."
        )
    if resp.status_code >= 400:
        raise GitHubError(f"GitHub returned HTTP {resp.status_code}: {resp.text[:200]}")

    repos = resp.json() or []
    projects: list[GitHubProject] = []
    for repo in repos:
        if repo.get("fork"):
            continue
        readme = _fetch_readme(username, repo["name"], headers, timeout)
        languages = _fetch_languages(username, repo["name"], headers, timeout)
        topics = repo.get("topics") or []
        techs = _detect_techs(readme, extra=topics + languages + [repo.get("language") or ""])
        project = GitHubProject(
            name=repo["name"],
            url=repo.get("html_url", ""),
            description=repo.get("description"),
            primary_language=repo.get("language"),
            languages=languages,
            topics=topics,
            stars=int(repo.get("stargazers_count") or 0),
            forks=int(repo.get("forks_count") or 0),
            last_updated=repo.get("updated_at"),
            readme_excerpt=(readme or None),
            detected_technologies=techs,
        )
        score, reason = _score_relevance(project, job)
        object.__setattr__(project, "relevance_score", score)
        object.__setattr__(project, "relevance_reason", reason or None)
        projects.append(project)

    # Sort by job relevance first, then by stars.
    projects.sort(key=lambda p: (-p.relevance_score, -p.stars))
    return projects


def _fetch_readme(
    user: str, repo: str, headers: dict[str, str], timeout: int
) -> str:
    try:
        resp = requests.get(
            f"{_API}/repos/{user}/{repo}/readme",
            headers=headers,
            timeout=timeout,
        )
    except requests.RequestException as exc:
        logger.debug("README fetch failed for %s/%s: %s", user, repo, exc)
        return ""
    if resp.status_code != 200:
        return ""
    payload = resp.json() or {}
    encoding = payload.get("encoding") or "base64"
    content = payload.get("content") or ""
    if encoding != "base64":
        return content[:_README_LIMIT]
    try:
        decoded = base64.b64decode(content)
        return decoded[:_README_LIMIT].decode("utf-8", errors="replace")
    except Exception:
        return ""


def _fetch_languages(
    user: str, repo: str, headers: dict[str, str], timeout: int
) -> list[str]:
    try:
        resp = requests.get(
            f"{_API}/repos/{user}/{repo}/languages",
            headers=headers,
            timeout=timeout,
        )
    except requests.RequestException:
        return []
    if resp.status_code != 200:
        return []
    payload = resp.json() or {}
    return list(payload.keys())


__all__ = ["fetch_github_projects", "GitHubError"]
