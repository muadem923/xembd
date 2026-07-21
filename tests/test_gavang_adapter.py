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

DALIAN_URL = (
    "https://smorf.io/s8-live/2448/dalian-beijing-chnfa/"
    "?s8_live_fixture_id=2448&"
    "s8_live_stream_key=dalian-beijing-chnfa&"
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

    def test_unknown_time_stream_key_is_kept_for_direct_probe(self):
        rows = [{
            "url": DALIAN_URL,
            "raw_title": "Dalian Kewei vs Beijing Guoan",
            "raw_time": "",
            "card_text": "Dalian Kewei vs Beijing Guoan",
        }]
        kept, stats = gavang.filter_links_by_scan_window(rows)
        self.assertEqual(len(kept), 1)
        self.assertEqual(kept[0]["scan_window_reason"], "unknown-time-derived-probe")
        self.assertTrue(kept[0]["derived_probe_only"])
        self.assertEqual(stats["unknown_key_probe"], 1)
        self.assertEqual(stats["unknown"], 0)

    def test_unknown_time_without_stream_key_is_still_rejected(self):
        rows = [{
            "url": "https://smorf.io/news/not-a-fixture/",
            "raw_title": "A vs B",
            "raw_time": "",
            "card_text": "A vs B",
        }]
        kept, stats = gavang.filter_links_by_scan_window(rows)
        self.assertEqual(kept, [])
        self.assertEqual(stats["unknown"], 1)

    def test_flv_http_headers_survive_streaming_body_timeout(self):
        class FakeHeaders(dict):
            def items(self):
                return super().items()

        class FakeResponse:
            status = 200
            headers = FakeHeaders({
                "Content-Type": "video/x-flv",
                "X-Has-Token": "123",
            })
            def __enter__(self):
                return self
            def __exit__(self, *_args):
                return False
            def getcode(self):
                return 200
            def geturl(self):
                return "https://flv.lauthaitv.cc/live/dalian-beijing-chnfa.flv"
            def read1(self, _size):
                raise TimeoutError("live body keeps streaming")

        with patch.object(gavang.urllib.request, "urlopen", side_effect=lambda *_a, **_k: FakeResponse()):
            result = gavang.probe_stream_sync(
                "https://flv.lauthaitv.cc/live/dalian-beijing-chnfa.flv",
                gavang.UA,
                DALIAN_URL,
                "https://smorf.io",
                timeout=3,
            )
        self.assertTrue(result["playable"])
        self.assertEqual(result["status"], 200)
        self.assertEqual(result["content_type"], "video/x-flv")
        self.assertIn("live chunked", result["detail"])

    def test_shared_player_url_is_removed_across_distinct_fixtures(self):
        shared = "https://live-bong.s3.ap-southeast-1.amazonaws.com/player/master.m3u8"
        unique = "https://flv.lauthaitv.cc/live/dalian-beijing-chnfa.flv"
        rows = [
            {"url": DALIAN_URL, "streams": [{"url": shared}, {"url": unique}]},
            {"url": MATCH_URL, "streams": [{"url": shared}]},
        ]
        removed = gavang.remove_cross_match_shared_streams(rows)
        self.assertEqual(removed, 2)
        self.assertEqual([item["url"] for item in rows[0]["streams"]], [unique])
        self.assertEqual(rows[1]["streams"], [])
        self.assertIn("nhiều fixture", rows[1]["rejected_streams"][0]["reject_reason"])

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


class _ProbeContext(_NoPageContext):
    async def cookies(self, _urls):
        return []


class GavangFastPathTests(unittest.IsolatedAsyncioTestCase):
    async def test_dalian_fixture_real_probe_path_keeps_flv(self):
        match = {
            "url": DALIAN_URL,
            "raw_title": "Dalian Kewei vs Beijing Guoan",
            "raw_time": "",
            "derived_probe_only": True,
            "scan_window_reason": "unknown-time-derived-probe",
            "sport_group": "Bóng đá",
        }

        class FakeHeaders(dict):
            def items(self):
                return super().items()

        class FakeResponse:
            status = 200
            headers = FakeHeaders({"Content-Type": "video/x-flv", "X-Has-Token": "2136995574"})
            def __enter__(self): return self
            def __exit__(self, *_args): return False
            def getcode(self): return 200
            def geturl(self): return "https://flv.lauthaitv.cc/live/dalian-beijing-chnfa.flv"
            def read1(self, _size): raise TimeoutError("live stream")

        discover = AsyncMock(return_value=0)
        with patch.object(gavang.urllib.request, "urlopen", side_effect=lambda *_a, **_k: FakeResponse()), \
             patch.object(gavang, "discover_http_candidates", new=discover):
            gavang.PROBE_CACHE.clear()
            result = await gavang.fetch_stream(_ProbeContext(), match, asyncio.Semaphore(1))

        discover.assert_not_awaited()
        self.assertEqual(result.get("scan_decision"), "derived-flv-fast-path")
        self.assertEqual(
            result["streams"][0]["url"],
            "https://flv.lauthaitv.cc/live/dalian-beijing-chnfa.flv",
        )
        self.assertEqual(result["streams"][0]["probe"]["status"], 200)

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

        discover = AsyncMock(return_value=0)
        with patch.object(gavang, "discover_http_candidates", new=discover), \
             patch.object(gavang, "finalize_stream_map", new=fake_finalize):
            result = await gavang.fetch_stream(
                _NoPageContext(), match, asyncio.Semaphore(1)
            )

        discover.assert_not_awaited()
        self.assertEqual(result.get("scan_decision"), "derived-flv-fast-path")
        self.assertEqual(len(result.get("streams") or []), 1)
        entry = next(iter(observed.values()))
        self.assertEqual(entry["referer"], MATCH_URL)
        self.assertEqual(entry["origin"], "https://smorf.io")
        self.assertIn("derived/s8_live_stream_key", entry["sources"])

    async def test_unknown_time_probe_miss_does_not_open_page_or_player(self):
        match = {
            "url": DALIAN_URL,
            "raw_title": "Dalian Kewei vs Beijing Guoan",
            "raw_time": "",
            "derived_probe_only": True,
            "scan_window_reason": "unknown-time-derived-probe",
            "sport_group": "Bóng đá",
        }
        discover = AsyncMock(return_value=99)

        async def fake_finalize(_context, _stream_map, _match, **_kwargs):
            return [], [{"url": "https://flv.lauthaitv.cc/live/dalian-beijing-chnfa.flv"}]

        with patch.object(gavang, "discover_http_candidates", new=discover), \
             patch.object(gavang, "finalize_stream_map", new=fake_finalize):
            result = await gavang.fetch_stream(
                _NoPageContext(), match, asyncio.Semaphore(1)
            )

        discover.assert_not_awaited()
        self.assertEqual(result.get("scan_decision"), "derived-probe-only-miss")
        self.assertEqual(result.get("streams"), [])



if __name__ == "__main__":
    unittest.main()
