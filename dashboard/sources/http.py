"""Minimal JSON-over-HTTPS clients; tokens stay in memory and are never logged."""

from __future__ import annotations

import json
from collections.abc import Callable
from urllib.request import Request, urlopen

TIMEOUT_S = 20
MANAGEMENT_SCOPE = "https://management.azure.com/.default"
SRE_SCOPE = "https://azuresre.dev/.default"


def get_json(url: str, headers: dict[str, str]) -> object:
    request = Request(url, headers={"Accept": "application/json", **headers})
    with urlopen(request, timeout=TIMEOUT_S) as response:
        return json.load(response)


class AzureRest:
    """GET with a bearer token from azure-identity for the requested scope."""

    def __init__(self, token_for: Callable[[str], str]) -> None:
        self._token_for = token_for

    def get(self, url: str, scope: str = MANAGEMENT_SCOPE) -> object:
        return get_json(url, {"Authorization": f"Bearer {self._token_for(scope)}"})


class GitHubRest:
    def __init__(self, token: str) -> None:
        self._headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    def get(self, path: str) -> object:
        return get_json(f"https://api.github.com{path}", self._headers)
