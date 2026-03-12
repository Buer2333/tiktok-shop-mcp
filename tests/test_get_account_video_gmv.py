"""Tests for get_account_video_gmv in analytics tools."""

import pytest
from unittest.mock import AsyncMock

from tiktok_shop_mcp.tools.get_analytics import get_account_video_gmv


def _make_video(username: str, gmv: str = "10.00", orders: int = 1, items: int = 2):
    """Helper to create a video dict matching the API shape."""
    return {
        "username": username,
        "gmv": {"amount": gmv},
        "sku_orders": orders,
        "items_sold": items,
    }


def _make_response(videos, next_page_token=None):
    """Wrap videos list into the API response shape."""
    data = {"videos": videos}
    if next_page_token:
        data["next_page_token"] = next_page_token
    return {"data": data}


@pytest.mark.asyncio
async def test_single_page():
    """Normal case: single page of results, no pagination."""
    client = AsyncMock()
    client._make_request.return_value = _make_response([
        _make_video("alice", "25.50", orders=3, items=5),
        _make_video("bob", "10.00", orders=1, items=2),
        _make_video("alice", "4.50", orders=1, items=1),
    ])

    result = await get_account_video_gmv(client, "2026-03-01", "2026-03-02")

    assert result["total_videos_scanned"] == 3
    assert result["total_accounts"] == 2
    # Sorted by GMV desc: alice=30.0, bob=10.0
    assert result["accounts"][0]["username"] == "alice"
    assert result["accounts"][0]["gmv"] == 30.0
    assert result["accounts"][0]["orders"] == 4
    assert result["accounts"][0]["items_sold"] == 6
    assert result["accounts"][0]["videos"] == 2
    assert result["accounts"][1]["username"] == "bob"
    assert result["accounts"][1]["gmv"] == 10.0

    # Verify API was called once with correct params
    client._make_request.assert_called_once()
    call_args = client._make_request.call_args
    assert call_args[0] == ("GET", "analytics", "shop_videos/performance")
    assert call_args[1]["params"]["page_size"] == "50"
    assert call_args[1]["api_version"] == "202509"


@pytest.mark.asyncio
async def test_multi_page_pagination():
    """Pagination: two pages then stops when next_page_token is absent."""
    client = AsyncMock()
    client._make_request.side_effect = [
        _make_response(
            [_make_video("alice", "20.00")],
            next_page_token="cursor_page2",
        ),
        _make_response(
            [_make_video("alice", "5.00"), _make_video("bob", "15.00")],
            # No next_page_token -> stop
        ),
    ]

    result = await get_account_video_gmv(client, "2026-03-01", "2026-03-02")

    assert result["total_videos_scanned"] == 3
    assert result["total_accounts"] == 2
    assert client._make_request.call_count == 2

    # Second call should include page_token
    second_call_params = client._make_request.call_args_list[1][1]["params"]
    assert second_call_params["page_token"] == "cursor_page2"

    # First call should NOT include page_token
    first_call_params = client._make_request.call_args_list[0][1]["params"]
    assert "page_token" not in first_call_params


@pytest.mark.asyncio
async def test_username_filter_case_insensitive():
    """Username filtering is case-insensitive; non-matching videos still scanned."""
    client = AsyncMock()
    client._make_request.return_value = _make_response([
        _make_video("Alice", "20.00"),
        _make_video("BOB", "10.00"),
        _make_video("charlie", "30.00"),
    ])

    result = await get_account_video_gmv(
        client, "2026-03-01", "2026-03-02", usernames=["alice", "Bob"],
    )

    # All 3 videos scanned even though charlie is filtered out
    assert result["total_videos_scanned"] == 3
    assert result["total_accounts"] == 2
    usernames_in_result = [a["username"] for a in result["accounts"]]
    assert "Alice" in usernames_in_result
    assert "BOB" in usernames_in_result
    assert "charlie" not in usernames_in_result


@pytest.mark.asyncio
async def test_empty_results():
    """API returns no videos at all."""
    client = AsyncMock()
    client._make_request.return_value = _make_response([])

    result = await get_account_video_gmv(client, "2026-03-01", "2026-03-02")

    assert result["total_videos_scanned"] == 0
    assert result["total_accounts"] == 0
    assert result["accounts"] == []
    client._make_request.assert_called_once()


@pytest.mark.asyncio
async def test_empty_data_key():
    """API returns response with no 'data' key."""
    client = AsyncMock()
    client._make_request.return_value = {}

    result = await get_account_video_gmv(client, "2026-03-01", "2026-03-02")

    assert result["total_videos_scanned"] == 0
    assert result["total_accounts"] == 0
    assert result["accounts"] == []


@pytest.mark.asyncio
async def test_safety_limit_max_pages():
    """Pagination stops at max_pages (100) even if next_page_token keeps coming."""
    client = AsyncMock()
    # Every call returns a video + next_page_token, simulating infinite pagination
    client._make_request.return_value = _make_response(
        [_make_video("alice", "1.00")],
        next_page_token="always_more",
    )

    result = await get_account_video_gmv(client, "2026-03-01", "2026-03-02")

    # Should stop at exactly 100 pages
    assert client._make_request.call_count == 100
    assert result["total_videos_scanned"] == 100
    assert result["accounts"][0]["username"] == "alice"
    assert result["accounts"][0]["gmv"] == pytest.approx(100.0)


@pytest.mark.asyncio
async def test_currency_and_account_type_params():
    """Verify currency and account_type are passed through to API."""
    client = AsyncMock()
    client._make_request.return_value = _make_response([])

    await get_account_video_gmv(
        client, "2026-03-01", "2026-03-02",
        currency="LOCAL", account_type="AFFILIATE_ACCOUNTS",
    )

    params = client._make_request.call_args[1]["params"]
    assert params["currency"] == "LOCAL"
    assert params["account_type"] == "AFFILIATE_ACCOUNTS"


@pytest.mark.asyncio
async def test_missing_gmv_field():
    """Video with missing gmv field defaults to 0."""
    client = AsyncMock()
    client._make_request.return_value = _make_response([
        {"username": "alice", "sku_orders": 1, "items_sold": 1},  # no gmv key
    ])

    result = await get_account_video_gmv(client, "2026-03-01", "2026-03-02")

    assert result["accounts"][0]["gmv"] == 0.0
    assert result["accounts"][0]["videos"] == 1


@pytest.mark.asyncio
async def test_missing_username_defaults_to_unknown():
    """Video without username field is bucketed as 'unknown'."""
    client = AsyncMock()
    client._make_request.return_value = _make_response([
        {"gmv": {"amount": "5.00"}, "sku_orders": 1, "items_sold": 1},
    ])

    result = await get_account_video_gmv(client, "2026-03-01", "2026-03-02")

    assert result["accounts"][0]["username"] == "unknown"
    assert result["accounts"][0]["gmv"] == 5.0
