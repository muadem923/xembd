from curl_cffi import requests
from bs4 import BeautifulSoup
import re
import codecs
from datetime import datetime

# --- CẤU HÌNH ---
BITLY_URL = "https://bit.ly/bunchatv"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

# Danh sách đen: Siết chặt hơn để sút bay mấy thằng Admin web đăng nhầm Tennis vào Bóng đá
BLACKLIST = [
    "ufc", "mma", "tennis", "quần vợt", "bóng rổ", "cầu lông", "bóng chuyền", "esport",
    "atp", "wta", "itf", "bóng bàn", "đua xe", "billiard", "wwe", "taro daniel", "brancaccio"
]

def expand_url(short_url):
    try:
        res = requests.get(short_url, impersonate="chrome110", allow_redirects=True, timeout=15)
        return res.url if res.url.endswith('/') else res.url + '/'
    except: return "https://bunchatv4.net/"

def get_match_time(url):
    try:
        m = re.search(r'-(\d{4})-(\d{2})-(\d{2})-(\d{4})', url)
        if m:
            t = f"{m.group(1)[:2]}:{m.group(1)[2:]}"
            d = f"{m.group(3)}/{m.group(2)}"
            sort_val = datetime.strptime(f"{m.group(4)}-{m.group(2)}-{m.group(3)} {t}", "%Y-%m-%d %H:%M")
            return f"[{t} {d}]", sort_val
    except: pass
    return "", datetime.now()

def get_clean_name_from_url(url):
    """Tuyệt chiêu mới: Bóc tên trận từ ĐƯỜNG LINK, đảm bảo sạch 100% không rác HTML"""
    try:
        slug = url.split('/')[-2] if url.endswith('/') else url.split('/')[-1]
        # Xóa đoạn ngày tháng (-2100-10-05-2026)
        slug = re.sub(r'-\d{3,4}-\d{2}-\d{2}-\d{4}.*', '', slug)
        name = slug.replace('-', ' ').title().replace(' Vs ', ' vs ')
        return name
    except: return "Trận Đấu"

def extract_streams(url):
    try:
        res = requests.get(url, impersonate="chrome110", timeout=15)
        html = res.text
        soup = BeautifulSoup(html, 'html.parser')
        streams = []
        seen = set()

        # 1. Tìm tên BLV chung của trận đấu bảo mật trong thẻ <title> của trang web
        match_blv = ""
        title_tag = soup.find('title')
        if title_tag:
            m = re.search(r'(?i)(BLV\s+[^-\|CƯỢC]+)', title_tag.text)
            if m: match_blv = m.group(1).strip()

        # 2. Bẫy JSON ngầm
        blv_map = {}
        for m in re.finditer(r'["\'](?:name|title|blv)["\']\s*:\s*["\']([^"\']+)["\'].*?["\'](?:url|src|link)["\']\s*:\s*["\']([^"\']+)["\']', html, re.I):
            u = m.group(2).replace('\\/', '/').replace('\\', '')
            blv_map[u] = m.group(1)
        for m in re.finditer(r'["\'](?:url|src|link)["\']\s*:\s*["\']([^"\']+)["\'].*?["\'](?:name|title|blv)["\']\s*:\s*["\']([^"\']+)["\']', html, re.I):
            u = m.group(1).replace('\\/', '/').replace('\\', '')
            blv_map[u] = m.group(2)

        def add_stream(link, fallback_name):
            link = link.replace('\\', '').replace('u0026', '&').strip()
            if link not in seen and '.m3u8' in link:
                # Ưu tiên lấy tên BLV bắt được từ thẻ Title nếu JSON lỗi
                final_name = blv_map.get(link, match_blv if match_blv else fallback_name)
                final_name = re.sub(r'(?i)(CƯỢC NGAY|Live|Click).*', '', final_name).strip()
                try: final_name = codecs.decode(final_name.encode(), 'unicode_escape')
                except: pass
                
                streams.append({'url': link, 'name': final_name})
                seen.add(link)

        for tag in soup.find_all(['button', 'a', 'span', 'li']):
            d_link = tag.get('data-link') or tag.get('data-src') or tag.get('data-url')
            if d_link:
                if d_link.startswith('//'): d_link = 'https:' + d_link
                btn_name = tag.text.strip()
                if '.m3u8' not in d_link:
                    try:
                        s_res = requests.get(d_link, impersonate="chrome110", timeout=5)
                        for l in re.findall(r'(https?://[^\s"\'<>]*\.m3u8[^\s"\'<>]*)', s_res.text):
                            add_stream(l, btn_name)
                    except: pass
                else: add_stream(d_link, btn_name)

        for l in re.findall(r'(https?://[^\s"\'<>]*\.m3u8[^\s"\'<>]*)', html):
            add_stream(l, "")
            
        return streams
    except: return []

