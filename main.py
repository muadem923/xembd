import asyncio
import html
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

from playwright.async_api import BrowserContext, Page, Route, async_playwright


# =========================
# CẤU HÌNH
# =========================
TARGET_URL = "https://live03.chuoichientv.me/"
OUTPUT_M3U = "chuoichien_live.m3u"
OUTPUT_DEBUG = "chuoichien_debug.json"
OUTPUT_HOME_DEBUG_HTML = "chuoichien_home_debug.html"
OUTPUT_HOME_DEBUG_PNG = "chuoichien_home_debug.png"


def read_env_int(name: str, default: int, minimum: int, maximum: int) -> int:
    """Đọc số nguyên từ biến môi trường và ép vào khoảng an toàn."""
    raw = os.getenv(name, "").strip()
    if not raw:
        return default

    try:
        value = int(raw)
    except ValueError:
        print(f"⚠️ {name}={raw!r} không hợp lệ; dùng mặc định {default}.")
        return default

    return max(minimum, min(value, maximum))


# Các giá trị này có thể chỉnh trực tiếp trong GitHub Actions.
CONCURRENCY_LIMIT = read_env_int(
    "SOCOLIVE_MATCH_CONCURRENCY", 8, minimum=1, maximum=16
)
HOME_WAIT_MS = read_env_int(
    "SOCOLIVE_HOME_WAIT_MS", 5000, minimum=1000, maximum=30000
)
STREAM_WAIT_SECONDS = read_env_int(
    "SOCOLIVE_ROOM_WAIT_SECONDS", 20, minimum=3, maximum=120
)
EXTRA_WAIT_AFTER_FIRST_STREAM = 2.0

HEADLESS = True

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/150.0.0.0 Safari/537.36"
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


def decode_url_repeatedly(value: str, rounds: int = 3) -> str:
    """Giải mã HTML + percent-encoding nhiều lớp nhưng không lặp vô hạn."""
    current = html.unescape(value or "").replace("\\/", "/").strip()

    for _ in range(rounds):
        decoded = unquote(current)
        if decoded == current:
            break
        current = decoded

    return current.strip()


def is_direct_stream_url(url: str) -> bool:
    """Chỉ nhận URL mà chính path của nó là m3u8/flv, tránh nhận nhầm URL embed."""
    if not url:
        return False

    clean = decode_url_repeatedly(url)
    parsed = urlparse(clean)
    lower_path = parsed.path.lower()
    lower_url = clean.lower()

    if parsed.scheme not in {"http", "https"}:
        return False

    if not any(ext in lower_path for ext in STREAM_EXTENSIONS):
        return False

    return not any(marker in lower_url for marker in AD_MARKERS)


def extract_stream_urls(raw_url: str) -> list[str]:
    """
    Trích URL luồng thật từ:
      - request trực tiếp tới .m3u8/.flv
      - URL embed có query streamUrl/file/src/url đã percent-encode
      - chuỗi có URL lồng nhiều lớp

    Ví dụ:
      https://live.chuoichien.tv/embed/?streamUrl=https%3A%2F%2Fcdn%2Flive.flv
      -> https://cdn/live.flv
    """
    if not raw_url:
        return []

    pending = [raw_url]
    seen_values: set[str] = set()
    found: list[str] = []

    nested_param_names = {
        "streamurl",
        "stream_url",
        "stream",
        "url",
        "src",
        "file",
        "source",
        "video",
        "hls",
        "flv",
        "playurl",
        "play_url",
    }

    while pending and len(seen_values) < 40:
        value = decode_url_repeatedly(pending.pop(0))
        if not value or value in seen_values:
            continue
        seen_values.add(value)

        if is_direct_stream_url(value):
            if value not in found:
                found.append(value)
            continue

        try:
            parsed = urlparse(value)
            query = parse_qs(parsed.query, keep_blank_values=False)
        except Exception:
            query = {}

        for key, values in query.items():
            if key.lower() not in nested_param_names:
                continue
            for nested in values:
                decoded = decode_url_repeatedly(nested)
                if decoded.startswith(("http://", "https://")):
                    pending.append(decoded)

        # Fallback cho URL lồng trong text/HTML nhưng không nằm ở query quen thuộc.
        decoded_text = decode_url_repeatedly(value)
        for match in re.findall(
            r"https?://[^\s\"'<>]+?(?:\.m3u8|\.flv)(?:\?[^\s\"'<>]*)?",
            decoded_text,
            flags=re.IGNORECASE,
        ):
            pending.append(match.rstrip("),];"))

    return found


