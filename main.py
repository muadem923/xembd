import asyncio
import hashlib
import html
import json
import os
import re
import sys
import time
import unicodedata
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, quote, unquote, urljoin, urlparse
from zoneinfo import ZoneInfo

from playwright.async_api import BrowserContext, Page, Route, async_playwright


# =========================
# CẤU HÌNH
# =========================
TARGET_URL = "https://live03.chuoichientv.me/"
PLAYER_ORIGIN_FALLBACK = "https://live.chuoichien.tv"
OUTPUT_M3U = "chuoichien_live.m3u"
OUTPUT_PIPE_M3U = "chuoichien_live_pipe.m3u"
OUTPUT_VLC_M3U = "chuoichien_live_vlc.m3u"
OUTPUT_DEBUG = "chuoichien_debug.json"
OUTPUT_HOME_DEBUG_HTML = "chuoichien_home_debug.html"
OUTPUT_HOME_DEBUG_PNG = "chuoichien_home_debug.png"
SCANNER_VERSION = "3.5.1-LOGO-BLV-MULTI-QUALITY-AUDIT"


def read_env_bool(name: str, default: bool = True) -> bool:
    raw = os.getenv(name, "").strip().lower()
    if not raw:
        return default
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    print(f"⚠️ {name}={raw!r} không hợp lệ; dùng mặc định {default}.")
    return default


def read_env_int(name: str, default: int, minimum: int, maximum: int) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        print(f"⚠️ {name}={raw!r} không hợp lệ; dùng mặc định {default}.")
        return default
    return max(minimum, min(value, maximum))


CONCURRENCY_LIMIT = read_env_int(
    "SOCOLIVE_MATCH_CONCURRENCY", 4, minimum=1, maximum=12
)
HOME_WAIT_MS = read_env_int(
    "SOCOLIVE_HOME_WAIT_MS", 6000, minimum=1000, maximum=30000
)
STREAM_WAIT_SECONDS = read_env_int(
    "SOCOLIVE_ROOM_WAIT_SECONDS", 20, minimum=5, maximum=120
)
EXTRA_WAIT_AFTER_FIRST_STREAM = 5.0
FULL_SCAN = read_env_bool("SOCOLIVE_FULL_SCAN", True)
HEADLESS = True

# Dùng đúng User-Agent đã được kiểm chứng phát được bằng VLC.
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)

STREAM_EXTENSIONS = (".m3u8", ".flv")
AD_MARKERS = (
    "doubleclick.",
    "googleads.",
    "/ads/",
    "/advert",
    "imasdk",
)

PLAY_SELECTORS = (
    ".vjs-big-play-button",
    ".plyr__control--overlaid",
    ".jw-icon-display",
    ".jw-display-icon-container",
    ".play-button",
    ".btn-play",
    "button[aria-label*='Play' i]",
    "button[title*='Play' i]",
    "[class*='play'][role='button']",
)

TIME_RE = re.compile(r"(?<!\d)([01]?\d|2[0-3])[:h.]([0-5]\d)(?!\d)", re.I)

BLV_ALIASES = {
    "angao": "A Ngáo",
}

QUALITY_TEXT_RE = re.compile(
    r"(?i)\b(4k|uhd|2160p?|full\s*hd|fhd|1080p?|hd|720p?|sd|480p?|auto)\b"
)


SPORT_GROUP_ORDER = (
    "Bóng đá",
    "Bóng rổ",
    "Bóng chuyền",
    "Tennis",
    "Esports",
    "Khác",
)
SPORT_GROUP_RANK = {name: index for index, name in enumerate(SPORT_GROUP_ORDER)}
SPORT_KEYWORDS: dict[str, tuple[tuple[str, int], ...]] = {
    "Esports": (
        ("esports", 12), ("e sports", 12), ("esport", 12),
        ("counter strike", 9), ("cs2", 9), ("csgo", 9),
        ("dota", 9), ("league of legends", 9), ("valorant", 9),
        ("pubg", 8), ("mobile legends", 8), ("lien quan", 8),
        ("efootball", 8), ("fifa online", 8), ("arena of valor", 8),
    ),
    "Tennis": (
        ("tennis", 12), ("quan vot", 12), ("atp", 8), ("wta", 8),
        ("challenger", 7), ("wimbledon", 8), ("roland garros", 8),
        ("australian open", 8), ("us open", 7), ("davis cup", 7),
    ),
    "Bóng rổ": (
        ("bong ro", 12), ("basketball", 12), ("nba", 9), ("wnba", 9),
        ("euroleague", 8), ("fiba", 8), ("ncaa", 7), ("vba", 7),
        ("cba", 6), ("basket", 6),
    ),
    "Bóng chuyền": (
        ("bong chuyen", 12), ("volleyball", 12), ("fivb", 9),
        ("volleyball nations league", 10), ("nations league women", 8),
        ("nations league men", 8), ("vnl", 8), ("pvl", 7),
        ("cev", 5),
    ),
    "Bóng đá": (
        ("bong da", 12), ("football", 11), ("soccer", 11),
        ("futsal", 10), ("premier league", 8), ("champions league", 8),
        ("europa league", 8), ("conference league", 8),
        ("world cup", 7), ("asian cup", 7), ("copa", 6),
        ("uefa", 6), ("afc", 5), ("fc ", 4), (" fc", 4),
    ),
    "Khác": (
        ("cau long", 12), ("badminton", 12), ("bong ban", 12),
        ("table tennis", 12), ("baseball", 10), ("ice hockey", 10),
        ("hockey", 8), ("handball", 9), ("boxing", 9), ("mma", 9),
        ("motogp", 9), ("formula 1", 9), ("f1 racing", 9),
    ),
}


def normalize_search_text(value: str) -> str:
    text = unicodedata.normalize("NFKD", clean_text(value).lower())
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return f" {clean_text(text)} "


def classify_sport(*values: str, default: str = "Bóng đá") -> str:
    """Phân loại theo tín hiệu gần card/trang trận; tín hiệu đầu tiên có độ tin cậy cao thắng."""
    for value in values:
        normalized = normalize_search_text(value)
        if not normalized.strip():
            continue
        scores: dict[str, int] = {}
        for group, keywords in SPORT_KEYWORDS.items():
            score = 0
            for keyword, weight in keywords:
                token = f" {keyword.strip()} "
                if token in normalized or (len(keyword.strip()) >= 6 and keyword.strip() in normalized):
                    score += weight
            if score:
                scores[group] = score
        if not scores:
            continue
        ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
        if len(ranked) == 1 or ranked[0][1] > ranked[1][1]:
            return ranked[0][0]
    return default if default in SPORT_GROUP_RANK else "Khác"


def channel_id_for(result: dict[str, Any], stream_url: str, index: int) -> str:
    path_match = re.search(r"/live/(\d+)", result.get("url", ""))
    base = path_match.group(1) if path_match else hashlib.sha1(
        (result.get("url", "") + stream_url).encode("utf-8")
    ).hexdigest()[:12]
    return f"chuoichien-{base}-{index}"


def clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def _decode_javascript_escapes(value: str) -> str:
    text = value or ""
    text = re.sub(
        r"\\u([0-9a-fA-F]{4})",
        lambda match: chr(int(match.group(1), 16)),
        text,
    )
    text = re.sub(
        r"\\x([0-9a-fA-F]{2})",
        lambda match: chr(int(match.group(1), 16)),
        text,
    )
    return text.replace("\\/", "/")


def decode_url_repeatedly(value: str, rounds: int = 5) -> str:
    current = html.unescape(value or "").strip()
    for _ in range(rounds):
        decoded = html.unescape(_decode_javascript_escapes(current))
        decoded = unquote(decoded)
        if decoded == current:
            current = decoded
            break
        current = decoded
    return current.strip()


def normalize_blv_name(value: str) -> str:
    raw = clean_text(decode_url_repeatedly(value))
    raw = re.sub(r"(?i)^\s*(?:blv|bình\s*luận\s*viên)\s*[:\-–—]?\s*", "", raw)
    raw = raw.strip(" -|•[]()")
    if not raw or len(raw) > 60 or re.search(r"(?i)\bvs\b", raw):
        return ""

    key = normalize_search_text(raw).strip().replace(" ", "")
    if key in BLV_ALIASES:
        return BLV_ALIASES[key]

    if re.fullmatch(r"[a-zA-Z0-9_.-]+", raw):
        words = re.sub(r"[_\-.]+", " ", raw).split()
        return " ".join(word.capitalize() for word in words)
    return raw


def extract_blv_from_url(value: str) -> str:
    try:
        query = parse_qs(urlparse(decode_url_repeatedly(value)).query)
    except Exception:
        return ""
    for key in ("blvName", "blv_name", "commentator", "commentatorName", "blv"):
        values = query.get(key) or query.get(key.lower())
        if values:
            name = normalize_blv_name(values[0])
            if name:
                return name
    return ""


def normalize_quality_hint(value: str) -> str:
    text = clean_text(decode_url_repeatedly(value))
    if not text:
        return ""
    match = QUALITY_TEXT_RE.search(text)
    if not match:
        return ""
    token = match.group(1).lower().replace(" ", "")
    if token in {"4k", "uhd", "2160", "2160p"}:
        return "4K"
    if token in {"fullhd", "fhd", "1080", "1080p"}:
        return "FHD"
    if token in {"hd", "720", "720p"}:
        return "HD"
    if token in {"sd", "480", "480p"}:
        return "SD"
    if token == "auto":
        return "AUTO"
    return token.upper()


def parse_hls_variants(text: str, base_url: str) -> list[dict[str, str]]:
    if "#EXTM3U" not in (text or "") or "#EXT-X-STREAM-INF" not in text:
        return []
    lines = [line.strip() for line in text.splitlines()]
    variants: list[dict[str, str]] = []
    pending = ""
    for line in lines:
        if line.startswith("#EXT-X-STREAM-INF:"):
            pending = line.partition(":")[2]
            continue
        if not pending or not line or line.startswith("#"):
            continue
        quality = normalize_quality_hint(pending)
        resolution = re.search(r"RESOLUTION=\d+x(\d+)", pending, re.I)
        if resolution:
            height = int(resolution.group(1))
            quality = "4K" if height >= 1800 else "FHD" if height >= 1000 else "HD" if height >= 700 else "SD"
        variants.append({
            "url": urljoin(base_url, line),
            "quality": quality,
            "parent_url": base_url,
        })
        pending = ""
    return variants


def absolute_url(value: str, base: str = TARGET_URL) -> str:
    value = decode_url_repeatedly(value)
    if not value or value.startswith(("data:", "blob:", "javascript:")):
        return ""
    try:
        return urljoin(base, value)
    except Exception:
        return value