def main():
    current_home_url = expand_url(BITLY_URL)
    base_domain = "/".join(current_home_url.split('/')[:3])
    
    print("🚀 Đang quét trang chủ lấy dữ liệu...")
    try:
        res = requests.get(current_home_url, impersonate="chrome110", timeout=20)
        soup = BeautifulSoup(res.text, 'html.parser')
        matches = []
        
        for a_tag in soup.find_all('a', href=True):
            href = a_tag['href']
            if '/truc-tiep/' in href:
                full_link = href if href.startswith('http') else f"{current_home_url.rstrip('/')}{href}"
                raw_title = a_tag.get('title') or a_tag.text.strip()
                
                if any(kw in (raw_title + full_link).lower() for kw in BLACKLIST): continue
                
                imgs = a_tag.find_all('img') or (a_tag.parent.find_all('img') if a_tag.parent else [])
                logo = ""
                for img in imgs:
                    src = img.get('data-src') or img.get('src') or ""
                    if src and '/categories/' not in src:
                        logo = src if src.startswith('http') else f"https:{src}" if src.startswith('//') else src
                        break

                time_tag, sort_val = get_match_time(full_link)
                
                # CỰC AN TOÀN: Bóc tên 2 đội từ đường link, vứt bỏ toàn bộ chữ rác HTML
                clean_title = get_clean_name_from_url(full_link)
                
                if not any(m['url'] == full_link for m in matches):
                    matches.append({
                        'url': full_link, 'clean_title': clean_title,
                        'time': time_tag, 'logo': logo, 'sort': sort_val
                    })
        
        matches.sort(key=lambda x: x['sort'])
        
        playlist = "#EXTM3U\n"
        print("✅ Đang tổng hợp Link và Tên BLV...")
        
        count = 0
        for m in matches:
            streams = extract_streams(m['url'])
            if streams:
                for s in streams:
                    blv_name = s['name']
                    
                    if blv_name and blv_name not in ["Luồng Chính", "Luồng Phụ", "Server"]:
                        if "BLV" not in blv_name.upper():
                            blv_tag = f"[BLV {blv_name}] "
                        else:
                            blv_tag = f"[{blv_name}] "
                    else:
                        blv_tag = ""
                    
                    display_name = f"{m['time']} {blv_tag}{m['clean_title']}"
                    
                    playlist += f'#EXTINF:-1 tvg-logo="{m["logo"]}", {display_name}\n'
                    playlist += f'#EXTVLCOPT:http-user-agent={UA}\n'
                    playlist += f'#EXTVLCOPT:http-referer={base_domain}/\n'
                    playlist += f'#EXTVLCOPT:http-origin={base_domain}\n'
                    
                    # FIX LỖI PLAYER OTT: Cắt bỏ đoạn User-Agent có chứa dấu cách khỏi URL
                    final_url = s['url']
                    if "|" not in final_url: final_url += f"|Referer={base_domain}/"
                    playlist += f'{final_url}\n'
                count += 1

        with open("buncha_live.m3u", "w", encoding="utf-8") as f:
            f.write(playlist)
        print(f"🎉 HOÀN TẤT! Link đã sửa lỗi phát, tên sạch 100%.")
        
    except Exception as e: print(f"Lỗi: {e}")

if __name__ == "__main__":
    main()
