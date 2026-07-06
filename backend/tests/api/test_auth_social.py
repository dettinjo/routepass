from __future__ import annotations

"""Tests for Google and GitHub OAuth login/callback endpoints."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient

# ── Google ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_google_login_redirects(async_client: AsyncClient) -> None:
    """GET /api/v1/auth/google should redirect to Google's OAuth endpoint."""
    response = await async_client.get("/api/v1/auth/google", follow_redirects=False)
    assert response.status_code == 302
    location = response.headers["location"]
    assert "accounts.google.com/o/oauth2/v2/auth" in location
    assert "response_type=code" in location
    assert "scope=openid" in location
    # CSRF state cookie must be set
    assert "oauth_state" in response.cookies


@pytest.mark.asyncio
async def test_google_callback_creates_user_and_redirects(
    async_client: AsyncClient,
) -> None:
    """A valid Google callback creates (or finds) the user and redirects with a JWT."""
    # First hit /google to get a real state cookie
    login_resp = await async_client.get("/api/v1/auth/google", follow_redirects=False)
    state = login_resp.cookies["oauth_state"]

    # Mock the two httpx calls: token exchange + userinfo
    token_response = MagicMock()
    token_response.raise_for_status.return_value = None
    token_response.json.return_value = {"access_token": "google_at"}

    userinfo_response = MagicMock()
    userinfo_response.raise_for_status.return_value = None
    userinfo_response.json.return_value = {"email": "googleuser@example.com"}

    mock_client = AsyncMock()
    mock_client.__aenter__.return_value = mock_client
    mock_client.__aexit__.return_value = None
    mock_client.post.return_value = token_response
    mock_client.get.return_value = userinfo_response

    with patch("app.api.v1.auth.httpx.AsyncClient", return_value=mock_client):
        callback_resp = await async_client.get(
            "/api/v1/auth/google/callback",
            params={"code": "auth_code", "state": state},
            cookies={"oauth_state": state},
            follow_redirects=False,
        )

    assert callback_resp.status_code == 302
    location = callback_resp.headers["location"]
    assert "/callback" in location
    assert "token=" in location


@pytest.mark.asyncio
async def test_google_callback_invalid_state(async_client: AsyncClient) -> None:
    """Mismatched CSRF state is rejected with 400."""
    response = await async_client.get(
        "/api/v1/auth/google/callback",
        params={"code": "auth_code", "state": "wrong_state"},
        cookies={"oauth_state": "correct_state"},
        follow_redirects=False,
    )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_google_callback_missing_state_cookie(async_client: AsyncClient) -> None:
    """Missing CSRF cookie is rejected with 400."""
    response = await async_client.get(
        "/api/v1/auth/google/callback",
        params={"code": "auth_code", "state": "some_state"},
        follow_redirects=False,
    )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_google_callback_no_email(async_client: AsyncClient) -> None:
    """Google returning no email is rejected with 400."""
    login_resp = await async_client.get("/api/v1/auth/google", follow_redirects=False)
    state = login_resp.cookies["oauth_state"]

    token_response = MagicMock()
    token_response.raise_for_status.return_value = None
    token_response.json.return_value = {"access_token": "google_at"}

    userinfo_response = MagicMock()
    userinfo_response.raise_for_status.return_value = None
    userinfo_response.json.return_value = {}  # no email field

    mock_client = AsyncMock()
    mock_client.__aenter__.return_value = mock_client
    mock_client.__aexit__.return_value = None
    mock_client.post.return_value = token_response
    mock_client.get.return_value = userinfo_response

    with patch("app.api.v1.auth.httpx.AsyncClient", return_value=mock_client):
        response = await async_client.get(
            "/api/v1/auth/google/callback",
            params={"code": "auth_code", "state": state},
            cookies={"oauth_state": state},
            follow_redirects=False,
        )

    assert response.status_code == 400


# ── GitHub ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_github_login_redirects(async_client: AsyncClient) -> None:
    """GET /api/v1/auth/github should redirect to GitHub's OAuth endpoint."""
    response = await async_client.get("/api/v1/auth/github", follow_redirects=False)
    assert response.status_code == 302
    location = response.headers["location"]
    assert "github.com/login/oauth/authorize" in location
    assert "scope=user" in location
    assert "oauth_state" in response.cookies