def origin_from_url(value: str) -> str:
    try:
        parsed = urlparse(value)
        if parsed.scheme and parsed.netloc:
            return f"{parsed.scheme}://{parsed.netloc}"
    except Exception:
        pass
    return ""


def extract_time(value: str) -> str:
    text = clean_text(value)

    # JSON/JSON-LD thường trả ISO UTC. Chuyển đúng sang giờ Việt Nam trước.
    iso_match = re.search(
        r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:?\d{2})?",
        text,
    )
    if iso_match:
        try:
            iso_value = iso_match.group(0).replace("Z", "+00:00")
            parsed = datetime.fromisoformat(iso_value)
            if parsed.tzinfo is not None:
                parsed = parsed.astimezone(ZoneInfo("Asia/Ho_Chi_Minh"))
            return parsed.strftime("%H:%M")
        except Exception:
            pass

    match = TIME_RE.search(text)
    if not match:
        return ""
    return f"{int(match.group(1)):02d}:{match.group(2)}"


def stream_kind(url: str, content_type: str = "") -> str:
    clean = decode_url_repeatedly(url)
    lower_path = urlparse(clean).path.lower()
    lower_type = (content_type or "").lower()

    if ".m3u8" in lower_path or any(marker in lower_type for marker in (
        "application/vnd.apple.mpegurl", "application/x-mpegurl",
        "audio/mpegurl", "audio/x-mpegurl",
    )):
        return "m3u8"
    if ".flv" in lower_path or any(marker in lower_type for marker in (
        "video/x-flv", "video/flv", "application/x-flv",
    )):
        return "flv"
    return ""


def is_direct_stream_url(url: str, content_type: str = "") -> bool:
    if not url:
        return False
    clean = decode_url_repeatedly(url)
    parsed = urlparse(clean)
    lower_url = clean.lower()
    if parsed.scheme not in {"http", "https"}:
        return False
    if not stream_kind(clean, content_type):
        return False
    return not any(marker in lower_url for marker in AD_MARKERS)


def extract_stream_urls(raw_url: str, content_type: str = "") -> list[str]:
    """Tách luồng trực tiếp, kể cả streamUrl đã percent-encode trong iframe embed."""
    if not raw_url:
        return []

    pending = [raw_url]
    seen_values: set[str] = set()
    found: list[str] = []
    nested_param_names = {
        "streamurl", "stream_url", "stream", "url", "src", "file",
        "source", "video", "hls", "flv", "playurl", "play_url",
    }

    while pending and len(seen_values) < 60:
        value = decode_url_repeatedly(pending.pop(0))
        if not value or value in seen_values:
            continue
        seen_values.add(value)

        direct_type = content_type if value == decode_url_repeatedly(raw_url) else ""
        if is_direct_stream_url(value, direct_type):
            if value not in found:
                found.append(value)
            continue

        try:
            query = parse_qs(urlparse(value).query, keep_blank_values=False)
        except Exception:
            query = {}

        for key, values in query.items():
            if key.lower() not in nested_param_names:
                continue
            for nested in values:
                decoded = decode_url_repeatedly(nested)
                if decoded.startswith(("http://", "https://")):
                    pending.append(decoded)

        for match in re.findall(
            r"https?://[^\s\"'<>]+?(?:\.m3u8|\.flv)(?:\?[^\s\"'<>]*)?",
            decode_url_repeatedly(value),
            flags=re.IGNORECASE,
        ):
            pending.append(match.rstrip("),];"))

    return found


def stream_referer_hint(raw_candidate: str, frame_url: str = "") -> str:
    """Ưu tiên origin của iframe embed chứa streamUrl, không dùng nhầm trang trận."""
    decoded = decode_url_repeatedly(raw_candidate)
    if extract_stream_urls(decoded) and not is_direct_stream_url(decoded):
        embedded_origin = origin_from_url(decoded)
        if embedded_origin:
            return embedded_origin + "/"
    if frame_url:
        frame_origin = origin_from_url(frame_url)
        if frame_origin:
            return frame_origin + "/"
    return ""


def normalize_playback_referer(value: str) -> str:
    """Chuẩn hóa Referer cho player; ưu tiên root live.chuoichien.tv đã kiểm chứng."""
    candidate = decode_url_repeatedly(value)
    parsed = urlparse(candidate)
    if parsed.scheme and parsed.netloc:
        origin = f"{parsed.scheme}://{parsed.netloc}"
        if parsed.netloc.lower() == urlparse(PLAYER_ORIGIN_FALLBACK).netloc.lower():
            return origin + "/"
        return candidate
    return PLAYER_ORIGIN_FALLBACK + "/"


def clean_match_name(value: str, fallback_url: str) -> str:
    text = clean_text(value)
    # Ưu tiên dòng/đoạn chứa "vs" nếu card còn kèm giải, thời gian, trạng thái.
    pieces = [clean_text(p) for p in re.split(r"[\n|]", value or "") if clean_text(p)]
    vs_piece = next((p for p in pieces if re.search(r"\bvs\b", p, re.I)), "")
    if vs_piece:
        text = vs_piece

    text = TIME_RE.sub(" ", text)
    text = re.sub(
        r"(?i)\b(xem ngay|trực tiếp|hot|live|bóng đá|sắp diễn ra|đang diễn ra|socolive)\b",
        " ",
        text,
    )
    text = clean_text(text).strip(" -|•")

    if not re.search(r"\bvs\b", text, re.I):
        slug = unquote(urlparse(fallback_url).path.rstrip("/").split("/")[-1])
        slug = re.sub(r"-\d{2}-\d{2}-\d{4}-\d{4}$", "", slug)
        slug = re.sub(r"-vs-", " vs ", slug, flags=re.I)
        slug = slug.replace("-", " ")
        text = clean_text(slug)

    return text or fallback_url


def derive_match_info(
    url: str,
    raw_title: str = "",
    raw_time: str = "",
) -> tuple[str, str, str]:
    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    match_name = clean_match_name(raw_title, url)
    time_str = extract_time(raw_time) or extract_time(raw_title)

    if not time_str:
        suffix = re.search(r"-(\d{2})(\d{2})/?$", parsed.path)
        if suffix:
            time_str = f"{suffix.group(1)}:{suffix.group(2)}"

    blv_name = ""
    for key in ("blvName", "blv_name", "commentator", "commentatorName", "blv"):
        values = query.get(key) or query.get(key.lower())
        if values:
            blv_name = normalize_blv_name(values[0])
            if blv_name:
                break

    return match_name, time_str, blv_name


def is_good_logo_url(value: str) -> bool:
    lower = (value or "").lower()
    if not value or value.startswith(("data:", "blob:")):
        return False
    bad = (
        "avatar", "banner", "advert", "doubleclick", "googleads", "emoji",
        "flag", "favicon", "placeholder", "default-avatar", "no-image",
        "logo-white", "logo-dark", "site-logo", "loading.gif",
    )
    return not any(marker in lower for marker in bad)


def _team_parts(match_name: str) -> tuple[str, str]:
    parts = re.split(r"(?i)\s+vs\s+", clean_text(match_name), maxsplit=1)
    home = parts[0] if parts else ""
    away = parts[1].split(" - ", 1)[0] if len(parts) > 1 else ""
    return home, away


def _candidate_dict(value: Any, base: str) -> dict[str, Any]:
    if isinstance(value, dict):
        raw_url = str(value.get("url") or value.get("value") or "")
        context = clean_text(str(value.get("context") or ""))
        source = clean_text(str(value.get("source") or ""))
        try:
            score = float(value.get("score") or 0)
        except Exception:
            score = 0.0
    else:
        raw_url = str(value or "")
        context = ""
        source = ""
        score = 0.0
    return {
        "url": absolute_url(raw_url, base),
        "context": context,
        "source": source,
        "score": score,
    }


def _logo_context_and_hits(
    candidate: dict[str, Any],
    match_name: str,
) -> tuple[str, int, int]:
    url = candidate.get("url", "")
    context = normalize_search_text(
        f"{candidate.get('context', '')} {urlparse(url).path}"
    )
    home, away = _team_parts(match_name)
    home_tokens = [
        token for token in normalize_search_text(home).split()
        if len(token) >= 4
    ]
    away_tokens = [
        token for token in normalize_search_text(away).split()
        if len(token) >= 4
    ]
    home_hits = sum(1 for token in home_tokens if f" {token} " in f" {context} ")
    away_hits = sum(1 for token in away_tokens if f" {token} " in f" {context} ")
    return context, home_hits, away_hits


def score_logo_candidate(candidate: dict[str, Any], match_name: str) -> float:
    url = candidate.get("url", "")
    if not is_good_logo_url(url):
        return -10000

    score = float(candidate.get("score") or 0)
    context, home_hits, away_hits = _logo_context_and_hits(candidate, match_name)
    source = clean_text(str(candidate.get("source") or "")).lower()

    if home_hits:
        score += 55 + min(home_hits, 3) * 8
    elif away_hits:
        score += 35 + min(away_hits, 3) * 6

    if any(marker in f" {context} " for marker in (
        " team ", " club ", " home ", " away ", " doi ", " đội "
    )):
        score += 10

    if any(marker in f" {context} " for marker in (
        " avatar ", " blv ", " commentator ", " banner ", " league ",
        " sponsor ", " advert ", " quảng cáo "
    )):
        score -= 45

    # Ảnh lấy từ card/trang trận nhưng không hề có dấu hiệu thuộc hai đội rất dễ là
    # logo của một trận liên quan nằm cùng section. Thà bỏ trống còn hơn gán sai.
    if not home_hits and not away_hits:
        if source in {"home-card", "detail-match", "detail-team"}:
            score -= 18
        else:
            score -= 40

    if source == "detail-team":
        score += 10
    elif source == "detail-match":
        score += 5
    elif source == "meta":
        score -= 25

    return score


def ranked_logo_candidates(
    candidates: list[Any],
    base: str,
    match_name: str = "",
) -> list[dict[str, Any]]:
    # Cùng một URL có thể xuất hiện từ card trang chủ, DOM trang trận và metadata.
    # Giữ bản có context/điểm tốt nhất thay vì giữ lần xuất hiện đầu tiên.
    best_by_url: dict[str, dict[str, Any]] = {}
    for value in candidates:
        item = _candidate_dict(value, base)
        if not item["url"]:
            continue
        _context, home_hits, away_hits = _logo_context_and_hits(item, match_name)
        item["home_hits"] = home_hits
        item["away_hits"] = away_hits
        item["final_score"] = score_logo_candidate(item, match_name)
        if item["final_score"] <= -1000:
            continue
        previous = best_by_url.get(item["url"])
        if previous is None or (
            item["final_score"], item.get("home_hits", 0), item.get("away_hits", 0)
        ) > (
            previous["final_score"], previous.get("home_hits", 0), previous.get("away_hits", 0)
        ):
            best_by_url[item["url"]] = item

    ranked = list(best_by_url.values())
    ranked.sort(
        key=lambda item: (
            item["final_score"],
            item.get("home_hits", 0),
            item.get("away_hits", 0),
        ),
        reverse=True,
    )
    return ranked


