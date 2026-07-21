from __future__ import annotations

import asyncio
import unittest
from unittest.mock import AsyncMock, patch

import main as orchestrator
from sources import gavang


MATCH_URL = (
    "https://smorf.io/s8-live/2436/marielhamn-lahti-finveik/"
    "?s8_live_fixture_id=2436&"
    "s8_live_stream_key=marielhamn-lahti-finveik&"
    "s8_auto_sound=1"
)


class GavangAdapterTests(unittest.TestCase):
    def test_route_smorf_to_gavang(self):
        routed = orchestrator.route_urls([MATCH_URL])
        self.assertEqual(routed["gavang"], [MATCH_URL])
        self.assertEqual(routed["chuoichien"], [])
        self.assertEqual(routed["luongson"], [])

    def test_extract_fixture_id(self):
        self.assertEqual(gavang.match_id_from_url(MATCH_URL), "2436")

    def test_extract_stream_key_from_query(self):
        self.assertEqual(
            gavang.extract_gavang_stream_key(MATCH_URL),
            "marielhamn-lahti-finveik",
        )

    def test_extract_stream_key_from_path_fallback(self):
        value = "https://smorf.io/s8-live/999/team-a-vs-team-b/"
        self.assertEqual(gavang.extract_gavang_stream_key(value), "team-a-vs-team-b")

    def test_reject_unsafe_stream_key(self):
        value = (
            "https://smorf.io/s8-live/999/test/"
            "?s8_live_stream_key=../../secret"
        )
        # Query không an toàn bị bỏ; slug an toàn vẫn là fallback.
        self.assertEqual(gavang.extract_gavang_stream_key(value), "test")

    def test_derived_flv_candidate_has_required_headers(self):
        rows = gavang.derived_gavang_stream_candidates(MATCH_URL)
        self.assertEqual(len(rows), 1)
        self.assertEqual(
            rows[0]["url"],
            "https://flv.lauthaitv.cc/live/marielhamn-lahti-finveik.flv",
        )
        self.assertEqual(rows[0]["referer"], MATCH_URL)
        self.assertEqual(rows[0]["origin"], "https://smorf.io")
        self.assertEqual(rows[0]["source"], "derived/s8_live_stream_key")

    def test_playlist_headers_keep_origin(self):
        header = gavang.header_json("UA", MATCH_URL, "https://smorf.io")
        self.assertIn('"Origin":"https://smorf.io"', header)
        pipe = gavang.android_stream_url(
            "https://flv.lauthaitv.cc/live/test.flv",
            "UA",
            MATCH_URL,
            "https://smorf.io",
        )
        self.assertIn("Origin=https://smorf.io", pipe)
        self.assertIn("Referer=https://smorf.io/s8-live/2436/", pipe)


class _NoPageContext:
    async def new_page(self):
        raise AssertionError("Không được mở tab Chromium khi FLV dựng đã xác minh")


class GavangFastPathTests(unittest.IsolatedAsyncioTestCase):
    async def test_verified_derived_flv_skips_browser(self):
        match = {
            "url": MATCH_URL,
            "raw_title": "Marielhamn vs Lahti",
            "raw_time": "",
            "minutes_to_kickoff": 0,
            "sport_group": "Bóng đá",
        }
        observed = {}

        async def fake_finalize(_context, stream_map, _match, **_kwargs):
            observed.update(stream_map)
            entry = next(iter(stream_map.values())).copy()
            entry["playability"] = "verified"
            return [entry], []

        with patch.object(gavang, "discover_http_candidates", new=AsyncMock(return_value=0)), \
             patch.object(gavang, "finalize_stream_map", new=fake_finalize):
            result = await gavang.fetch_stream(
                _NoPageContext(), match, asyncio.Semaphore(1)
            )

        self.assertEqual(result.get("scan_decision"), "http-first-complete")
        self.assertEqual(len(result.get("streams") or []), 1)
        entry = next(iter(observed.values()))
        self.assertEqual(entry["referer"], MATCH_URL)
        self.assertEqual(entry["origin"], "https://smorf.io")
        self.assertIn("derived/s8_live_stream_key", entry["sources"])


if __name__ == "__main__":
    unittest.main()