@pytest.mark.asyncio
async def test_github_callback_creates_user_and_redirects(
    async_client: AsyncClient,
) -> None:
    """A valid GitHub callback creates (or finds) the user and redirects with a JWT."""
    login_resp = await async_client.get("/api/v1/auth/github", follow_redirects=False)
    state = login_resp.cookies["oauth_state"]

    token_response = MagicMock()
    token_response.raise_for_status.return_value = None
    token_response.json.return_value = {"access_token": "github_at"}

    emails_response = MagicMock()
    emails_response.raise_for_status.return_value = None
    emails_response.json.return_value = [
        {"email": "other@example.com", "primary": False, "verified": True},
        {"email": "githubuser@example.com", "primary": True, "verified": True},
    ]

    profile_response = MagicMock()
    profile_response.raise_for_status.return_value = None
    profile_response.json.return_value = {"name": "GitHub User", "login": "githubuser"}

    mock_client = AsyncMock()
    mock_client.__aenter__.return_value = mock_client
    mock_client.__aexit__.return_value = None
    mock_client.post.return_value = token_response
    # First GET → emails, second GET → user profile
    mock_client.get.side_effect = [emails_response, profile_response]

    with patch("app.api.v1.auth.httpx.AsyncClient", return_value=mock_client):
        callback_resp = await async_client.get(
            "/api/v1/auth/github/callback",
            params={"code": "auth_code", "state": state},
            cookies={"oauth_state": state},
            follow_redirects=False,
        )

    assert callback_resp.status_code == 302
    location = callback_resp.headers["location"]
    assert "/callback" in location
    assert "token=" in location


@pytest.mark.asyncio
async def test_github_callback_no_verified_primary_email(
    async_client: AsyncClient,
) -> None:
    """GitHub returning no verified primary email is rejected with 400."""
    login_resp = await async_client.get("/api/v1/auth/github", follow_redirects=False)
    state = login_resp.cookies["oauth_state"]

    token_response = MagicMock()
    token_response.raise_for_status.return_value = None
    token_response.json.return_value = {"access_token": "github_at"}

    emails_response = MagicMock()
    emails_response.raise_for_status.return_value = None
    emails_response.json.return_value = [
        {"email": "unverified@example.com", "primary": True, "verified": False},
    ]

    profile_response = MagicMock()
    profile_response.raise_for_status.return_value = None
    profile_response.json.return_value = {"login": "user"}

    mock_client = AsyncMock()
    mock_client.__aenter__.return_value = mock_client
    mock_client.__aexit__.return_value = None
    mock_client.post.return_value = token_response
    mock_client.get.side_effect = [emails_response, profile_response]

    with patch("app.api.v1.auth.httpx.AsyncClient", return_value=mock_client):
        response = await async_client.get(
            "/api/v1/auth/github/callback",
            params={"code": "auth_code", "state": state},
            cookies={"oauth_state": state},
            follow_redirects=False,
        )

    assert response.status_code == 400


@pytest.mark.asyncio
async def test_github_callback_invalid_state(async_client: AsyncClient) -> None:
    """Mismatched CSRF state is rejected with 400."""
    response = await async_client.get(
        "/api/v1/auth/github/callback",
        params={"code": "auth_code", "state": "bad_state"},
        cookies={"oauth_state": "different_state"},
        follow_redirects=False,
    )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_google_callback_existing_user_reuses_account(
    async_client: AsyncClient,
) -> None:
    """Signing in with Google twice reuses the same account (no duplicate users)."""
    login1 = await async_client.get("/api/v1/auth/google", follow_redirects=False)
    state1 = login1.cookies["oauth_state"]

    def _mock_client():
        token_response = MagicMock()
        token_response.raise_for_status.return_value = None
        token_response.json.return_value = {"access_token": "google_at"}
        userinfo_response = MagicMock()
        userinfo_response.raise_for_status.return_value = None
        userinfo_response.json.return_value = {"email": "returning@example.com"}
        mock = AsyncMock()
        mock.__aenter__.return_value = mock
        mock.__aexit__.return_value = None
        mock.post.return_value = token_response
        mock.get.return_value = userinfo_response
        return mock

    with patch("app.api.v1.auth.httpx.AsyncClient", return_value=_mock_client()):
        resp1 = await async_client.get(
            "/api/v1/auth/google/callback",
            params={"code": "code1", "state": state1},
            cookies={"oauth_state": state1},
            follow_redirects=False,
        )
    assert resp1.status_code == 302
    token1 = resp1.headers["location"].split("token=")[1]

    login2 = await async_client.get("/api/v1/auth/google", follow_redirects=False)
    state2 = login2.cookies["oauth_state"]

    with patch("app.api.v1.auth.httpx.AsyncClient", return_value=_mock_client()):
        resp2 = await async_client.get(
            "/api/v1/auth/google/callback",
            params={"code": "code2", "state": state2},
            cookies={"oauth_state": state2},
            follow_redirects=False,
        )
    assert resp2.status_code == 302
    token2 = resp2.headers["location"].split("token=")[1]

    # Both tokens must decode to the same user ID
    from app.core import security

    assert security.verify_access_token(token1) == security.verify_access_token(token2)