def choose_logo(candidates: list[Any], base: str, match_name: str = "") -> str:
    ranked = ranked_logo_candidates(candidates, base, match_name)
    if not ranked:
        return ""
    best = ranked[0]
    # Chỉ dùng khi có dấu hiệu rõ ràng ảnh thuộc đội/trận hiện tại.
    if best["final_score"] < 28:
        return ""
    if not best.get("home_hits") and not best.get("away_hits") and best["final_score"] < 45:
        return ""
    return best["url"]


def resolve_duplicate_logos(results: list[dict[str, Any]]) -> None:
    """Giữ logo lặp cho đúng trận nhất, loại khỏi các trận bị gán nhầm."""
    ranked_by_result: dict[int, list[dict[str, Any]]] = {}
    for result in results:
        candidates = list(result.get("logo_candidates") or [])
        candidates.extend(result.get("team_logos") or [])
        if result.get("logo"):
            candidates.append(result["logo"])
        ranked = ranked_logo_candidates(
            candidates,
            result.get("url") or TARGET_URL,
            result.get("match_name") or "",
        )
        ranked_by_result[id(result)] = ranked
        result["logo"] = choose_logo(
            candidates,
            result.get("url") or TARGET_URL,
            result.get("match_name") or "",
        )

    usage: dict[str, list[dict[str, Any]]] = {}
    for result in results:
        if result.get("logo"):
            usage.setdefault(result["logo"], []).append(result)

    reserved: set[str] = set()
    for logo_url, owners in usage.items():
        home_teams = {
            normalize_search_text(_team_parts(owner.get("match_name", ""))[0]).strip()
            for owner in owners
        }
        if len(owners) < 2 or len(home_teams) <= 1:
            reserved.add(logo_url)
            continue

        scored_owners: list[tuple[float, int, int, dict[str, Any]]] = []
        for owner in owners:
            candidate = next(
                (item for item in ranked_by_result[id(owner)] if item["url"] == logo_url),
                None,
            )
            if candidate:
                scored_owners.append((
                    float(candidate.get("final_score") or -9999),
                    int(candidate.get("home_hits") or 0),
                    int(candidate.get("away_hits") or 0),
                    owner,
                ))
            else:
                scored_owners.append((-9999.0, 0, 0, owner))

        scored_owners.sort(key=lambda item: (item[0], item[1], item[2]), reverse=True)
        top = scored_owners[0]
        second_score = scored_owners[1][0] if len(scored_owners) > 1 else -9999
        winner: dict[str, Any] | None = None
        if (
            top[0] >= 45
            and (top[1] > 0 or top[2] > 0)
            and (top[0] - second_score >= 12 or second_score < 28)
        ):
            winner = top[3]
            reserved.add(logo_url)

        print(
            f"   ⚠️ Phát hiện một logo bị gán cho {len(owners)} trận khác nhau; "
            f"giữ cho trận khớp nhất và chọn lại các trận còn lại: {logo_url}",
            flush=True,
        )

        for owner in owners:
            if owner is winner:
                continue
            alternatives = [
                item for item in ranked_by_result[id(owner)]
                if item["url"] != logo_url
                and item["url"] not in reserved
                and item["final_score"] >= 28
                and (item.get("home_hits") or item.get("away_hits"))
            ]
            owner["logo"] = alternatives[0]["url"] if alternatives else ""
            if owner["logo"]:
                reserved.add(owner["logo"])



async def install_route_filter(page: Page, homepage: bool = False) -> None:
    """Cho ảnh tải để lazy-load logo hoạt động; chỉ chặn font và media ở trang chủ."""
    blocked_types = {"font"}
    if homepage:
        blocked_types.add("media")

    async def route_handler(route: Route) -> None:
        if route.request.resource_type in blocked_types:
            await route.abort()
        else:
            await route.continue_()

    await page.route("**/*", route_handler)


async def collect_dom_stream_candidates(page: Page) -> list[dict[str, str]]:
    candidates: list[dict[str, str]] = []
    seen: set[tuple[str, str, str]] = set()

    for frame in page.frames:
        try:
            frame_candidates = await frame.evaluate(
                r"""() => {
                    const out = [];
                    const seen = new Set();
                    const clean = (v) => String(v || "").replace(/\s+/g, " ").trim();
                    const qualityOf = (v) => {
                        const text = clean(v);
                        const match = text.match(/\b(4K|UHD|2160p?|Full\s*HD|FHD|1080p?|HD|720p?|SD|480p?|Auto)\b/i);
                        return match ? match[1] : "";
                    };
                    const add = (value, quality = "", context = "") => {
                        if (!value) return;
                        const raw = String(value).trim();
                        if (!raw || raw.length > 12000) return;
                        const key = `${raw}\n${quality}`;
                        if (seen.has(key)) return;
                        seen.add(key);
                        out.push({url: raw, quality: qualityOf(quality || context), context: clean(context)});
                    };

                    try {
                        for (const entry of performance.getEntriesByType("resource")) {
                            if (entry && entry.name) add(entry.name);
                        }
                    } catch (_) {}

                    document.querySelectorAll("*").forEach((el) => {
                        const attrs = Array.from(el.attributes || []).map((attr) => `${attr.name}=${attr.value}`);
                        const context = clean([
                            el.innerText && el.innerText.length < 160 ? el.innerText : "",
                            el.getAttribute?.("aria-label"), el.getAttribute?.("title"),
                            el.className, attrs.join(" ")
                        ].filter(Boolean).join(" "));
                        const quality = qualityOf(context);
                        [el.src, el.currentSrc, el.data].forEach((value) => add(value, quality, context));
                        attrs.forEach((entry) => {
                            const value = entry.slice(entry.indexOf("=") + 1);
                            if (/m3u8|\.flv|stream|playurl|source|https?(?:%3a|:)/i.test(value)) {
                                add(value, quality, context);
                            }
                        });
                    });

                    const htmlText = document.documentElement?.innerHTML || "";
                    const normalized = htmlText
                        .replace(/\\u002[fF]/g, "/")
                        .replace(/\\x2[fF]/g, "/")
                        .replace(/\\u003[aA]/g, ":")
                        .replace(/\\u0026/g, "&")
                        .replace(/\\u003[dD]/g, "=")
                        .replace(/\\\//g, "/")
                        .replace(/&amp;/g, "&");
                    (normalized.match(/https?:\/\/[^"' <>\n\r]+?(?:\.m3u8|\.flv)(?:\?[^"' <>\n\r]*)?/gi) || [])
                        .forEach((value) => add(value));
                    (normalized.match(/https?:\/\/[^"' <>\n\r]+?(?:streamUrl|stream_url|file|src|url|source|playurl)=[^"' <>\n\r]+/gi) || [])
                        .forEach((value) => add(value));
                    (normalized.match(/https?%3[aA]%2[fF]%2[fF][^"' <>\n\r]+/g) || [])
                        .forEach((value) => add(value));
                    return out.slice(0, 800);
                }"""
            )
            for item in frame_candidates:
                raw_url = str(item.get("url", "")) if isinstance(item, dict) else str(item)
                quality = str(item.get("quality", "")) if isinstance(item, dict) else ""
                context = str(item.get("context", "")) if isinstance(item, dict) else ""
                key = (raw_url, frame.url or "", quality)
                if raw_url and key not in seen:
                    seen.add(key)
                    candidates.append({
                        "url": raw_url,
                        "frame_url": frame.url or "",
                        "quality": normalize_quality_hint(quality or context),
                    })
        except Exception:
            continue

    return candidates


async def stimulate_player(page: Page) -> None:
    for selector in PLAY_SELECTORS:
        try:
            locator = page.locator(selector)
            if await locator.count():
                await locator.first.click(timeout=700, force=True)
        except Exception:
            pass

    for frame in page.frames:
        try:
            await frame.evaluate(
                """() => {
                    document.querySelectorAll("video").forEach((video) => {
                        try {
                            video.muted = true;
                            video.volume = 0;
                            const result = video.play();
                            if (result && typeof result.catch === "function") {
                                result.catch(() => {});
                            }
                        } catch (_) {}
                    });
                }"""
            )
        except Exception:
            pass


async def stimulate_quality_variants(page: Page) -> int:
    """Mở menu chất lượng và lần lượt kích hoạt HD/FHD/1080 để lộ mọi URL."""
    clicked = 0
    for frame in page.frames:
        try:
            count = await frame.evaluate(
                r"""async () => {
                    const delay = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
                    const clean = (v) => String(v || "").replace(/\s+/g, " ").trim();
                    const visible = (el) => {
                        const rect = el.getBoundingClientRect();
                        const style = getComputedStyle(el);
                        return rect.width > 0 && rect.height > 0 && style.display !== "none" && style.visibility !== "hidden";
                    };
                    const nodes = Array.from(document.querySelectorAll(
                        "button, a, [role='button'], [role='option'], li, label, [data-quality], [data-resolution]"
                    )).filter((el) => {
                        if (el.tagName !== "A") return true;
                        const href = String(el.getAttribute("href") || "").trim();
                        return !href || href === "#" || href.startsWith("javascript:");
                    });
                    const textOf = (el) => clean([
                        el.innerText, el.textContent, el.getAttribute("aria-label"),
                        el.getAttribute("title"), el.getAttribute("data-quality"),
                        el.getAttribute("data-resolution"), el.className
                    ].filter(Boolean).join(" "));

                    let clicks = 0;
                    const menu = nodes.find((el) => visible(el) && /quality|chất lượng|độ phân giải/i.test(textOf(el)));
                    if (menu) {
                        try { menu.click(); clicks += 1; await delay(300); } catch (_) {}
                    }

                    const options = nodes.filter((el) =>
                        visible(el) && /\b(4K|UHD|2160p?|Full\s*HD|FHD|1080p?|HD|720p?|SD|480p?)\b/i.test(textOf(el))
                    ).slice(0, 10);
                    for (const option of options) {
                        try { option.click(); clicks += 1; await delay(450); } catch (_) {}
                    }
                    return clicks;
                }"""
            )
            clicked += int(count or 0)
        except Exception:
            continue
    return clicked


