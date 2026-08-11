"""MyAnimeList als tracker (M7).

Officiële API v2, dus er is een contract en het mag gewoon. Twee dingen die
afwijken van wat je zou verwachten:

* **OAuth2 met PKCE, maar alleen ``plain``.** MyAnimeList ondersteunt geen
  S256; de code_challenge is letterlijk gelijk aan de code_verifier. Dat is
  hun keuze, niet de onze — daarom staat het hier expliciet in plaats van dat
  het op een fout lijkt.
* **De koppeling komt grotendeels gratis.** MangaDex geeft de MAL-id mee in de
  external links van een serie, dus die staat al in ``Series.tracker_ids``
  voordat een tracker ooit is ingesteld.
"""

from __future__ import annotations

import secrets
from typing import Any
from urllib.parse import urlencode

import httpx

from bookpal.ratelimit import RateLimiter
from bookpal.trackers.base import (
    PushResult,
    ReadingStatus,
    Tracker,
    TrackerEntry,
    TrackerError,
)

AUTH_BASE = "https://myanimelist.net/v1/oauth2"
API_BASE = "https://api.myanimelist.net/v2"

#: Onze statussen naar die van MyAnimeList.
_STATUS = {
    ReadingStatus.READING: "reading",
    ReadingStatus.COMPLETED: "completed",
    ReadingStatus.ON_HOLD: "on_hold",
    ReadingStatus.DROPPED: "dropped",
    ReadingStatus.PLAN_TO_READ: "plan_to_read",
}


def make_code_verifier() -> str:
    """Een PKCE-verifier. MyAnimeList wil 43–128 tekens."""
    return secrets.token_urlsafe(64)[:128]


def authorize_url(client_id: str, code_verifier: str, *, state: str | None = None) -> str:
    """De URL waar je je MyAnimeList-account koppelt.

    De challenge is gelijk aan de verifier: MyAnimeList kent alleen ``plain``.
    """
    params = {
        "response_type": "code",
        "client_id": client_id,
        "code_challenge": code_verifier,
        "code_challenge_method": "plain",
    }
    if state:
        params["state"] = state
    return f"{AUTH_BASE}/authorize?{urlencode(params)}"


class MyAnimeListTracker(Tracker):
    provider = "mal"

    def __init__(
        self,
        credentials: dict[str, Any],
        client: httpx.Client | None = None,
        *,
        rate: float = 2.0,
    ) -> None:
        self.credentials = credentials
        self._client = client or httpx.Client(timeout=30.0)
        self._limiter = RateLimiter(rate)

    # --- koppelen ---------------------------------------------------------

    def exchange_code(self, code: str, code_verifier: str) -> dict[str, Any]:
        """Wissel de code uit de browser in voor tokens."""
        response = self._post_token(
            {
                "client_id": self.credentials.get("client_id", ""),
                "client_secret": self.credentials.get("client_secret", ""),
                "grant_type": "authorization_code",
                "code": code,
                "code_verifier": code_verifier,
            }
        )
        return response

    def refresh(self) -> dict[str, Any]:
        """Ververs het access token met het refresh token."""
        refresh_token = self.credentials.get("refresh_token")
        if not refresh_token:
            raise TrackerError("geen refresh token; koppel het account opnieuw")
        return self._post_token(
            {
                "client_id": self.credentials.get("client_id", ""),
                "client_secret": self.credentials.get("client_secret", ""),
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
            }
        )

    def _post_token(self, data: dict[str, str]) -> dict[str, Any]:
        try:
            response = self._client.post(f"{AUTH_BASE}/token", data=data)
        except httpx.HTTPError as exc:
            raise TrackerError(f"MyAnimeList niet bereikbaar: {exc}") from exc
        if response.status_code >= 400:
            raise TrackerError(f"MyAnimeList weigerde de tokenaanvraag ({response.status_code})")
        payload: dict[str, Any] = response.json()
        # Meteen bijwerken, zodat de aanroeper alleen nog hoeft op te slaan.
        self.credentials = {**self.credentials, **payload}
        return payload

    # --- pushen -----------------------------------------------------------

    def push(self, entry: TrackerEntry, *, dry_run: bool) -> PushResult:
        if not entry.remote_id:
            return PushResult(
                entry=entry,
                pushed=False,
                dry_run=dry_run,
                detail="geen MyAnimeList-id op deze serie",
            )

        body: dict[str, Any] = {
            "status": _STATUS[entry.status],
            "num_chapters_read": entry.chapters_read,
        }
        if entry.volumes_read:
            body["num_volumes_read"] = entry.volumes_read
        if entry.score is not None:
            body["score"] = entry.score

        if dry_run:
            beschrijving = ", ".join(f"{key}={value}" for key, value in body.items())
            return PushResult(entry=entry, pushed=False, dry_run=True, detail=beschrijving)

        token = self.credentials.get("access_token")
        if not token:
            raise TrackerError("geen access token; koppel het account eerst")

        self._limiter.acquire()
        try:
            response = self._client.patch(
                f"{API_BASE}/manga/{entry.remote_id}/my_list_status",
                data=body,
                headers={"Authorization": f"Bearer {token}"},
            )
        except httpx.HTTPError as exc:
            # Zacht falen: het lezen mag hier nooit op stuklopen.
            return PushResult(entry=entry, pushed=False, dry_run=False, detail=f"netwerk: {exc}")

        if response.status_code == 401:
            raise TrackerError("MyAnimeList wees het token af; koppel opnieuw")
        if response.status_code >= 400:
            return PushResult(
                entry=entry,
                pushed=False,
                dry_run=False,
                detail=f"MyAnimeList gaf {response.status_code}",
            )
        return PushResult(entry=entry, pushed=True, dry_run=False)

    def close(self) -> None:
        self._client.close()
