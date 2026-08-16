from __future__ import annotations

import json
import os
import stat
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path


NATIVE_UI_ROOT = Path(__file__).resolve().parents[1] / "native-ui"
sys.path.insert(0, str(NATIVE_UI_ROOT))

from pulsearc_tv import (  # noqa: E402
    import_sources_from_media,
    _build_xtream_epg_index,
    _decode_epg_text,
    _merge_xtream_channels,
    _match_epg_channel,
    _normalize_epg_channel,
    online_epg_feed_warning,
    _upgrade_cached_xtream_channel,
    load_saved_sources,
    parse_m3u,
    public_source_label,
    save_sources,
    xtream_group_visible,
    xtream_xmltv_url,
    xtream_playlist_url,
)


class TelevisionSourceTests(unittest.TestCase):
    def test_online_epg_matching_preserves_east_and_west_feeds(self) -> None:
        names = {"amc", "amc west", "mtv east", "mtv west"}
        self.assertEqual(_match_epg_channel({"name": "US: AMC HD", "tvg_id": "AMC.us"}, names), "amc")
        self.assertEqual(_match_epg_channel({"name": "MTV East HD"}, names), "mtv east")
        self.assertEqual(_match_epg_channel({"name": "MTV Pacific HD"}, names), "mtv west")

    def test_epg_channel_normalization_removes_quality_not_feed(self) -> None:
        self.assertEqual(_normalize_epg_channel("US: MTV - Music Television HD (Pacific)"), "mtv west")
        self.assertEqual(_normalize_epg_channel("AMC+ HD"), "amc plus")

    def test_known_mismatched_feed_gets_warning(self) -> None:
        self.assertEqual(
            online_epg_feed_warning({"name": "US: BBC AMERICA HD", "tvg_id": "BBCAmerica.us"}),
            "STREAM AND PUBLIC GUIDE DO NOT MATCH",
        )
        self.assertEqual(online_epg_feed_warning({"name": "AMC HD"}), "")

    def test_epg_text_accepts_base64_and_plain_text(self) -> None:
        self.assertEqual(_decode_epg_text("VGVzdCBTaG93"), "Test Show")
        self.assertEqual(_decode_epg_text("Plain title"), "Plain title")

    def test_old_xtream_cache_recovers_stream_id(self) -> None:
        upgraded = _upgrade_cached_xtream_channel({
            "url": "http://provider.test/live/user/password/12345.ts",
            "group": "LIVE / US| NEWS",
        })
        self.assertEqual(upgraded["stream_id"], "12345")
        self.assertEqual(upgraded["media_type"], "live")

    def test_partial_xtream_refresh_preserves_cached_vod(self) -> None:
        merged = _merge_xtream_channels(
            [{"url": "http://provider.test/movie/u/p/9.mp4", "group": "VOD / EN - MOVIES"}],
            [{"url": "http://provider.test/live/u/p/1.ts", "group": "LIVE / US| NEWS"}],
        )
        self.assertEqual({item["media_type"] for item in merged}, {"live", "movie"})

    def test_parse_m3u_preserves_group_logo_and_stream(self) -> None:
        channels = parse_m3u(
            '#EXTM3U\n#EXTINF:-1 tvg-id="demo.us" tvg-logo="https://img.test/logo.png" '
            'group-title="Movies",Demo Movies\nhttps://stream.test/demo.m3u8\n',
            "Demo",
        )
        self.assertEqual(len(channels), 1)
        self.assertEqual(channels[0]["name"], "Demo Movies")
        self.assertEqual(channels[0]["group"], "MOVIES")
        self.assertEqual(channels[0]["source"], "Demo")
        self.assertEqual(channels[0]["url"], "https://stream.test/demo.m3u8")

    def test_parse_m3u_rejects_local_and_script_urls(self) -> None:
        playlist = "#EXTM3U\n#EXTINF:-1,Unsafe\nfile:///etc/passwd\n#EXTINF:-1,Script\njavascript:alert(1)\n"
        self.assertEqual(parse_m3u(playlist), [])

    def test_xtream_url_validates_and_encodes_credentials(self) -> None:
        url = xtream_playlist_url({
            "server": "http://provider.test",
            "port": 8080,
            "username": "user+one",
            "password": "pass&word",
            "type": "xtream",
        })
        self.assertEqual(
            url,
            "http://provider.test:8080/get.php?username=user%2Bone&password=pass%26word&type=m3u_plus&output=ts",
        )
        label = public_source_label({
            "name": "Private",
            "server": "http://provider.test",
            "username": "secret-user",
            "password": "secret-password",
            "type": "xtream",
        })
        self.assertNotIn("secret-user", label)
        self.assertNotIn("secret-password", label)
        self.assertIn("CREDENTIALS SAVED", label)

    def test_xtream_xmltv_url_uses_authenticated_endpoint(self) -> None:
        url = xtream_xmltv_url({
            "server": "http://provider.test/base",
            "username": "user+one",
            "password": "pass&word",
            "type": "xtream",
        })
        self.assertEqual(
            url,
            "http://provider.test/base/xmltv.php?username=user%2Bone&password=pass%26word",
        )

    def test_xtream_xmltv_index_supports_exact_id_and_display_name(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            xmltv = Path(temporary) / "guide.xml"
            start = (datetime.now(timezone.utc) + timedelta(minutes=10)).strftime("%Y%m%d%H%M%S +0000")
            stop = (datetime.now(timezone.utc) + timedelta(minutes=70)).strftime("%Y%m%d%H%M%S +0000")
            xmltv.write_text(
                '<?xml version="1.0"?><tv>'
                '<channel id="AMC.us"><display-name>AMC East HD</display-name></channel>'
                f'<programme channel="AMC.us" start="{start}" stop="{stop}">'
                '<title>Future Show</title><desc>Episode description.</desc></programme>'
                '</tv>',
                encoding="utf-8",
            )
            index = _build_xtream_epg_index(xmltv)
            self.assertIn("id:amc.us", index)
            self.assertIn("amc east", index)
            self.assertEqual(index["id:amc.us"][0]["title"], "Future Show")

    def test_saved_credentials_are_owner_readable_only(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "sources.json"
            save_sources(path, [{"name": "Private", "type": "m3u", "url": "https://example.test/list.m3u"}])
            if os.name != "nt":
                self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            self.assertEqual(load_saved_sources(path)[0]["name"], "Private")

    def test_usb_import_accepts_xtream_json_and_local_playlist(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            tv = root / "USB" / "PulseArc" / "TV"
            tv.mkdir(parents=True)
            (tv / "sources.json").write_text(json.dumps({"sources": [{
                "name": "Private Provider",
                "type": "xtream",
                "server": "http://provider.test",
                "port": 8000,
                "username": "demo",
                "password": "secret",
            }]}), encoding="utf-8")
            (tv / "local.m3u").write_text("#EXTM3U\n#EXTINF:-1,Local\nhttps://example.test/live.m3u8\n", encoding="utf-8")
            destination = root / "state" / "sources.json"
            sources, _count = import_sources_from_media(root, destination)
            self.assertEqual({source["type"] for source in sources}, {"xtream", "local"})
            if os.name != "nt":
                self.assertEqual(stat.S_IMODE(destination.stat().st_mode), 0o600)

    def test_xtream_country_filter_keeps_us_english_and_untagged_vod(self) -> None:
        self.assertTrue(xtream_group_visible("LIVE / US| NEWS"))
        self.assertTrue(xtream_group_visible("VOD / EN - NEW RELEASE"))
        self.assertTrue(xtream_group_visible("VOD / AMAZON MOVIES"))
        self.assertTrue(xtream_group_visible("LIVE / 4K| RELAX"))
        self.assertFalse(xtream_group_visible("LIVE / CA| CANADA"))
        self.assertFalse(xtream_group_visible("LIVE / UK| GENERAL"))
        self.assertFalse(xtream_group_visible("VOD / DE - FILME"))
        self.assertFalse(xtream_group_visible("VOD / NORDIC FILM"))
        self.assertFalse(xtream_group_visible("LIVE / FOR ADULTS"))
        self.assertFalse(xtream_group_visible("VOD / FOR ADULTS"))


if __name__ == "__main__":
    unittest.main()