async def scan_quality_variants(page: Page, capture_callback: Any) -> list[str]:
    """Bấm từng mức chất lượng, chờ player đổi nguồn rồi quét lại URL sau mỗi lần."""
    discovered: list[str] = []

    for frame in list(page.frames):
        try:
            labels = await frame.evaluate(
                r"""() => {
                    const clean = (v) => String(v || "").replace(/\s+/g, " ").trim();
                    const qualityOf = (value) => {
                        const text = clean(value);
                        if (/\b(4K|UHD|2160p?)\b/i.test(text)) return "4K";
                        if (/\b(Full\s*HD|FHD|1080p?)\b/i.test(text)) return "FHD";
                        if (/\b(HD|720p?)\b/i.test(text)) return "HD";
                        if (/\b(SD|480p?)\b/i.test(text)) return "SD";
                        return "";
                    };
                    const values = [];
                    document.querySelectorAll(
                        "button, a, [role='button'], [role='option'], li, label, " +
                        "[data-quality], [data-resolution]"
                    ).forEach((el) => {
                        const blob = clean([
                            el.innerText, el.textContent, el.getAttribute("aria-label"),
                            el.getAttribute("title"), el.getAttribute("data-quality"),
                            el.getAttribute("data-resolution"), el.className
                        ].filter(Boolean).join(" "));
                        const quality = qualityOf(blob);
                        if (quality && !values.includes(quality)) values.push(quality);
                    });
                    return values;
                }"""
            )
            for label in labels or []:
                normalized = normalize_quality_hint(str(label))
                if normalized and normalized not in discovered:
                    discovered.append(normalized)
        except Exception:
            continue

    order = {"4K": 0, "FHD": 1, "HD": 2, "SD": 3}
    discovered.sort(key=lambda value: order.get(value, 99))
    activated: list[str] = []

    for target in discovered[:8]:
        clicked = False
        for frame in list(page.frames):
            try:
                clicked = bool(await frame.evaluate(
                    r"""async (target) => {
                        const delay = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
                        const clean = (v) => String(v || "").replace(/\s+/g, " ").trim();
                        const visible = (el) => {
                            const rect = el.getBoundingClientRect();
                            const style = getComputedStyle(el);
                            return rect.width > 0 && rect.height > 0 &&
                                style.display !== "none" && style.visibility !== "hidden";
                        };
                        const qualityOf = (value) => {
                            const text = clean(value);
                            if (/\b(4K|UHD|2160p?)\b/i.test(text)) return "4K";
                            if (/\b(Full\s*HD|FHD|1080p?)\b/i.test(text)) return "FHD";
                            if (/\b(HD|720p?)\b/i.test(text)) return "HD";
                            if (/\b(SD|480p?)\b/i.test(text)) return "SD";
                            return "";
                        };
                        const selector = "button, a, [role='button'], [role='option'], li, label, " +
                            "[data-quality], [data-resolution]";
                        const textOf = (el) => clean([
                            el.innerText, el.textContent, el.getAttribute("aria-label"),
                            el.getAttribute("title"), el.getAttribute("data-quality"),
                            el.getAttribute("data-resolution"), el.className
                        ].filter(Boolean).join(" "));

                        let nodes = Array.from(document.querySelectorAll(selector));
                        const menu = nodes.find((el) => visible(el) &&
                            /quality|chất lượng|độ phân giải/i.test(textOf(el)));
                        if (menu) {
                            try { menu.click(); await delay(350); } catch (_) {}
                        }
                        nodes = Array.from(document.querySelectorAll(selector));
                        const option = nodes.find((el) => {
                            if (!visible(el) || qualityOf(textOf(el)) !== target) return false;
                            if (el.tagName !== "A") return true;
                            const href = String(el.getAttribute("href") || "").trim();
                            return !href || href === "#" || href.startsWith("javascript:");
                        });
                        if (!option) return false;
                        try {
                            option.scrollIntoView({block: "center", inline: "center"});
                            option.click();
                            option.dispatchEvent(new MouseEvent("click", {bubbles: true, cancelable: true, view: window}));
                            await delay(500);
                            return true;
                        } catch (_) {
                            return false;
                        }
                    }""",
                    target,
                ))
            except Exception:
                clicked = False

            if clicked:
                await page.wait_for_timeout(900)
                await stimulate_player(page)
                for candidate in await collect_dom_stream_candidates(page):
                    capture_callback(
                        candidate["url"],
                        f"quality/{target}",
                        frame_url=candidate.get("frame_url", ""),
                        quality=target or candidate.get("quality", ""),
                    )
                activated.append(target)
                break

    return activated


async def read_match_metadata(
    page: Page,
    match_url: str,
    match_name: str = "",
    blv_slug: str = "",
) -> dict[str, Any]:
    try:
        data = await page.evaluate(
            r"""({matchName, blvSlug}) => {
                const clean = (v) => String(v || "").replace(/\s+/g, " ").trim();
                const norm = (v) => clean(v).normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase();
                const teamParts = clean(matchName).split(/\s+vs\s+/i);
                const homeTokens = norm(teamParts[0] || "").split(/[^a-z0-9]+/).filter((v) => v.length >= 4);
                const awayTokens = norm((teamParts[1] || "").split(" - ")[0]).split(/[^a-z0-9]+/).filter((v) => v.length >= 4);
                const logoItems = [];
                const seen = new Set();

                function addLogo(v, score = 0, context = "", source = "detail-match") {
                    if (!v) return;
                    let value = String(v).trim();
                    if (!value || value.startsWith("data:") || value.startsWith("blob:")) return;
                    try { value = new URL(value, location.href).href; } catch (_) {}
                    if (seen.has(value)) return;
                    seen.add(value);
                    const normalizedContext = norm(`${context} ${value}`);
                    if (homeTokens.some((token) => normalizedContext.includes(token))) score += 60;
                    else if (awayTokens.some((token) => normalizedContext.includes(token))) score += 35;
                    if (/team|club|home|away|doi|đội/i.test(context)) score += 12;
                    if (/avatar|blv|comment|banner|advert|flag|league/i.test(context)) score -= 35;
                    logoItems.push({url: value, score, context: clean(context), source});
                }

                function inspectImage(img, baseScore = 0, source = "detail-match") {
                    const nearby = clean([
                        img.alt, img.title, img.className,
                        img.parentElement?.innerText, img.parentElement?.className,
                        img.parentElement?.parentElement?.innerText,
                        img.parentElement?.parentElement?.className
                    ].filter(Boolean).join(" ")).slice(0, 500);
                    let score = baseScore;
                    const width = img.naturalWidth || img.width || 0;
                    const height = img.naturalHeight || img.height || 0;
                    if (width && height && Math.abs(width - height) <= Math.max(width, height) * 0.35) score += 5;
                    [
                        img.currentSrc, img.src, img.getAttribute("src"),
                        img.getAttribute("data-src"), img.getAttribute("data-original"),
                        img.getAttribute("data-lazy-src")
                    ].forEach((value) => addLogo(value, score, nearby, source));
                    [img.getAttribute("srcset"), img.getAttribute("data-srcset")].filter(Boolean)
                        .forEach((set) => set.split(",").forEach((part) =>
                            addLogo(part.trim().split(/\s+/)[0], score, nearby, source)
                        ));
                }

                const tokenMatchCount = (value, tokens) => {
                    const text = norm(value);
                    return tokens.filter((token) => text.includes(token)).length;
                };
                const belongsToCurrentMatch = (node) => {
                    const blob = clean([
                        node?.innerText, node?.textContent, node?.className,
                        node?.getAttribute?.("aria-label"), node?.getAttribute?.("data-team"),
                        node?.getAttribute?.("data-home"), node?.getAttribute?.("data-away")
                    ].filter(Boolean).join(" ")).slice(0, 1600);
                    return tokenMatchCount(blob, homeTokens) > 0 || tokenMatchCount(blob, awayTokens) > 0;
                };

                const rootSelectors = [
                    "[class*='match-info']", "[class*='match-detail']", "[class*='event-detail']",
                    "[class*='match-header']", "[class*='fixture-detail']", "article", "main"
                ];
                const rootCandidates = Array.from(document.querySelectorAll(rootSelectors.join(",")))
                    .filter((node) => {
                        const blob = clean(node.innerText || node.textContent || "").slice(0, 5000);
                        return tokenMatchCount(blob, homeTokens) > 0 && tokenMatchCount(blob, awayTokens) > 0;
                    })
                    .sort((a, b) => clean(a.innerText || a.textContent).length - clean(b.innerText || b.textContent).length);
                const primaryRoot = rootCandidates[0] || document.querySelector("[class*='match-detail']") || null;

                const teamScope = primaryRoot || document;
                const teamNodes = Array.from(teamScope.querySelectorAll(
                    "[class*='team'], [class*='club'], [class*='home'], [class*='away'], " +
                    "[data-team], [data-home], [data-away]"
                )).filter(belongsToCurrentMatch);
                teamNodes.forEach((node) =>
                    node.querySelectorAll("img").forEach((img) => inspectImage(img, 24, "detail-team"))
                );

                if (primaryRoot) {
                    primaryRoot.querySelectorAll("img").forEach((img) => {
                        const nearby = clean([
                            img.alt, img.title, img.parentElement?.innerText,
                            img.parentElement?.parentElement?.innerText
                        ].filter(Boolean).join(" "));
                        if (belongsToCurrentMatch(img.parentElement) || tokenMatchCount(nearby, homeTokens) || tokenMatchCount(nearby, awayTokens)) {
                            inspectImage(img, 10, "detail-match");
                        }
                    });
                }

                [
                    document.querySelector("meta[property='og:image']")?.content,
                    document.querySelector("meta[name='twitter:image']")?.content,
                    document.querySelector("link[rel='image_src']")?.href
                ].forEach((value) => addLogo(value, -15, "meta image", "meta"));

                const titleSelectors = [
                    "h1", "[class*='match-title']", "[class*='match-name']",
                    "[class*='event-title']", "h2", "title"
                ];
                let title = "";
                for (const selector of titleSelectors) {
                    const nodes = selector === "title" ? [document.querySelector("title")] : Array.from(document.querySelectorAll(selector));
                    const found = nodes.find((el) => el && /\bvs\b/i.test(clean(el.innerText || el.textContent)));
                    if (found) { title = clean(found.innerText || found.textContent); break; }
                }

                const timeParts = [];
                document.querySelectorAll(
                    "time, [datetime], [data-time], [data-start], [data-date], " +
                    "[class*='time'], [class*='kickoff'], [class*='date']"
                ).forEach((el) => {
                    [el.getAttribute("datetime"), el.getAttribute("data-time"),
                     el.getAttribute("data-start"), el.getAttribute("data-date"),
                     el.innerText, el.textContent].forEach((v) => { if (v) timeParts.push(clean(v)); });
                });

                document.querySelectorAll("script[type='application/ld+json']").forEach((script) => {
                    try {
                        const raw = JSON.parse(script.textContent || "null");
                        const items = Array.isArray(raw) ? raw : [raw];
                        items.forEach((item) => {
                            if (item && item.startDate) timeParts.push(String(item.startDate));
                            if (!title && item && item.name) title = clean(item.name);
                            if (item && item.image) (Array.isArray(item.image) ? item.image : [item.image])
                                .forEach((value) => addLogo(value, 2, String(item.name || "json ld")));
                        });
                    } catch (_) {}
                });

                const iframeUrls = Array.from(document.querySelectorAll("iframe[src]"))
                    .map((el) => el.src || el.getAttribute("src") || "").filter(Boolean);

                const qualitySources = [];
                const qualitySeen = new Set();
                const qualityOf = (value) => {
                    const text = clean(value);
                    const match = text.match(/\b(4K|UHD|2160p?|Full\s*HD|FHD|1080p?|HD|720p?|SD|480p?)\b/i);
                    return match ? match[1] : "";
                };
                const addQualitySource = (value, quality, context = "") => {
                    if (!value) return;
                    const raw = String(value).trim();
                    if (!raw || raw.length > 12000) return;
                    const key = `${raw}\n${quality}`;
                    if (qualitySeen.has(key)) return;
                    qualitySeen.add(key);
                    qualitySources.push({url: raw, quality: qualityOf(quality || context), context: clean(context)});
                };
                document.querySelectorAll(
                    "iframe[src], a[href], source[src], video[src], [data-url], [data-src], " +
                    "[data-stream], [data-stream-url], [data-quality], [data-resolution], [data-file]"
                ).forEach((el) => {
                    const attrs = [
                        el.getAttribute("src"), el.getAttribute("href"), el.getAttribute("data-url"),
                        el.getAttribute("data-src"), el.getAttribute("data-stream"),
                        el.getAttribute("data-stream-url"), el.getAttribute("data-file")
                    ].filter(Boolean);
                    const context = clean([
                        el.innerText, el.textContent, el.getAttribute("title"), el.getAttribute("aria-label"),
                        el.getAttribute("data-quality"), el.getAttribute("data-resolution"), el.className
                    ].filter(Boolean).join(" "));
                    const quality = qualityOf(context);
                    attrs.forEach((value) => {
                        if (/m3u8|\.flv|streamUrl|stream_url|playurl|source=/i.test(String(value))) {
                            addQualitySource(value, quality, context);
                        }
                    });
                });

                let blv = "";
                const currentSlug = clean(blvSlug || new URLSearchParams(location.search).get("blv") || "").toLowerCase();
                const blvSelectors = [
                    "[data-blv].active", "[data-blv][aria-selected='true']",
                    "[class*='blv'].active", "[class*='commentator'].active",
                    "[class*='blv-name']", "[class*='commentator-name']"
                ];
                for (const selector of blvSelectors) {
                    const el = document.querySelector(selector);
                    const value = clean(el?.innerText || el?.textContent || el?.getAttribute?.("data-name"));
                    if (value && value.length <= 80) { blv = value; break; }
                }
                if (!blv && currentSlug) {
                    const nodes = Array.from(document.querySelectorAll("a[href], [data-blv], [data-commentator]"));
                    const found = nodes.find((el) => {
                        const blob = norm([el.getAttribute("href"), el.getAttribute("data-blv"),
                            el.getAttribute("data-commentator"), el.id, el.className].filter(Boolean).join(" "));
                        return blob.includes(norm(currentSlug));
                    });
                    const value = clean(found?.innerText || found?.textContent || found?.getAttribute?.("data-name"));
                    if (value && value.length <= 80) blv = value;
                }
                if (!blv) {
                    const bodyText = clean(document.body?.innerText || "");
                    const match = bodyText.match(/(?:BLV|Bình luận viên)\s*[:\-–—]?\s*([^|•\n]{2,40})/i);
                    if (match) blv = clean(match[1]);
                }

                const sportParts = [
                    document.body?.getAttribute("data-sport"), document.body?.getAttribute("data-category"),
                    document.querySelector("meta[name='description']")?.content,
                    document.querySelector("[data-sport]")?.getAttribute("data-sport"),
                    document.querySelector("[data-category]")?.getAttribute("data-category"),
                    document.querySelector("[class*='breadcrumb']")?.innerText,
                    document.querySelector("[class*='sport-name']")?.innerText,
                    document.querySelector("[class*='category-name']")?.innerText,
                    document.querySelector("[class*='league-name']")?.innerText, title
                ].filter(Boolean).map(clean);

                logoItems.sort((a, b) => b.score - a.score);
                return {
                    title, time_text: timeParts.join(" | "),
                    logos: logoItems.map((item) => item.url),
                    logo_candidates: logoItems.slice(0, 24),
                    iframe_urls: iframeUrls,
                    quality_sources: qualitySources.slice(0, 80),
                    sport_text: sportParts.join(" | "), blv
                };
            }""",
            {"matchName": match_name, "blvSlug": blv_slug},
        )
        data["logos"] = [absolute_url(str(v), match_url) for v in data.get("logos", []) if v]
        for item in data.get("logo_candidates", []) or []:
            if isinstance(item, dict):
                item["url"] = absolute_url(str(item.get("url", "")), match_url)
        return data
    except Exception:
        return {
            "title": "", "time_text": "", "logos": [], "logo_candidates": [],
            "iframe_urls": [], "quality_sources": [], "sport_text": "", "blv": "",
        }


