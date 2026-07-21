from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from merger import SourceFiles, cleanup_intermediate_playlists, merge_sources

TZ = ZoneInfo("Asia/Ho_Chi_Minh")


def write_playlist(path: Path, rows: list[dict[str, str]], pipe: bool = False) -> None:
    lines = ["#EXTM3U"]
    for row in rows:
        lines.extend([
            f'#EXTINF:-1 tvg-id="{row["id"]}" tvg-name="{row["name"]}" group-title="{row.get("group", "Bóng đá")}",{row["name"]}',
            "#EXTVLCOPT:http-referrer=https://example.test/",
            "#EXTVLCOPT:http-user-agent=UA",
            '#EXTHTTP:{"User-Agent":"UA","Referer":"https://example.test/"}',
            row["url"] + ("|User-Agent=UA&Referer=https://example.test/" if pipe else ""),
        ])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


class MergerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.now = datetime(2026, 7, 20, 7, 0, tzinfo=TZ)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def make_source(self, key: str, label: str, rows: list[dict[str, str]], debug_rows: list[dict]) -> SourceFiles:
        universal = self.root / f"{key}.m3u"
        pipe = self.root / f"{key}_pipe.m3u"
        vlc = self.root / f"{key}_vlc.m3u"
        debug = self.root / f"{key}.json"
        write_playlist(universal, rows)
        write_playlist(pipe, rows, pipe=True)
        write_playlist(vlc, rows)
        debug.write_text(json.dumps(debug_rows, ensure_ascii=False), encoding="utf-8")
        return SourceFiles(key, label, universal, pipe, vlc, debug)

    def test_dedupe_and_quality_cap(self) -> None:
        match_name = "USA vs Poland - Nations League"
        rows_a = [
            {"id": "cc-1", "name": f"[08:00 20/07] {match_name} [BLV A] [FHD M3U8]", "url": "https://cdn/xhd/playlist.m3u8"},
            {"id": "cc-2", "name": f"[08:00 20/07] {match_name} [BLV A] [FHD FLV]", "url": "https://cdn/xhd.flv"},
            {"id": "cc-3", "name": f"[08:00 20/07] {match_name} [BLV A] [HD M3U8]", "url": "https://cdn/x/playlist.m3u8"},
        ]
        debug_a = [{
            "match_name": match_name, "date": "20/07/2026", "time": "08:00", "blv": "A",
            "streams": [
                {"url": "https://cdn/xhd/playlist.m3u8", "quality": "FHD", "playability": "verified", "http_status": 200},
                {"url": "https://cdn/xhd.flv", "quality": "FHD", "playability": "verified", "http_status": 200},
                {"url": "https://cdn/x/playlist.m3u8", "quality": "HD", "playability": "verified", "http_status": 200},
            ],
        }]
        rows_b = [{"id": "ls-1", "name": f"[20/07/2026 08:00] {match_name} [BLV A] [FHD M3U8]", "url": "https://cdn/xhd/playlist.m3u8"}]
        debug_b = [{"match_name": match_name, "date": "20/07/2026", "time": "08:00", "blv": "A", "streams": [{"url": "https://cdn/xhd/playlist.m3u8", "quality": "FHD", "playability": "verified"}]}]
        report = merge_sources(self.root, [self.make_source("cc", "CC", rows_a, debug_a), self.make_source("ls", "LS", rows_b, debug_b)], now=self.now, max_per_match=2, preserve_on_empty=False)
        self.assertEqual(report["selected_count"], 2)
        content = (self.root / "all_live.m3u").read_text(encoding="utf-8")
        self.assertEqual(content.count("https://cdn/xhd/playlist.m3u8"), 1)
        self.assertIn("https://cdn/x/playlist.m3u8", content)
        self.assertNotIn("https://cdn/xhd.flv", content)
        self.assertNotIn("|User-Agent=", content)
        self.assertFalse((self.root / "all_live_pipe.m3u").exists())
        self.assertFalse((self.root / "all_live_vlc.m3u").exists())
        self.assertIn('group-title="CC"', content)
        self.assertNotIn('group-title="Bóng đá"', content)

    def test_upcoming_four_hours_only(self) -> None:
        rows = [
            {"id": "a", "name": "Soon vs Team [FHD M3U8]", "url": "https://cdn/soon/playlist.m3u8"},
            {"id": "b", "name": "Far vs Team [FHD M3U8]", "url": "https://cdn/far/playlist.m3u8"},
        ]
        soon = self.now + timedelta(hours=4)
        far = self.now + timedelta(hours=4, minutes=1)
        debug = [
            {"match_name": "Soon vs Team", "kickoff_iso": soon.isoformat(), "streams": [{"url": "https://cdn/soon/playlist.m3u8", "quality": "FHD", "playability": "upcoming-pending"}]},
            {"match_name": "Far vs Team", "kickoff_iso": far.isoformat(), "streams": [{"url": "https://cdn/far/playlist.m3u8", "quality": "FHD", "playability": "upcoming-pending"}]},
        ]
        report = merge_sources(self.root, [self.make_source("cc", "CC", rows, debug)], now=self.now, max_per_match=2, upcoming_hours=4, preserve_on_empty=False)
        self.assertEqual(report["selected_count"], 1)
        content = (self.root / "all_live.m3u").read_text(encoding="utf-8")
        self.assertIn("/soon/", content)
        self.assertNotIn("/far/", content)


    def test_gavang_unknown_time_derived_pending_is_kept(self) -> None:
        url = "https://flv.lauthaitv.cc/live/queensland-perth-ausffa.flv"
        rows = [{"id": "gavang-2449", "name": "[CHỜ PHÁT] Queensland VS Perth [FLV]", "url": url, "group": "Bóng đá"}]
        debug = [{
            "url": "https://smorf.io/s8-live/2449/queensland-perth-ausffa/",
            "match_name": "Queensland VS Perth",
            "scan_window_reason": "unknown-time-derived-probe",
            "streams": [{
                "url": url,
                "playability": "upcoming-pending",
                "derived_pending": True,
                "pending_reason": "current-home-stream-key-no-time",
            }],
        }]
        report = merge_sources(
            self.root,
            [self.make_source("gavang", "Gà Vàng", rows, debug)],
            now=self.now,
            preserve_on_empty=False,
        )
        content = (self.root / "all_live.m3u").read_text(encoding="utf-8")
        self.assertEqual(report["selected_count"], 1)
        self.assertIn(url, content)
        self.assertIn("[CHỜ PHÁT] Queensland VS Perth [FLV]", content)

    def test_gavang_pending_started_within_150_minutes_is_kept(self) -> None:
        url = "https://flv.lauthaitv.cc/live/a-b-league.flv"
        kickoff = self.now - timedelta(minutes=149)
        rows = [{"id": "gv", "name": "[CHỜ PHÁT] A VS B [FLV]", "url": url, "group": "Bóng đá"}]
        debug = [{
            "match_name": "A VS B",
            "kickoff_iso": kickoff.isoformat(),
            "streams": [{"url": url, "playability": "upcoming-pending", "derived_pending": True}],
        }]
        report = merge_sources(
            self.root, [self.make_source("gavang", "Gà Vàng", rows, debug)],
            now=self.now, preserve_on_empty=False,
        )
        self.assertEqual(report["selected_count"], 1)

    def test_gavang_pending_older_than_150_minutes_is_removed(self) -> None:
        url = "https://flv.lauthaitv.cc/live/a-b-league.flv"
        kickoff = self.now - timedelta(minutes=151)
        rows = [{"id": "gv", "name": "[CHỜ PHÁT] A VS B [FLV]", "url": url, "group": "Bóng đá"}]
        debug = [{
            "match_name": "A VS B",
            "kickoff_iso": kickoff.isoformat(),
            "streams": [{"url": url, "playability": "upcoming-pending", "derived_pending": True}],
        }]
        report = merge_sources(
            self.root, [self.make_source("gavang", "Gà Vàng", rows, debug)],
            now=self.now, preserve_on_empty=False,
        )
        self.assertEqual(report["selected_count"], 0)


    def test_gavang_fuzzy_key_match_enriches_buncheon_from_bucheon(self) -> None:
        url = "https://flv.lauthaitv.cc/live/buncheon-anyang-kork1.flv"
        gavang_rows = [{"id": "gv", "name": "[CHỜ PHÁT] Buncheon VS Anyang [FLV]", "url": url, "group": "Bóng đá"}]
        gavang_debug = [{
            "match_name": "Buncheon VS Anyang",
            "date": "22/07",
            "streams": [{"url": url, "playability": "upcoming-pending", "derived_pending": True}],
        }]
        kickoff = self.now + timedelta(hours=2)
        ref_url = "https://cdn.example/bucheon-anyang.m3u8"
        ref_rows = [{"id": "ls", "name": "Bucheon FC 1995 VS FC Anyang [FHD M3U8]", "url": ref_url, "group": "Bóng đá"}]
        ref_debug = [{
            "match_name": "Bucheon FC 1995 VS FC Anyang",
            "kickoff_iso": kickoff.isoformat(),
            "streams": [{"url": ref_url, "playability": "verified", "quality": "FHD"}],
        }]
        report = merge_sources(
            self.root,
            [
                self.make_source("gavang", "Gà Vàng", gavang_rows, gavang_debug),
                self.make_source("luongson", "Lương Sơn", ref_rows, ref_debug),
            ],
            now=self.now,
            preserve_on_empty=False,
        )
        content = (self.root / "all_live.m3u").read_text(encoding="utf-8")
        self.assertIn("[CHỜ PHÁT]", content)
        self.assertIn(kickoff.strftime("%H:%M %d/%m"), content)
        self.assertEqual(report["gavang_metadata"]["enriched"], 1)

    def test_previous_fallback_is_rejected(self) -> None:
        rows = [{"id": "a", "name": "Dead vs Link [FLV]", "url": "https://cdn/dead.flv"}]
        debug = [{"match_name": "Dead vs Link", "streams": [{"url": "https://cdn/dead.flv", "playability": "previous-fallback"}]}]
        report = merge_sources(self.root, [self.make_source("cc", "CC", rows, debug)], now=self.now, preserve_on_empty=False)
        self.assertEqual(report["selected_count"], 0)
        self.assertEqual((self.root / "all_live.m3u").read_text(encoding="utf-8"), "#EXTM3U\n")

    def test_different_commentators_are_kept(self) -> None:
        rows = [
            {"id": "a", "name": "A vs B [BLV Một] [FHD M3U8]", "url": "https://cdn/one/playlist.m3u8"},
            {"id": "b", "name": "A vs B [BLV Hai] [FHD M3U8]", "url": "https://cdn/two/playlist.m3u8"},
        ]
        debug = [
            {"match_name": "A vs B", "blv": "Một", "streams": [{"url": "https://cdn/one/playlist.m3u8", "quality": "FHD", "playability": "verified"}]},
            {"match_name": "A vs B", "blv": "Hai", "streams": [{"url": "https://cdn/two/playlist.m3u8", "quality": "FHD", "playability": "verified"}]},
        ]
        report = merge_sources(self.root, [self.make_source("cc", "CC", rows, debug)], now=self.now, max_per_match=1, preserve_on_empty=False)
        self.assertEqual(report["selected_count"], 2)

    def test_all_live_groups_channels_by_source(self) -> None:
        cc_rows = [{"id": "cc", "name": "C vs D [FHD M3U8]", "url": "https://cdn/cc/playlist.m3u8", "group": "Bóng đá"}]
        ls_rows = [{"id": "ls", "name": "A vs B [FHD M3U8]", "url": "https://cdn/ls/playlist.m3u8", "group": "Bóng đá"}]
        gv_rows = [{"id": "gv", "name": "E vs F [FHD M3U8]", "url": "https://cdn/gv/playlist.m3u8", "group": "Bóng đá"}]
        cc_debug = [{"match_name": "C vs D", "streams": [{"url": "https://cdn/cc/playlist.m3u8", "quality": "FHD", "playability": "verified"}]}]
        ls_debug = [{"match_name": "A vs B", "streams": [{"url": "https://cdn/ls/playlist.m3u8", "quality": "FHD", "playability": "verified"}]}]
        gv_debug = [{"match_name": "E vs F", "streams": [{"url": "https://cdn/gv/playlist.m3u8", "quality": "FHD", "playability": "verified"}]}]
        report = merge_sources(
            self.root,
            [
                self.make_source("chuoichien", "Chuối Chiên", cc_rows, cc_debug),
                self.make_source("luongson", "Lương Sơn", ls_rows, ls_debug),
                self.make_source("gavang", "Gà Vàng", gv_rows, gv_debug),
            ],
            now=self.now,
            preserve_on_empty=False,
        )
        content = (self.root / "all_live.m3u").read_text(encoding="utf-8")
        self.assertEqual(content.count('group-title="Chuối Chiên"'), 1)
        self.assertEqual(content.count('group-title="Lương Sơn"'), 1)
        self.assertEqual(content.count('group-title="Gà Vàng"'), 1)
        self.assertLess(content.index('group-title="Chuối Chiên"'), content.index('group-title="Lương Sơn"'))
        self.assertLess(content.index('group-title="Lương Sơn"'), content.index('group-title="Gà Vàng"'))
        self.assertEqual({row["group"] for row in report["channels"]}, {"Chuối Chiên", "Lương Sơn", "Gà Vàng"})
        self.assertEqual({row["sport_group"] for row in report["channels"]}, {"Bóng đá"})

    def test_cleanup_leaves_only_all_live_m3u(self) -> None:
        (self.root / "all_live.m3u").write_text("#EXTM3U\n", encoding="utf-8")
        for name in ("chuoichien_live.m3u", "hygenie_live.m3u", "all_live_pipe.m3u", "all_live_vlc.m3u"):
            (self.root / name).write_text("#EXTM3U\n", encoding="utf-8")
        legacy = self.root / "gavang" / "gavang_live.m3u"
        legacy.parent.mkdir(parents=True)
        legacy.write_text("#EXTM3U\n", encoding="utf-8")
        removed = cleanup_intermediate_playlists(self.root)
        self.assertEqual(sorted(removed), sorted(["chuoichien_live.m3u", "hygenie_live.m3u", "all_live_pipe.m3u", "all_live_vlc.m3u", "gavang/gavang_live.m3u"]))
        self.assertEqual([path.relative_to(self.root).as_posix() for path in self.root.rglob("*.m3u")], ["all_live.m3u"])
        self.assertFalse((self.root / "gavang").exists())

    def test_gavang_metadata_is_soft_enriched_from_matching_source(self) -> None:
        gv_url = "https://flv.lauthaitv.cc/live/queensland-perth-ausffa.flv"
        gv_rows = [{"id": "gavang-2449", "name": "Queensland VS Perth [FLV]", "url": gv_url, "group": "Bóng đá"}]
        gv_debug = [{
            "url": "https://smorf.io/s8-live/2449/queensland-perth-ausffa/",
            "match_name": "Queensland VS Perth", "blv": "NGƯỜI CHÈ",
            "streams": [{"url": gv_url, "quality": "", "playability": "verified", "http_status": 200}],
        }]
        ls_url = "https://cdn.example/queensland/index.m3u8"
        ls_rows = [{"id": "ls-qld", "name": "[21/07/2026 16:30] QUEENSLAND LIONS SC vs PERTH GLORY [M3U8]", "url": ls_url, "group": "Bóng đá"}]
        ls_debug = [{
            "match_name": "QUEENSLAND LIONS SC vs PERTH GLORY",
            "date": "21/07/2026", "time": "16:30",
            "streams": [{"url": ls_url, "quality": "", "playability": "verified", "http_status": 200}],
        }]
        report = merge_sources(
            self.root,
            [
                self.make_source("luongson", "Lương Sơn", ls_rows, ls_debug),
                self.make_source("gavang", "Gà Vàng", gv_rows, gv_debug),
            ],
            now=datetime(2026, 7, 21, 15, 0, tzinfo=TZ),
            max_per_match=2, preserve_on_empty=False,
        )
        text = (self.root / "all_live.m3u").read_text(encoding="utf-8")
        self.assertIn(gv_url, text)
        self.assertIn('[16:30 21/07] QUEENSLAND LIONS SC vs PERTH GLORY [BLV NGƯỜI CHÈ] [FLV]', text)
        gv_channel = next(row for row in report["channels"] if row["source"] == "gavang")
        self.assertEqual(gv_channel["metadata_audit"], "enriched-soft")
        self.assertEqual(gv_channel["metadata_enriched_from"], "luongson")

    def test_gavang_metadata_mismatch_warns_but_keeps_verified_link(self) -> None:
        gv_url = "https://flv.lauthaitv.cc/live/unknown-alpha-beta.flv"
        gv_rows = [{"id": "gv", "name": "Unknown VS Alpha [FLV]", "url": gv_url, "group": "Bóng đá"}]
        gv_debug = [{
            "match_name": "Unknown VS Alpha",
            "streams": [{"url": gv_url, "playability": "verified", "http_status": 200}],
        }]
        report = merge_sources(
            self.root, [self.make_source("gavang", "Gà Vàng", gv_rows, gv_debug)],
            now=self.now, preserve_on_empty=False,
        )
        text = (self.root / "all_live.m3u").read_text(encoding="utf-8")
        self.assertIn(gv_url, text)
        self.assertEqual(report["selected_count"], 1)
        self.assertEqual(report["channels"][0]["metadata_audit"], "warn-only")


    def test_gavang_fallback_logo_is_replaced_by_matching_team_logo(self):
        from merger import M3UBlock, enrich_gavang_logos_from_other_sources
        gavang_block = M3UBlock(
            source_key="gavang", source_label="Gà Vàng",
            extinf='#EXTINF:-1 tvg-logo="https://smorf.io/favicon.ico",Queensland VS Perth [FLV]',
            lines=['#EXTINF:-1 tvg-logo="https://smorf.io/favicon.ico",Queensland VS Perth [FLV]', 'https://flv.lauthaitv.cc/live/queensland-perth-ausffa.flv'],
            url_line='https://flv.lauthaitv.cc/live/queensland-perth-ausffa.flv',
            canonical_url='https://flv.lauthaitv.cc/live/queensland-perth-ausffa.flv',
            attributes={"tvg-logo": "https://smorf.io/favicon.ico"},
            display_name="Queensland VS Perth [FLV]",
            metadata={"logo_is_fallback": True},
        )
        reference = M3UBlock(
            source_key="luongson", source_label="Lương Sơn",
            extinf='#EXTINF:-1 tvg-logo="https://cdn.example/queensland.png",QUEENSLAND LIONS SC vs PERTH GLORY [M3U8]',
            lines=['#EXTINF:-1 tvg-logo="https://cdn.example/queensland.png",QUEENSLAND LIONS SC vs PERTH GLORY [M3U8]', 'https://cdn.example/live.m3u8'],
            url_line='https://cdn.example/live.m3u8', canonical_url='https://cdn.example/live.m3u8',
            attributes={"tvg-logo": "https://cdn.example/queensland.png"},
            display_name="QUEENSLAND LIONS SC vs PERTH GLORY [M3U8]", metadata={},
        )
        stats = enrich_gavang_logos_from_other_sources([gavang_block, reference])
        self.assertEqual(gavang_block.attributes["tvg-logo"], "https://cdn.example/queensland.png")
        self.assertIn('tvg-logo="https://cdn.example/queensland.png"', gavang_block.extinf)
        self.assertEqual(stats["team_logo"], 1)


if __name__ == "__main__":
    unittest.main()