def is_stream_url(url: str) -> bool:
    """Giữ tương thích với code cũ."""
    return bool(extract_stream_urls(url))


def normalize_stream_url(url: str) -> str:
    return decode_url_repeatedly(url)

def derive_match_info(url: str, raw_title: str = "") -> tuple[str, str, str]:
    """
    Trả về:
      - tên trận
      - giờ trận
      - tên BLV suy đoán
    """
    parsed = urlparse(url)
    query = parse_qs(parsed.query)

    raw_title = re.sub(r"\s+", " ", raw_title or "").strip()
    raw_lower = raw_title.lower()

    has_match_title = " vs " in f" {raw_lower} "
    blv_name = ""

    if "blv" in query and raw_title and not has_match_title:
        blv_name = raw_title

    if has_match_title:
        match_name = raw_title
    else:
        slug = unquote(parsed.path.rstrip("/").split("/")[-1])
        slug = re.sub(r"-\d{2}-\d{2}-\d{4}-\d{4}$", "", slug)
        slug = slug.replace("-vs-", " vs ")
        slug = slug.replace("-", " ")
        match_name = re.sub(r"\s+", " ", slug).strip()

    match_name = re.sub(
        r"(?i)\b(xem ngay|trực tiếp|hot|live|bóng đá|sắp diễn ra|socolive)\b",
        "",
        match_name,
    )
    match_name = re.sub(r"\s+", " ", match_name).strip(" -")

    time_match = re.search(r"-(\d{2})(\d{2})/?$", parsed.path)
    time_str = f"{time_match.group(1)}:{time_match.group(2)}" if time_match else ""

    return match_name or raw_title or url, time_str, blv_name


async def install_route_filter(page: Page, homepage: bool = False) -> None:
    """
    Trang trận KHÔNG chặn media/manifest/other.
    Chỉ chặn ảnh và font để giảm tải.
    Trang chủ có thể chặn media vì chỉ cần lấy danh sách link.
    """
    blocked_types = {"image", "font"}
    if homepage:
        blocked_types.add("media")

    async def route_handler(route: Route) -> None:
        if route.request.resource_type in blocked_types:
            await route.abort()
        else:
            await route.continue_()

    await page.route("**/*", route_handler)


async def collect_dom_stream_candidates(page: Page) -> list[str]:
    """
    Bắt URL từ mọi frame, gồm video/source và iframe embed.
    Iframe rất quan trọng vì Chuối Chiên hiện nhét streamUrl đã encode trong src.
    """
    candidates: set[str] = set()

    for frame in page.frames:
        try:
            frame_candidates = await frame.evaluate(
                r"""() => {
                    const out = new Set();

                    try {
                        for (const entry of performance.getEntriesByType("resource")) {
                            if (entry && entry.name) out.add(entry.name);
                        }
                    } catch (_) {}

                    document.querySelectorAll(
                        "video, source, iframe, embed, object, " +
                        "[data-stream], [data-stream-url], [data-url], [data-src]"
                    ).forEach((el) => {
                        const values = [
                            el.src,
                            el.currentSrc,
                            el.data,
                            el.getAttribute("src"),
                            el.getAttribute("data"),
                            el.getAttribute("data-src"),
                            el.getAttribute("data-url"),
                            el.getAttribute("data-stream"),
                            el.getAttribute("data-stream-url"),
                            el.getAttribute("data-file"),
                        ];
                        values.forEach((value) => {
                            if (value) out.add(value);
                        });
                    });

                    const htmlText = document.documentElement
                        ? document.documentElement.innerHTML
                        : "";

                    const normalizedHtml = htmlText
                        .replace(/\\\//g, "/")
                        .replace(/&amp;/g, "&");

                    const absoluteMatches = normalizedHtml.match(
                        /https?:\/\/[^"' <>\n\r]+?(?:\.m3u8|\.flv)(?:\?[^"' <>\n\r]*)?/gi
                    ) || [];
                    absoluteMatches.forEach((value) => out.add(value));

                    // Bắt cả URL embed chứa streamUrl=https%3A%2F%2F...flv.
                    const embedMatches = normalizedHtml.match(
                        /https?:\/\/[^"' <>\n\r]+?(?:streamUrl|stream_url|file|src|url)=[^"' <>\n\r]+/gi
                    ) || [];
                    embedMatches.forEach((value) => out.add(value));

                    return Array.from(out);
                }"""
            )
            candidates.update(str(item) for item in frame_candidates if item)
        except Exception:
            continue

    return sorted(candidates)