async def fetch_stream(
    context: BrowserContext,
    match: dict[str, Any],
    sem: asyncio.Semaphore,
) -> dict[str, Any]:
    async with sem:
        match_name, time_str, blv_from_link = derive_match_info(
            match["url"], match.get("raw_title", ""), match.get("raw_time", "")
        )
        match["match_name"] = match_name
        match["time"] = time_str
        match["blv"] = blv_from_link
        match["streams"] = []
        match["stream_urls"] = []
        match["errors"] = []
        match["sport_group"] = classify_sport(
            match.get("sport_hint", ""),
            match.get("card_text", ""),
            match.get("raw_title", ""),
            match.get("url", ""),
            default=match.get("sport_group", "Bóng đá"),
        )

        scan_index = int(match.get("_scan_index", 0))
        scan_total = int(match.get("_scan_total", 0))
        prefix = f"[{scan_index}/{scan_total}] " if scan_index and scan_total else ""
        print(
            f"-> {prefix}Đang quét [{match['sport_group']}]: {match_name[:90]}",
            flush=True,
        )
        page = await context.new_page()
        await install_route_filter(page, homepage=False)

        stream_map: dict[str, dict[str, Any]] = {}
        first_stream_at: float | None = None
        rate_limit_urls: set[str] = set()
        response_body_tasks: set[asyncio.Task[Any]] = set()

        def capture_url(
            raw_url: str,
            source: str,
            headers: dict[str, str] | None = None,
            frame_url: str = "",
            status: int | None = None,
            content_type: str = "",
            quality: str = "",
            parent_url: str = "",
        ) -> None:
            nonlocal first_stream_at
            normalized_headers = {
                str(k).lower(): str(v) for k, v in (headers or {}).items()
            }
            hint = stream_referer_hint(raw_url, frame_url)

            for stream_url in extract_stream_urls(raw_url, content_type):
                normalized = decode_url_repeatedly(stream_url)
                entry = stream_map.setdefault(
                    normalized,
                    {
                        "url": normalized,
                        "referer": "",
                        "origin": "",
                        "user_agent": "",
                        "status": None,
                        "statuses": [],
                        "content_type": "",
                        "sources": [],
                        "quality": "",
                        "parent_url": "",
                    },
                )

                referer = normalize_playback_referer(
                    normalized_headers.get("referer", "") or hint
                )
                # Không tự tạo Origin. VLC thử nghiệm chạy với Referer + User-Agent;
                # Origin dư thừa có thể làm CDN từ chối. Chỉ lưu nếu request thật có gửi.
                origin = normalized_headers.get("origin", "")
                user_agent = normalized_headers.get("user-agent", "") or UA

                if referer:
                    entry["referer"] = referer
                if origin:
                    entry["origin"] = origin
                if user_agent:
                    entry["user_agent"] = user_agent
                if status is not None:
                    entry["status"] = status
                    if status not in entry["statuses"]:
                        entry["statuses"].append(status)
                if content_type:
                    entry["content_type"] = content_type
                normalized_quality = normalize_quality_hint(quality or raw_url)
                if normalized_quality:
                    entry["quality"] = normalized_quality
                if parent_url:
                    entry["parent_url"] = parent_url
                if source not in entry["sources"]:
                    entry["sources"].append(source)

                if first_stream_at is None:
                    first_stream_at = time.monotonic()
                if len(entry["sources"]) == 1:
                    print(f"   🎯 [{source}] {normalized}")

        async def inspect_response_body(response: Any) -> None:
            try:
                content_type = (response.headers.get("content-type", "") or "").lower()
                content_length = response.headers.get("content-length", "")
                if content_length and int(content_length) > 2_500_000:
                    return
                kind = stream_kind(response.url, content_type)
                textual = any(marker in content_type for marker in (
                    "json", "javascript", "text/", "mpegurl", "xml"
                )) or kind == "m3u8"
                if not textual:
                    return
                body = await response.body()
                if not body or len(body) > 2_500_000:
                    return
                text = body.decode("utf-8", errors="ignore")
                request = response.request
                try:
                    frame_url = request.frame.url if request.frame else ""
                except Exception:
                    frame_url = ""
                for candidate in extract_stream_urls(text, content_type):
                    capture_url(
                        candidate, "response/body", headers=request.headers,
                        frame_url=frame_url, content_type=content_type,
                    )
                for variant in parse_hls_variants(text, response.url):
                    capture_url(
                        variant["url"], "hls/variant", headers=request.headers,
                        frame_url=frame_url, content_type="application/vnd.apple.mpegurl",
                        quality=variant.get("quality", ""),
                        parent_url=variant.get("parent_url", ""),
                    )
            except Exception:
                return

        def track_response_body(response: Any) -> None:
            task = asyncio.create_task(inspect_response_body(response))
            response_body_tasks.add(task)
            task.add_done_callback(response_body_tasks.discard)

        def handle_request(request: Any) -> None:
            try:
                frame_url = request.frame.url if request.frame else ""
            except Exception:
                frame_url = ""
            capture_url(
                request.url,
                f"request/{request.resource_type}",
                headers=request.headers,
                frame_url=frame_url,
            )

        def handle_response(response: Any) -> None:
            try:
                if response.status == 429 and response.url not in rate_limit_urls:
                    rate_limit_urls.add(response.url)
                    match["errors"].append(
                        f"HTTP 429 (tiếp tục quét, không restart): {response.url}"
                    )
                    print(f"   ⚠️ HTTP 429 nhưng vẫn tiếp tục quét full: {response.url}")

                req = response.request
                frame_url = req.frame.url if req.frame else ""
                content_type = response.headers.get("content-type", "")
                if any(marker in content_type.lower() for marker in (
                    "json", "javascript", "text/", "mpegurl", "xml"
                )) or stream_kind(response.url, content_type) == "m3u8":
                    track_response_body(response)
                capture_url(
                    response.url,
                    "response",
                    headers=req.headers,
                    frame_url=frame_url,
                    status=response.status,
                    content_type=content_type,
                )
            except Exception:
                capture_url(response.url, "response", status=response.status)

        def handle_page_error(error: Any) -> None:
            match["errors"].append(f"JS: {error}")

        def handle_console(message: Any) -> None:
            if message.type in {"error", "warning"}:
                text = str(message.text)
                if len(text) <= 500:
                    match["errors"].append(f"console/{message.type}: {text}")

        page.on("request", handle_request)
        page.on("response", handle_response)
        page.on("pageerror", handle_page_error)
        page.on("console", handle_console)

        try:
            await page.goto(match["url"], wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(1200)

            blv_slug = (parse_qs(urlparse(match["url"]).query).get("blv") or [""])[0]
            metadata = await read_match_metadata(
                page, match["url"], match.get("match_name", ""), blv_slug
            )
            if metadata.get("title"):
                better_name = clean_match_name(metadata["title"], match["url"])
                if re.search(r"\bvs\b", better_name, re.I):
                    match["match_name"] = better_name
            if not match.get("time"):
                match["time"] = extract_time(metadata.get("time_text", ""))
            if metadata.get("blv"):
                match["blv"] = normalize_blv_name(metadata.get("blv", "")) or match.get("blv", "")

            match["sport_group"] = classify_sport(
                match.get("sport_hint", ""),
                metadata.get("sport_text", ""),
                match.get("card_text", ""),
                match.get("match_name", ""),
                match.get("url", ""),
                default=match.get("sport_group", "Bóng đá"),
            )

            logo_candidates: list[Any] = list(match.get("logo_candidates") or [])
            logo_candidates.extend(match.get("team_logos") or [])
            if match.get("logo"):
                logo_candidates.append(match["logo"])
            logo_candidates.extend(metadata.get("logo_candidates") or [])
            logo_candidates.extend(metadata.get("logos") or [])
            match["logo_candidates"] = logo_candidates
            match["team_logos"] = [
                item.get("url", "") if isinstance(item, dict) else absolute_url(str(item), match["url"])
                for item in logo_candidates if item
            ]
            match["logo"] = choose_logo(
                logo_candidates, match["url"], match.get("match_name", "")
            )

            for iframe_url in metadata.get("iframe_urls") or []:
                iframe_blv = extract_blv_from_url(iframe_url)
                if iframe_blv and not match.get("blv"):
                    match["blv"] = iframe_blv
                capture_url(iframe_url, "iframe/src", frame_url=iframe_url)

            for source_info in metadata.get("quality_sources") or []:
                if not isinstance(source_info, dict):
                    continue
                capture_url(
                    str(source_info.get("url") or ""),
                    "metadata/quality-source",
                    frame_url=match["url"],
                    quality=str(source_info.get("quality") or ""),
                )

            activated_qualities = await scan_quality_variants(page, capture_url)
            if activated_qualities:
                print(
                    "   🎛️ Đã lần lượt thử các mức chất lượng: "
                    + ", ".join(activated_qualities),
                    flush=True,
                )
            else:
                quality_clicks = await stimulate_quality_variants(page)
                if quality_clicks:
                    print(
                        f"   🎛️ Đã thử fallback {quality_clicks} nút/tuỳ chọn chất lượng",
                        flush=True,
                    )

            deadline = time.monotonic() + STREAM_WAIT_SECONDS
            quality_retry_done = False
            while time.monotonic() < deadline:
                await stimulate_player(page)
                for candidate in await collect_dom_stream_candidates(page):
                    capture_url(
                        candidate["url"],
                        "dom/performance",
                        frame_url=candidate.get("frame_url", ""),
                        quality=candidate.get("quality", ""),
                    )

                if (
                    not FULL_SCAN
                    and first_stream_at is not None
                    and time.monotonic() - first_stream_at >= EXTRA_WAIT_AFTER_FIRST_STREAM
                ):
                    break
                elapsed = STREAM_WAIT_SECONDS - max(0.0, deadline - time.monotonic())
                if not quality_retry_done and elapsed >= max(8, STREAM_WAIT_SECONDS * 0.55):
                    quality_retry_done = True
                    retry_qualities = await scan_quality_variants(page, capture_url)
                    if retry_qualities:
                        print(
                            "   🔁 Quét lại nguồn sau khi đổi chất lượng: "
                            + ", ".join(retry_qualities),
                            flush=True,
                        )
                await page.wait_for_timeout(1000)

        except Exception as exc:
            error_text = f"{type(exc).__name__}: {exc}"
            match["errors"].append(error_text)
            print(f"   ❌ {match_name[:70]} | {error_text}")
        finally:
            if response_body_tasks:
                try:
                    await asyncio.wait_for(
                        asyncio.gather(*list(response_body_tasks), return_exceptions=True),
                        timeout=6,
                    )
                except Exception:
                    pass
            try:
                for candidate in await collect_dom_stream_candidates(page):
                    capture_url(
                        candidate["url"],
                        "final-scan",
                        frame_url=candidate.get("frame_url", ""),
                        quality=candidate.get("quality", ""),
                    )
            except Exception:
                pass
            await page.close()

        streams = []
        for entry in stream_map.values():
            # Header fallback đúng player embed, không dùng nhầm origin live03.
            entry["referer"] = normalize_playback_referer(
                entry.get("referer") or PLAYER_ORIGIN_FALLBACK + "/"
            )
            if not entry.get("user_agent"):
                entry["user_agent"] = UA

            status = entry.get("status")
            statuses = [int(value) for value in (entry.get("statuses") or [])]

            # 404/410 là link đã mất rõ ràng nên mới loại. Các mã 401/403/429/5xx
            # vẫn được giữ vì request trong Chromium có thể bị chặn, trong khi player
            # phát được khi gửi đúng Referer + User-Agent. Đây chính là trường hợp
            # URL FLV thử thủ công bằng VLC của người dùng.
            terminal_statuses = {404, 410}
            if statuses and all(value in terminal_statuses for value in statuses):
                match["errors"].append(
                    f"Stream chỉ trả {statuses}, loại link đã mất: {entry['url']}"
                )
                print(f"   ⚠️ Loại stream HTTP {statuses}: {entry['url']}")
                continue

            if status is not None and int(status) >= 400:
                match["errors"].append(
                    f"Stream HTTP {status} nhưng vẫn giữ để phát kèm header: {entry['url']}"
                )
                print(
                    f"   🛡️ Giữ stream HTTP {status}; Android/VLC sẽ gửi "
                    f"Referer + User-Agent: {entry['url']}"
                )
            streams.append(entry)

        variant_parents = {
            entry.get("parent_url") for entry in streams
            if entry.get("parent_url") and entry.get("quality")
        }
        if variant_parents:
            streams = [
                entry for entry in streams
                if entry.get("url") not in variant_parents or entry.get("quality")
            ]
        match["streams"] = sorted(
            streams, key=lambda item: (item.get("quality") or "ZZZ", item["url"])
        )
        match["stream_urls"] = [item["url"] for item in match["streams"]]

        if match["streams"]:
            for entry in match["streams"]:
                state = entry.get("status") or "chưa có status"
                print(
                    f"   ✅ Stream {state} | referer={entry.get('referer', '')} | "
                    f"logo={'có' if match.get('logo') else 'không'} | "
                    f"BLV={match.get('blv') or 'không rõ'} | "
                    f"chất lượng={entry.get('quality') or 'không rõ'} | "
                    f"giờ={match.get('time') or 'không rõ'}"
                )
        else:
            print(f"   ⚠️ Không thấy m3u8/flv: {match_name[:85]}")

        return match


async def collect_home_links(context: BrowserContext) -> list[dict[str, Any]]:
    page = await context.new_page()
    await install_route_filter(page, homepage=True)
    print(f"👉 Đang mở trang chủ: {TARGET_URL}")

    try:
        await page.goto(TARGET_URL, wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(HOME_WAIT_MS)

        for _ in range(5):
            await page.evaluate("window.scrollBy(0, Math.max(700, window.innerHeight));")
            await page.wait_for_timeout(700)

        result = await page.evaluate(
            r"""() => {
                const items = [];
                const seen = new Set();
                const clean = (v) => String(v || "").replace(/\s+/g, " ").trim();

                function normalizeHref(value) {
                    try { return new URL(value, location.href).href; }
                    catch (_) { return ""; }
                }

                function isMatchHref(value) {
                    const href = normalizeHref(value);
                    if (!href) return false;
                    try {
                        const path = new URL(href).pathname;
                        return /^\/live\/\d+(?:\/|$)/i.test(path) ||
                            path.includes("/truc-tiep/") || path.includes("/room/");
                    } catch (_) { return false; }
                }

                function imageCandidates(scope, matchText = "") {
                    const scored = [];
                    if (!scope) return [];
                    const teamParts = clean(matchText).split(/\s+vs\s+/i);
                    const homeTokens = clean(teamParts[0] || "").toLowerCase().split(/[^a-z0-9À-ỹ]+/i).filter((v) => v.length >= 4);
                    const awayTokens = clean((teamParts[1] || "").split(" - ")[0]).toLowerCase().split(/[^a-z0-9À-ỹ]+/i).filter((v) => v.length >= 4);
                    scope.querySelectorAll("img").forEach((img, index) => {
                        const context = clean([
                            img.alt, img.title, img.className, img.parentElement?.innerText,
                            img.parentElement?.className, img.parentElement?.parentElement?.innerText,
                            img.parentElement?.parentElement?.className
                        ].join(" ")).slice(0, 500);
                        const lower = context.toLowerCase();
                        let score = 0;
                        if (homeTokens.some((token) => lower.includes(token))) score += 60;
                        else if (awayTokens.some((token) => lower.includes(token))) score += 35;
                        if (/team|club|home|away|doi|đội/.test(lower)) score += 12;
                        if (/logo/.test(lower)) score += 4;
                        if (/avatar|blv|comment|banner|advert|ads|flag|league/.test(lower)) score -= 35;
                        const width = img.naturalWidth || img.width || 0;
                        const height = img.naturalHeight || img.height || 0;
                        if (width && height && Math.abs(width - height) <= Math.max(width, height) * 0.35) score += 5;
                        score -= index * 0.01;

                        const values = [img.currentSrc, img.src, img.getAttribute("src"),
                            img.getAttribute("data-src"), img.getAttribute("data-original"),
                            img.getAttribute("data-lazy-src")];
                        [img.getAttribute("srcset"), img.getAttribute("data-srcset")].filter(Boolean)
                            .forEach((set) => set.split(",").forEach((part) => values.push(part.trim().split(/\s+/)[0])));
                        values.filter(Boolean).forEach((value) => {
                            try { value = new URL(value, location.href).href; } catch (_) {}
                            scored.push({url: value, score, context, source: "home-card"});
                        });
                    });
                    const out = [];
                    const unique = new Set();
                    scored.sort((a, b) => b.score - a.score).forEach((item) => {
                        if (!unique.has(item.url)) { unique.add(item.url); out.push(item); }
                    });
                    return out.slice(0, 20);
                }

                function findContainer(a) {
                    const target = normalizeHref(a.href || a.getAttribute("href") || "");
                    let node = a;
                    for (let depth = 0; node && depth < 9; depth += 1, node = node.parentElement) {
                        const links = Array.from(node.querySelectorAll?.("a[href]") || [])
                            .map((el) => normalizeHref(el.href || el.getAttribute("href") || ""))
                            .filter(isMatchHref);
                        const uniqueLinks = Array.from(new Set(links));
                        const text = clean(node.innerText || node.textContent || "");
                        if (uniqueLinks.length === 1 && uniqueLinks[0] === target && /\bvs\b/i.test(text)) {
                            return node;
                        }
                    }
                    return a.closest(
                        "[data-match-id], [data-event-id], [class*='match-card'], " +
                        "[class*='match-item'], [class*='game-card'], [class*='fixture'], article, li"
                    ) || a.parentElement || a;
                }

                function sportContext(a, container) {
                    const parts = [];
                    const add = (value) => {
                        const fixed = clean(value);
                        if (fixed && fixed.length <= 300 && !parts.includes(fixed)) parts.push(fixed);
                    };
                    const inspect = (node) => {
                        if (!node) return;
                        [
                            node.getAttribute?.("data-sport"),
                            node.getAttribute?.("data-category"),
                            node.getAttribute?.("data-type"),
                            node.getAttribute?.("aria-label"),
                            node.id,
                            node.className
                        ].forEach(add);
                        const heading = node.querySelector?.(
                            ":scope > h1, :scope > h2, :scope > h3, :scope > h4, " +
                            ":scope > [class*='sport-title'], :scope > [class*='category-title']"
                        );
                        add(heading?.innerText || heading?.textContent);
                    };

                    inspect(a);
                    inspect(container);
                    let node = container;
                    for (let depth = 0; node && depth < 6; depth += 1, node = node.parentElement) {
                        inspect(node);
                        let previous = node.previousElementSibling;
                        for (let step = 0; previous && step < 3; step += 1, previous = previous.previousElementSibling) {
                            if (/^H[1-6]$/.test(previous.tagName || "") ||
                                /sport|category|tab|section/i.test(String(previous.className || ""))) {
                                add(previous.innerText || previous.textContent);
                            }
                        }
                    }
                    return parts.join(" | ");
                }

                function addItem(
                    hrefValue,
                    titleValue = "",
                    cardText = "",
                    timeValue = "",
                    logos = [],
                    sportHint = ""
                ) {
                    const href = normalizeHref(hrefValue);
                    if (!isMatchHref(href) || seen.has(href)) return;
                    seen.add(href);
                    const parts = new URL(href).pathname.split("/").filter(Boolean);
                    const fallback = decodeURIComponent(parts[parts.length - 1] || href)
                        .replace(/-vs-/gi, " vs ").replace(/-/g, " ");
                    items.push({
                        url: href,
                        raw_title: clean(titleValue || cardText || fallback),
                        card_text: clean(cardText),
                        raw_time: clean(timeValue || cardText),
                        logo: logos[0]?.url || "",
                        team_logos: logos.slice(0, 12).map((item) => item.url),
                        logo_candidates: logos.slice(0, 20),
                        sport_hint: clean(sportHint),
                    });
                }

                document.querySelectorAll("a[href]").forEach((a) => {
                    const href = a.href || a.getAttribute("href") || "";
                    if (!isMatchHref(href)) return;
                    const container = findContainer(a);
                    const cardText = clean(container?.innerText || a.innerText || "");
                    const sportHint = sportContext(a, container);

                    const timeEl = container?.querySelector(
                        "time, [datetime], [data-time], [data-start], [class*='time'], [class*='kickoff']"
                    );
                    const timeValue = clean([
                        timeEl?.getAttribute("datetime"), timeEl?.getAttribute("data-time"),
                        timeEl?.getAttribute("data-start"), timeEl?.innerText
                    ].filter(Boolean).join(" "));

                    const titleNode = Array.from(container?.querySelectorAll(
                        "h1, h2, h3, [class*='match-title'], [class*='match-name'], [class*='team-name']"
                    ) || []).find((el) => /\bvs\b/i.test(clean(el.innerText || el.textContent)));

                    addItem(
                        href,
                        clean(titleNode?.innerText || titleNode?.textContent || a.innerText || a.title || a.getAttribute("aria-label")),
                        cardText,
                        timeValue,
                        imageCandidates(container, clean(titleNode?.innerText || titleNode?.textContent || cardText)),
                        sportHint
                    );
                });

                const htmlText = document.documentElement?.innerHTML || "";
                const normalizedHtml = htmlText.replace(/\\\//g, "/")
                    .replace(/&amp;/g, "&").replace(/\\u002F/gi, "/");
                const patterns = [
                    /https?:\/\/[^"' <>\n\r]+\/live\/\d+\/[^"' <>\n\r]+/gi,
                    /\/live\/\d+\/[a-z0-9][a-z0-9._~!$&'()*+,;=:@%\/-]*/gi,
                    /https?:\/\/[^"' <>\n\r]+\/(?:truc-tiep|room)\/[^"' <>\n\r]+/gi,
                    /\/(?:truc-tiep|room)\/[^"' <>\n\r]+/gi,
                ];
                for (const pattern of patterns) {
                    (normalizedHtml.match(pattern) || []).forEach((href) => addItem(href));
                }

                const anchors = Array.from(document.querySelectorAll("a[href]"));
                return {
                    items,
                    diagnostics: {
                        final_url: location.href,
                        title: document.title || "",
                        anchor_count: anchors.length,
                        html_length: normalizedHtml.length,
                        sample_hrefs: anchors.slice(0, 20).map((a) => a.href || "")
                    }
                };
            }"""
        )

        links = list(result.get("items") or [])
        initial_logo_usage = Counter(
            item.get("logo", "") for item in links if item.get("logo")
        )
        for item in links:
            if item.get("logo") and initial_logo_usage[item["logo"]] > 1:
                item["logo"] = ""
                # Giữ candidate để trang chi tiết chấm lại, nhưng không ưu tiên logo lặp từ card cha.
                for candidate in item.get("logo_candidates", []) or []:
                    if isinstance(candidate, dict) and initial_logo_usage[candidate.get("url", "")] > 1:
                        candidate["score"] = float(candidate.get("score") or 0) - 80
        for item in links:
            item["sport_group"] = classify_sport(
                item.get("sport_hint", ""),
                item.get("card_text", ""),
                item.get("raw_title", ""),
                item.get("url", ""),
            )
        diagnostics = result.get("diagnostics") or {}
        print(
            "ℹ️ Trang chủ: "
            f"title={diagnostics.get('title', '')!r} | "
            f"anchors={diagnostics.get('anchor_count', 0)} | "
            f"html={diagnostics.get('html_length', 0)} ký tự | "
            f"match_links={len(links)}"
        )

        if links:
            counts = Counter(item.get("sport_group", "Khác") for item in links)
            summary = " | ".join(
                f"{group}={counts[group]}" for group in SPORT_GROUP_ORDER if counts[group]
            )
            print(f"📂 Phân loại link trang chủ: {summary}", flush=True)

        if not links:
            try:
                Path(OUTPUT_HOME_DEBUG_HTML).write_text(await page.content(), encoding="utf-8")
                await page.screenshot(path=OUTPUT_HOME_DEBUG_PNG, full_page=True)
                print(f"⚠️ Đã lưu trang debug: {OUTPUT_HOME_DEBUG_HTML}, {OUTPUT_HOME_DEBUG_PNG}")
            except Exception as debug_exc:
                print(f"⚠️ Không lưu được trang debug: {debug_exc}")
        return links

    except Exception as exc:
        print(f"❌ Không lấy được danh sách trang chủ: {type(exc).__name__}: {exc}")
        return []
    finally:
        await page.close()


def escape_m3u_text(value: str) -> str:
    return re.sub(r"[\r\n]+", " ", value or "").replace('"', "'").strip()


def header_json(user_agent: str, referer: str) -> str:
    values = {"User-Agent": user_agent}
    if referer:
        values["Referer"] = referer
    return json.dumps(values, ensure_ascii=False, separators=(",", ":"))


def escape_pipe_header(value: str) -> str:
    """Mã hóa giá trị protocol-option để URL không vỡ bởi khoảng trắng, &, | hoặc %."""
    return quote(clean_text(value), safe=":/().,;=-_")


def android_stream_url(stream_url: str, user_agent: str, referer: str) -> str:
    """
    Header syntax understood by many Android IPTV players:
      URL|User-Agent=...&Referer=...

    Keep EXTVLCOPT too because TiviMate versions differ in which syntax they honor.
    """
    headers = [f"User-Agent={escape_pipe_header(user_agent)}"]
    if referer:
        headers.append(f"Referer={escape_pipe_header(referer)}")
    return stream_url + "|" + "&".join(headers)


def write_outputs(results: list[dict[str, Any]]) -> tuple[int, int]:
    """
    Tạo 3 playlist:
      - chuoichien_live.m3u: playlist phổ thông, URL nguyên bản + EXTHTTP/EXTVLCOPT.
      - chuoichien_live_pipe.m3u: biến thể Kodi-style URL|Header=Value.
      - chuoichien_live_vlc.m3u: URL nguyên bản + EXTVLCOPT dành riêng VLC.

    Không gắn pipe headers vào playlist mặc định vì nhiều IPTV player Android
    coi phần sau dấu | là một phần URL và báo lỗi phát kênh.
    """
    resolve_duplicate_logos(results)

    universal_lines = ["#EXTM3U"]
    pipe_lines = ["#EXTM3U"]
    vlc_lines = ["#EXTM3U"]

    written_streams: set[str] = set()
    match_keys_with_streams: set[str] = set()
    count_links = 0

    sorted_results = sorted(
        results,
        key=lambda item: (
            SPORT_GROUP_RANK.get(item.get("sport_group", "Khác"), 999),
            item.get("time") or "99:99",
            clean_text(item.get("match_name") or item.get("raw_title") or "").lower(),
        ),
    )

    group_stream_counts: Counter[str] = Counter()

    for result in sorted_results:
        streams = result.get("streams") or [
            {"url": value} for value in (result.get("stream_urls") or [])
        ]
        if not streams:
            continue

        match_name = result.get("match_name") or result.get("raw_title") or "Chuối Chiên TV"
        time_str = result.get("time") or ""
        blv = result.get("blv") or ""
        sport_group = result.get("sport_group") or classify_sport(
            result.get("sport_hint", ""),
            result.get("card_text", ""),
            match_name,
            result.get("url", ""),
        )
        if sport_group not in SPORT_GROUP_RANK:
            sport_group = "Khác"
        # resolve_duplicate_logos() đã chọn logo cuối cùng và loại logo dùng nhầm
        # cho nhiều trận. Không chấm lại ở đây vì có thể vô tình chọn lại logo lỗi.
        logo = result.get("logo", "")

        display_base = f"[{time_str}] {match_name}" if time_str else match_name
        if blv and blv.lower() not in display_base.lower():
            display_base += f" [BLV {blv}]"
        display_base = escape_m3u_text(display_base)
        logo = escape_m3u_text(logo)

        unique_streams = [item for item in streams if item.get("url") not in written_streams]
        if not unique_streams:
            continue

        match_keys_with_streams.add(f"{match_name}|{blv}|{time_str}")
        for index, stream_info in enumerate(unique_streams, start=1):
            stream_url = decode_url_repeatedly(stream_info.get("url", ""))
            if not stream_url:
                continue
            written_streams.add(stream_url)

            display_name = display_base
            quality = normalize_quality_hint(stream_info.get("quality", ""))
            if len(unique_streams) > 1 and not quality:
                display_name += f" (Luồng {index})"

            referer = normalize_playback_referer(
                stream_info.get("referer") or PLAYER_ORIGIN_FALLBACK + "/"
            )
            user_agent = clean_text(stream_info.get("user_agent") or UA)
            kind = stream_kind(stream_url, stream_info.get("content_type", ""))
            if kind:
                suffix = f"{quality} {kind.upper()}" if quality else kind.upper()
                display_name += f" [{suffix}]"

            channel_id = channel_id_for(result, stream_url, index)
            attributes = (
                f'tvg-id="{escape_m3u_text(channel_id)}" '
                f'tvg-name="{escape_m3u_text(display_base)}" '
                f'group-title="{escape_m3u_text(sport_group)}"'
            )
            if logo:
                attributes += f' tvg-logo="{logo}"'
            extinf = f"#EXTINF:-1 {attributes},{display_name}"

            universal_lines.extend([
                extinf,
                f"#EXTVLCOPT:http-referrer={referer}",
                f"#EXTVLCOPT:http-user-agent={user_agent}",
                "#EXTVLCOPT:http-reconnect=true",
                f"#EXTHTTP:{header_json(user_agent, referer)}",
                stream_url,
            ])

            pipe_lines.extend([
                extinf,
                f"#EXTVLCOPT:http-referrer={referer}",
                f"#EXTVLCOPT:http-user-agent={user_agent}",
                "#EXTVLCOPT:http-reconnect=true",
                f"#EXTHTTP:{header_json(user_agent, referer)}",
                android_stream_url(stream_url, user_agent, referer),
            ])

            vlc_lines.extend([
                extinf,
                f"#EXTVLCOPT:http-referrer={referer}",
                f"#EXTVLCOPT:http-user-agent={user_agent}",
                "#EXTVLCOPT:http-reconnect=true",
                stream_url,
            ])

            group_stream_counts[sport_group] += 1
            count_links += 1

    Path(OUTPUT_DEBUG).write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    output_sets = (
        (Path(OUTPUT_M3U), universal_lines, "phổ thông"),
        (Path(OUTPUT_PIPE_M3U), pipe_lines, "pipe/Kodi"),
        (Path(OUTPUT_VLC_M3U), vlc_lines, "VLC"),
    )

    if count_links:
        for path, lines, _label in output_sets:
            path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    else:
        for path, _lines, label in output_sets:
            if path.exists():
                print(f"⚠️ Không có link mới; giữ nguyên playlist {label}: {path.resolve()}")
            else:
                path.write_text("#EXTM3U\n", encoding="utf-8")
                print(f"⚠️ Đã tạo playlist {label} rỗng: {path.resolve()}")

    if count_links:
        m3u8_count = sum(
            1 for line in vlc_lines if line.startswith("http") and stream_kind(line) == "m3u8"
        )
        flv_count = sum(
            1 for line in vlc_lines if line.startswith("http") and stream_kind(line) == "flv"
        )
        print(f"📊 Playlist: M3U8={m3u8_count} | FLV={flv_count}")
        group_summary = " | ".join(
            f"{group}={group_stream_counts[group]}"
            for group in SPORT_GROUP_ORDER if group_stream_counts[group]
        )
        if group_summary:
            print(f"📂 Thư mục playlist: {group_summary}")
        print(f"📺 Mặc định Android/IPTV: {Path(OUTPUT_M3U).resolve()}")
        print(f"📺 Pipe/Kodi tùy chọn: {Path(OUTPUT_PIPE_M3U).resolve()}")
        print(f"📺 VLC: {Path(OUTPUT_VLC_M3U).resolve()}")

    return len(match_keys_with_streams), count_links


async def progress_heartbeat(tasks: list[asyncio.Task[Any]], total: int) -> None:
    """In tiến trình đều đặn để GitHub Actions không đứng im trong lúc các tab đang chờ."""
    started = time.monotonic()
    try:
        while True:
            await asyncio.sleep(5)
            completed = sum(task.done() for task in tasks)
            if completed >= total:
                return
            active = min(CONCURRENCY_LIMIT, total - completed)
            waiting = max(0, total - completed - active)
            elapsed = int(time.monotonic() - started)
            print(
                f"⏳ Tiến trình realtime: xong {completed}/{total} | "
                f"đang/chờ tối đa {active}/{waiting} | đã chạy {elapsed}s",
                flush=True,
            )
    except asyncio.CancelledError:
        return


async def main() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(line_buffering=True, write_through=True)
        except Exception:
            pass

    print(f"🥷 KHỞI ĐỘNG CHUỐI CHIÊN STREAM SCANNER - {SCANNER_VERSION}", flush=True)
    print(
        "ℹ️ Test riêng một trận:\n"
        '   python main.py "https://live03.chuoichientv.me/live/1528034/ordabasy-vs-yelimay-semey?blv=angao"'
    )
    print(
        f"ℹ️ Chế độ quét: {'FULL toàn bộ thời gian' if FULL_SCAN else 'dừng sớm'} | "
        f"định dạng={','.join(STREAM_EXTENSIONS)} | chờ mỗi trận={STREAM_WAIT_SECONDS}s"
    )

    direct_urls = [
        arg.strip() for arg in sys.argv[1:]
        if arg.strip().startswith(("http://", "https://"))
    ]

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(
            headless=HEADLESS,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--mute-audio",
                "--autoplay-policy=no-user-gesture-required",
                "--disable-dev-shm-usage",
            ],
        )
        context = await browser.new_context(
            viewport={"width": 1366, "height": 768},
            user_agent=UA,
            locale="vi-VN",
            timezone_id="Asia/Ho_Chi_Minh",
            ignore_https_errors=True,
            service_workers="block",
            extra_http_headers={
                "Accept-Language": "vi-VN,vi;q=0.9,en-US;q=0.8,en;q=0.7"
            },
        )

        if direct_urls:
            links = []
            for url in direct_urls:
                match_name, _, _ = derive_match_info(url)
                links.append({
                    "url": url,
                    "raw_title": match_name,
                    "raw_time": "",
                    "logo": "",
                    "team_logos": [],
                    "logo_candidates": [],
                    "sport_hint": "",
                    "sport_group": classify_sport(match_name, url),
                })
            print(f"✅ Chế độ test trực tiếp: {len(links)} URL.")
        else:
            links = await collect_home_links(context)

        if not links:
            print("❌ Không tìm thấy link trận/phòng nào.")
            write_outputs([])
            await context.close()
            await browser.close()
            return

        print(
            f"✅ Tìm thấy {len(links)} link trận/phòng. "
            f"Bắt đầu quét tối đa {CONCURRENCY_LIMIT} trang cùng lúc..."
        )
        semaphore = asyncio.Semaphore(CONCURRENCY_LIMIT)
        total_links = len(links)
        tasks: list[asyncio.Task[dict[str, Any]]] = []
        for index, match in enumerate(links, start=1):
            match["_scan_index"] = index
            match["_scan_total"] = total_links
            tasks.append(asyncio.create_task(fetch_stream(context, match, semaphore)))

        heartbeat = asyncio.create_task(progress_heartbeat(tasks, total_links))
        results: list[dict[str, Any]] = []
        completed = 0
        try:
            for future in asyncio.as_completed(tasks):
                result = await future
                results.append(result)
                completed += 1
                found = len(result.get("streams") or [])
                print(
                    f"📈 Hoàn thành {completed}/{total_links}: "
                    f"[{result.get('sport_group', 'Khác')}] "
                    f"{result.get('match_name', '')[:70]} | stream={found}",
                    flush=True,
                )
        finally:
            heartbeat.cancel()
            await asyncio.gather(heartbeat, return_exceptions=True)

        count_matches, count_links = write_outputs(results)

        if count_links:
            print(f"\n🎉 HOÀN TẤT: lấy được {count_links} link từ {count_matches} trận/phòng.")
            print(f"📺 Playlist mặc định: {Path(OUTPUT_M3U).resolve()}")
            print(f"📺 Playlist pipe/Kodi: {Path(OUTPUT_PIPE_M3U).resolve()}")
            print(f"📺 Playlist VLC: {Path(OUTPUT_VLC_M3U).resolve()}")
        else:
            print("\n❌ Không bắt được m3u8/flv nào.")
        print(f"🧾 Nhật ký chi tiết: {Path(OUTPUT_DEBUG).resolve()}")

        await context.close()
        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
