from curl_cffi import requests
from bs4 import BeautifulSoup
import re
import codecs
from datetime import datetime

# --- CẤU HÌNH ---
BITLY_URL = "https://bit.ly/bunchatv"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

# Danh sách đen để lọc các môn không phải bóng đá
BLACKLIST = ["ufc", "mma", "tennis", "quần vợt", "bóng rổ", "cầu lông", "bóng chuyền", "esport"]

def expand_url(short_url):
    try:
        res = requests.get(short_url, impersonate="chrome110", allow_redirects=True, timeout=15)
        final_url = res.url
        return final_url if final_url.endswith('/') else final_url + '/'
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

def clean_title_v20(text):
    """Bộ lọc siêu sạch: Chỉ giữ lại Tên Đội A vs Tên Đội B"""
    if not text: return ""
    # 1. Xóa các cụm từ rác và giải đấu
    junk = [
        "CƯỢC NGAY", "Trực tiếp", "Bóng đá", "Live", "vs -", "Click xem", 
        "Football", "Super League", "League", "Championship", "Premier", "Cup", "Serie A", "Laliga"
    ]
    for w in junk:
        text = re.sub(re.escape(w), '', text, flags=re.IGNORECASE)
    
    # 2. Xóa ngày tháng năm (ví dụ: 10/05, 05/10, 2026)
    text = re.sub(r'\d{1,2}/\d{1,2}', '', text)
    text = re.sub(r'\d{4}', '', text)
    
    # 3. Xóa tỷ số hoặc phút đang đá (ví dụ: 79 ', 1 - 0)
    text = re.sub(r'\d+\s*\'', '', text)
    text = re.sub(r'\d+\s*[-:]\s*\d+', ' vs ', text)
    
    # 4. Dọn dẹp khoảng trắng và dấu gạch dư thừa
    text = re.sub(r'\s+', ' ', text)
    text = text.replace('vs vs', 'vs').replace('- vs', 'vs').strip()
    
    # 5. Nếu còn chữ 'vs' ở đầu hoặc cuối thì xóa nốt
    text = re.sub(r'^vs\s+|^\s+vs\s+|-|vs$', '', text).strip()
    
    # 6. Đảm bảo có chữ 'vs' chuẩn ở giữa 2 đội
    if 'vs' not in text.lower() and len(text.split()) > 2:
        parts = text.split()
        mid = len(parts) // 2
        text = " ".join(parts[:mid]) + " vs " + " ".join(parts[mid:])
        
    return text

def get_matches(domain_url):
    print(f"🚀 Đang quét trận đấu tại: {domain_url}")
    try:
        res = requests.get(domain_url, impersonate="chrome110", timeout=20)
        soup = BeautifulSoup(res.text, 'html.parser')
        matches = []
        
        for a_tag in soup.find_all('a', href=True):
            href = a_tag['href']
            if '/truc-tiep/' in href:
                full_link = href if href.startswith('http') else f"{domain_url.rstrip('/')}{href}"
                
                raw_name = a_tag.get('title') or a_tag.text.strip()
                if not raw_name or len(raw_name) < 5:
                    parent = a_tag.parent
                    raw_name = parent.get_text(" ", strip=True) if parent else ""

                # Lọc môn thể thao khác
                check_text = (full_link + " " + raw_name).lower()
                if any(kw in check_text for kw in BLACKLIST): continue

                # --- LẤY LOGO ---
                imgs = a_tag.find_all('img')
                if not imgs and a_tag.parent: imgs = a_tag.parent.find_all('img')
                logo_url = ""
                for img in imgs:
                    src = img.get('data-src') or img.get('src') or img.get('data-original') or ""
                    if src and '/categories/' not in src:
                        logo_url = src if src.startswith('http') else f"https:{src}" if src.startswith('//') else src
                        break 

                time_tag, sort_val = get_match_time(full_link)
                # Dùng bộ lọc V20 mới để làm sạch tên
                clean_name = clean_title_v20(raw_name)

                if not any(m['url'] == full_link for m in matches):
                    matches.append({'url': full_link, 'title': clean_name, 'time': time_tag, 'logo': logo_url, 'sort': sort_val})
        
        matches.sort(key=lambda x: x['sort'])
        return matches
    except: return []

def extract_all_m3u8(url):
    try:
        res = requests.get(url, impersonate="chrome110", timeout=15)
        html = res.text
        soup = BeautifulSoup(html, 'html.parser')
        streams, seen = [], set()
        
        blv_map = {}
        json_data = re.findall(r'["\']?(?:name|title)["\']?\s*:\s*["\']([^"\']+)["\'].*?["\']?(?:url|link|src|iframe)["\']?\s*:\s*["\']([^"\']+)["\']', html, re.I)
        for b_name, b_url in json_data:
            u = b_url.replace('\\/', '/').replace('\\', '').replace('u0026', '&')
            try: blv_map[u] = codecs.decode(b_name.encode(), 'unicode_escape')
            except: blv_map[u] = b_name

        def add(link, name):
            link = link.replace('\\', '').replace('\\u0026', '&').replace('u0026', '&').strip()
            if link not in seen and '.m3u8' in link:
                final_n = blv_map.get(link, name).replace("CƯỢC NGAY", "").strip()
                streams.append({'url': link, 'name': final_n})
                seen.add(link)

        for tag in soup.find_all(['button', 'a', 'span', 'li']):
            d_link = tag.get('data-link') or tag.get('data-src') or tag.get('data-url')
            if d_link:
                if d_link.startswith('//'): d_link = 'https:' + d_link
                btn_text = tag.text.strip()
                if btn_text and len(btn_text) < 15:
                    try:
                        if '.m3u8' not in d_link:
                            s_res = requests.get(d_link, impersonate="chrome110", timeout=5)
                            for l in re.findall(r'(https?://[^\s"\'<>]*\.m3u8[^\s"\'<>]*)', s_res.text):
                                add(l, btn_text)
                        else: add(d_link, btn_text)
                    except: pass

        for l in re.findall(r'(https?://[^\s"\'<>]*\.m3u8[^\s"\'<>]*)', html):
            add(l, "Luồng Chính")
        return streams
    except: return []

def main():
    current_home_url = expand_url(BITLY_URL)
    matches = get_matches(current_home_url)
    if not matches: return

    playlist = "#EXTM3U\n"
    count = 0
    base_domain = "/".join(current_home_url.split('/')[:3])

    for m in matches:
        print(f"-> {m['time']} {m['title']}")
        links = extract_all_m3u8(m['url'])
        if links:
            for s in links:
                # Gắn tên BLV vào sau cùng
                blv = f" ({s['name']})" if s['name'] and s['name'] not in ["Luồng Chính", "Server", "Luồng Nhanh"] else ""
                # Kết quả mong muốn: [Giờ Ngày] Đội A vs Đội B (BLV)
                display_name = f"{m['time']} {m['title']}{blv}"
                
                playlist += f'#EXTINF:-1 tvg-logo="{m["logo"]}", {display_name}\n'
                playlist += f'#EXTVLCOPT:http-user-agent={UA}\n'
                playlist += f'#EXTVLCOPT:http-referer={base_domain}/\n'
                playlist += f'#EXTVLCOPT:http-origin={base_domain}\n'
                
                final_url = s["url"]
                if "|" not in final_url:
                    final_url += f"|Referer={base_domain}/&User-Agent={UA}"
                playlist += f'{final_url}\n'
            count += 1
            
    with open("buncha_live.m3u", "w", encoding="utf-8") as f:
        f.write(playlist)
    print(f"🎉 Xong! Đã gắp {count} trận.")

if __name__ == "__main__":
    main()
    