async def stimulate_player(page: Page) -> None:
    """Thử kích hoạt player/autoplay mà không làm hỏng trang."""
    for selector in PLAY_SELECTORS:
        try:
            locator = page.locator(selector)
            if await locator.count():
                await locator.first.click(timeout=700, force=True)
        except Exception:
            pass

    try:
        await page.evaluate(
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


async def fetch_stream(
    context: BrowserContext,
    match: dict[str, Any],
    sem: asyncio.Semaphore,
) -> dict[str, Any]:
    async with sem:
        match_name, time_str, blv_from_link = derive_match_info(
            match["url"], match.get("raw_title", "")
        )
        match["match_name"] = match_name
        match["time"] = time_str
        match["blv"] = blv_from_link
        match["stream_urls"] = []
        match["errors"] = []

        label = match_name
        if blv_from_link:
            label += f" | BLV {blv_from_link}"

        print(f"-> Đang quét: {label[:90]}")

        page = await context.new_page()
        await install_route_filter(page, homepage=False)

        stream_urls: set[str] = set()
        first_stream_at: float | None = None

        def capture_url(url: str, source: str) -> None:
            nonlocal first_stream_at

            for stream_url in extract_stream_urls(url):
                normalized = normalize_stream_url(stream_url)
                if normalized in stream_urls:
                    continue

                stream_urls.add(normalized)
                if first_stream_at is None:
                    first_stream_at = time.monotonic()
                print(f"   🎯 [{source}] {normalized}")

        def handle_request(request: Any) -> None:
            capture_url(request.url, f"request/{request.resource_type}")

        def handle_response(response: Any) -> None:
            capture_url(response.url, "response")

        def handle_page_error(error: Any) -> None:
            message = f"JS: {error}"
            match["errors"].append(message)

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
            await page.goto(
                match["url"],
                wait_until="domcontentloaded",
                timeout=30000,
            )

            # Thử đọc tên BLV thật trên trang.
            try:
                dom_blv = await page.evaluate(
                    """() => {
                        const selectors = [
                            ".blv-name",
                            ".player-info-name",
                            ".name-blv",
                            ".chat-item-name",
                            "[class*='blv'] [class*='name']",
                            "[class*='commentator'] [class*='name']"
                        ];

                        for (const selector of selectors) {
                            const el = document.querySelector(selector);
                            if (el && el.innerText && el.innerText.trim()) {
                                return el.innerText.trim();
                            }
                        }
                        return "";
                    }"""
                )
                if dom_blv:
                    match["blv"] = re.sub(r"\s+", " ", dom_blv).strip()
            except Exception:
                pass

            # Logo chỉ dùng để hiển thị; đuôi JPG không còn bị coi là phòng rác.
            if not match.get("logo"):
                try:
                    room_logo = await page.evaluate(
                        """() => {
                            const imgs = document.querySelectorAll(
                                ".team-logo img, .match-info img, .logo img, img"
                            );

                            for (const img of imgs) {
                                const src =
                                    img.getAttribute("data-src") ||
                                    img.getAttribute("data-original") ||
                                    img.getAttribute("src") ||
                                    img.src ||
                                    "";

                                if (
                                    src &&
                                    !src.includes("base64") &&
                                    !src.includes("data:image") &&
                                    !src.includes("icon") &&
                                    !src.includes(".svg") &&
                                    !src.includes(".gif")
                                ) {
                                    return src;
                                }
                            }
                            return "";
                        }"""
                    )
                    if room_logo:
                        match["logo"] = room_logo
                except Exception:
                    pass

            deadline = time.monotonic() + STREAM_WAIT_SECONDS

            while time.monotonic() < deadline:
                await stimulate_player(page)

                for candidate in await collect_dom_stream_candidates(page):
                    capture_url(candidate, "dom/performance")

                if (
                    first_stream_at is not None
                    and time.monotonic() - first_stream_at
                    >= EXTRA_WAIT_AFTER_FIRST_STREAM
                ):
                    break

                await page.wait_for_timeout(1000)

        except Exception as exc:
            error_text = f"{type(exc).__name__}: {exc}"
            match["errors"].append(error_text)
            print(f"   ❌ {label[:70]} | {error_text}")
        finally:
            # Quét lần cuối trước khi đóng trang.
            try:
                for candidate in await collect_dom_stream_candidates(page):
                    capture_url(candidate, "final-scan")
            except Exception:
                pass

            await page.close()

        match["stream_urls"] = sorted(stream_urls)

        if not stream_urls:
            print(f"   ⚠️ Không thấy m3u8/flv: {label[:85]}")

        return match


async def collect_home_links(context: BrowserContext) -> list[dict[str, str]]:
    page = await context.new_page()
    await install_route_filter(page, homepage=True)

    print(f"👉 Đang mở trang chủ: {TARGET_URL}")

    try:
        await page.goto(
            TARGET_URL,
            wait_until="domcontentloaded",
            timeout=30000,
        )

        await page.wait_for_timeout(HOME_WAIT_MS)

        # Cuộn nhẹ để các danh sách lazy-load được render.
        for _ in range(5):
            await page.evaluate("window.scrollBy(0, Math.max(700, window.innerHeight));")
            await page.wait_for_timeout(600)

        result = await page.evaluate(
            r"""() => {
                const items = [];
                const seen = new Set();

                function normalizeHref(value) {
                    try {
                        return new URL(value, location.href).href;
                    } catch (_) {
                        return "";
                    }
                }

                function isMatchHref(value) {
                    const href = normalizeHref(value);
                    if (!href) return false;

                    try {
                        const path = new URL(href).pathname;
                        return (
                            /^\/live\/\d+(?:\/|$)/i.test(path) ||
                            path.includes("/truc-tiep/") ||
                            path.includes("/room/")
                        );
                    } catch (_) {
                        return false;
                    }
                }

                function addItem(hrefValue, titleValue = "", logoValue = "") {
                    const href = normalizeHref(hrefValue);
                    if (!isMatchHref(href) || seen.has(href)) return;
                    seen.add(href);

                    const fallbackTitle = (() => {
                        try {
                            const parts = new URL(href).pathname.split("/").filter(Boolean);
                            return decodeURIComponent(parts[parts.length - 1] || href)
                                .replace(/-vs-/gi, " vs ")
                                .replace(/-/g, " ");
                        } catch (_) {
                            return href;
                        }
                    })();

                    items.push({
                        url: href,
                        raw_title: String(titleValue || fallbackTitle)
                            .replace(/\s+/g, " ")
                            .trim(),
                        logo: String(logoValue || "").trim(),
                    });
                }

                document.querySelectorAll("a[href]").forEach((a) => {
                    const href = a.href || a.getAttribute("href") || "";
                    if (!isMatchHref(href)) return;

                    const text = (a.innerText || "").replace(/\s+/g, " ").trim();
                    const lowerText = text.toLowerCase();

                    if (
                        lowerText.includes("bóng rổ") ||
                        lowerText.includes("tennis") ||
                        lowerText.includes("cầu lông")
                    ) {
                        return;
                    }

                    let logo = "";
                    const container =
                        a.closest("div[class*='item']") ||
                        a.closest("article") ||
                        a.closest("li") ||
                        a.closest("div");

                    if (container) {
                        const imgs = container.querySelectorAll("img");
                        for (const img of imgs) {
                            const src =
                                img.getAttribute("data-src") ||
                                img.getAttribute("data-original") ||
                                img.getAttribute("src") ||
                                img.src ||
                                "";

                            if (
                                src &&
                                !src.includes("data:image") &&
                                !src.includes("base64") &&
                                !src.includes("icon") &&
                                !src.includes("gif")
                            ) {
                                logo = src;
                                break;
                            }
                        }
                    }

                    addItem(
                        href,
                        a.title || a.getAttribute("aria-label") || text || href,
                        logo
                    );
                });

                // Fallback cho React/Next.js: link có thể nằm trong JSON/script,
                // chưa được render thành thẻ <a> khi chạy headless trên GitHub.
                const htmlText = document.documentElement
                    ? document.documentElement.innerHTML
                    : "";
                const normalizedHtml = htmlText
                    .replace(/\\\//g, "/")
                    .replace(/&amp;/g, "&")
                    .replace(/\\u002F/gi, "/");

                const patterns = [
                    /https?:\/\/[^"' <>\n\r]+\/live\/\d+\/[^"' <>\n\r]+/gi,
                    /\/live\/\d+\/[a-z0-9][a-z0-9._~!$&'()*+,;=:@%\/-]*/gi,
                    /https?:\/\/[^"' <>\n\r]+\/(?:truc-tiep|room)\/[^"' <>\n\r]+/gi,
                    /\/(?:truc-tiep|room)\/[^"' <>\n\r]+/gi,
                ];

                for (const pattern of patterns) {
                    const matches = normalizedHtml.match(pattern) || [];
                    matches.forEach((href) => addItem(href));
                }

                const allAnchors = Array.from(document.querySelectorAll("a[href]"));
                return {
                    items,
                    diagnostics: {
                        final_url: location.href,
                        title: document.title || "",
                        anchor_count: allAnchors.length,
                        html_length: normalizedHtml.length,
                        sample_hrefs: allAnchors
                            .slice(0, 20)
                            .map((a) => a.href || a.getAttribute("href") || ""),
                    },
                };
            }"""
        )

        links = list(result.get("items") or [])
        diagnostics = result.get("diagnostics") or {}
        print(
            "ℹ️ Trang chủ: "
            f"title={diagnostics.get('title', '')!r} | "
            f"anchors={diagnostics.get('anchor_count', 0)} | "
            f"html={diagnostics.get('html_length', 0)} ký tự | "
            f"match_links={len(links)}"
        )

        if not links:
            try:
                Path(OUTPUT_HOME_DEBUG_HTML).write_text(
                    await page.content(),
                    encoding="utf-8",
                )
                await page.screenshot(
                    path=OUTPUT_HOME_DEBUG_PNG,
                    full_page=True,
                )
                print(
                    "⚠️ Đã lưu trang debug: "
                    f"{OUTPUT_HOME_DEBUG_HTML}, {OUTPUT_HOME_DEBUG_PNG}"
                )
                samples = diagnostics.get("sample_hrefs") or []
                if samples:
                    print("ℹ️ Một số href nhìn thấy trên trang:")
                    for href in samples[:10]:
                        print(f"   - {href}")
            except Exception as debug_exc:
                print(f"⚠️ Không lưu được trang debug: {debug_exc}")

        return links

    except Exception as exc:
        print(f"❌ Không lấy được danh sách trang chủ: {type(exc).__name__}: {exc}")
        return []
    finally:
        await page.close()


def normalize_logo(logo: str) -> str:
    logo = (logo or "").strip()

    if not logo:
        return TARGET_URL.rstrip("/") + "/logo.png"

    if logo.startswith("//"):
        return "https:" + logo

    if logo.startswith("/"):
        return TARGET_URL.rstrip("/") + logo

    return logo


def escape_m3u_text(value: str) -> str:
    return re.sub(r"[\r\n]+", " ", value or "").replace('"', "'").strip()


def write_outputs(results: list[dict[str, Any]]) -> tuple[int, int]:
    playlist_lines = ["#EXTM3U"]
    written_streams: set[str] = set()
    match_keys_with_streams: set[str] = set()

    referer_origin = TARGET_URL.rstrip("/")
    count_links = 0

    for result in results:
        streams = result.get("stream_urls") or []
        if not streams:
            continue

        match_name = result.get("match_name") or result.get("raw_title") or "Socolive"
        time_str = result.get("time") or ""
        blv = result.get("blv") or ""
        logo = normalize_logo(result.get("logo", ""))
        page_referer = result.get("url") or TARGET_URL

        display_base = f"[{time_str}] {match_name}" if time_str else match_name
        if blv and blv.lower() not in display_base.lower():
            display_base += f" [BLV {blv}]"

        display_base = escape_m3u_text(display_base)
        logo = escape_m3u_text(logo)

        unique_streams = [
            stream for stream in streams
            if stream not in written_streams
        ]

        if not unique_streams:
            continue

        match_key = f"{match_name}|{blv}|{time_str}"
        match_keys_with_streams.add(match_key)

        for index, stream in enumerate(unique_streams, start=1):
            written_streams.add(stream)

            server_tag = (
                f" (Luồng {index})"
                if len(unique_streams) > 1
                else ""
            )
            display_name = display_base + server_tag

            fixed_url = (
                f"{stream}"
                f"|Referer={page_referer}"
                f"&Origin={referer_origin}"
                f"&User-Agent={UA}"
            )

            playlist_lines.append(
                f'#EXTINF:-1 group-title="Socolive" tvg-logo="{logo}",'
                f'{display_name}'
            )
            playlist_lines.append(
                f"#EXTVLCOPT:http-referrer={page_referer}"
            )
            playlist_lines.append(
                f"#EXTVLCOPT:http-referer={page_referer}"
            )
            playlist_lines.append(
                f"#EXTVLCOPT:http-origin={referer_origin}"
            )
            playlist_lines.append(
                f"#EXTVLCOPT:http-user-agent={UA}"
            )
            playlist_lines.append(fixed_url)

            count_links += 1

    Path(OUTPUT_DEBUG).write_text(
        json.dumps(results, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    playlist_path = Path(OUTPUT_M3U)

    if count_links:
        playlist_path.write_text(
            "\n".join(playlist_lines) + "\n",
            encoding="utf-8",
        )
    elif playlist_path.exists():
        # Lần quét lỗi/rỗng không được xóa playlist tốt của lần chạy trước.
        print(
            f"⚠️ Không có link mới; giữ nguyên playlist cũ: "
            f"{playlist_path.resolve()}"
        )
    else:
        # Repository chạy lần đầu vẫn cần một file hợp lệ để git add không lỗi 128.
        playlist_path.write_text("#EXTM3U\n", encoding="utf-8")
        print(
            f"⚠️ Chưa có playlist cũ; đã tạo playlist rỗng hợp lệ: "
            f"{playlist_path.resolve()}"
        )

    return len(match_keys_with_streams), count_links


async def main() -> None:
    print("🥷 KHỞI ĐỘNG SOCOLIVE STREAM SCANNER - BẢN FIX")
    print(
        "ℹ️ Có thể test riêng một trận bằng lệnh:\n"
        '   python main.py "https://live03.chuoichientv.me/live/1524177/capalaba-vs-holland-park-hawks"'
    )

    direct_urls = [
        arg.strip()
        for arg in sys.argv[1:]
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
                links.append(
                    {
                        "url": url,
                        "raw_title": match_name,
                        "logo": "",
                    }
                )
            print(f"✅ Chế độ test trực tiếp: {len(links)} URL.")
        else:
            links = await collect_home_links(context)

        if not links:
            print("❌ Không tìm thấy link trận/phòng nào.")
            # Vẫn tạo debug và bảo đảm playlist tồn tại; không ghi đè playlist cũ.
            write_outputs([])
            await context.close()
            await browser.close()
            return

        print(
            f"✅ Tìm thấy {len(links)} link trận/phòng. "
            f"Bắt đầu quét tối đa {CONCURRENCY_LIMIT} trang cùng lúc..."
        )

        semaphore = asyncio.Semaphore(CONCURRENCY_LIMIT)
        tasks = [
            fetch_stream(context, match, semaphore)
            for match in links
        ]
        results = await asyncio.gather(*tasks)

        count_matches, count_links = write_outputs(results)

        if count_links:
            print(
                f"\n🎉 HOÀN TẤT: lấy được {count_links} link "
                f"từ {count_matches} trận/phòng."
            )
            print(f"📺 Playlist: {Path(OUTPUT_M3U).resolve()}")
        else:
            print("\n❌ Không bắt được m3u8/flv nào.")

        print(f"🧾 Nhật ký chi tiết: {Path(OUTPUT_DEBUG).resolve()}")

        await context.close()
        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
