from curl_cffi import requests
from bs4 import BeautifulSoup
import re
import codecs
from datetime import datetime

# --- CẤU HÌNH ---
BITLY_URL = "https://bit.ly/bunchatv"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

# Danh sách đen: Lọc sạch các môn thể thao tạp nham
BLACKLIST = [
    "ufc", "mma", "tennis", "quần vợt", "bóng rổ", "cầu lông", "bóng chuyền", "esport",
    "atp", "wta", "itf", "challenger", "bóng bàn", "futsal", "đua xe", "golf", "billiard"
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

def clean_only_teams(text):
    """Bộ lọc V24: Chỉ giữ lại Tên Đội A vs Tên Đội B"""
    if not text: return ""
    junk_patterns = [
        r'CƯỢC NGAY', r'Trực tiếp', r'Bóng đá', r'Live', r'Click xem', r'vào',
        r'United Arab Emirates', r'Arab', r'Division', r'Group', r'League', r'Cup', r'Championship',
        r'English', r'England', r'Italian', r'Italy', r'Spanish', r'Spain', r'French', r'France', 
        r'German', r'Germany', r'Dutch', r'Portuguese', r'Portugal', r'Chinese', r'China', 
        r'Japanese', r'Japan', r'Korean', r'Korea', r'Saudi', r'Turkish', r'Professional', 
        r'Football', r'Super', r'National', r'International', r'A-League', r'U\d+', r'Women'
    ]
    for p in junk_patterns:
        text = re.sub(p, '', text, flags=re.IGNORECASE)
    text = re.sub(r'\d{1,2}/\d{1,2}', '', text)
    text = re.sub(r'\d{4}', '', text)
    text = re.sub(r'\d+\s*\'', '', text)
    text = re.sub(r'\d+\s*[-:]\s*\d+', ' vs ', text)
    text = re.sub(r'\s+', ' ', text).strip()
    text = text.replace('vs vs', 'vs').strip(' -')
    if 'vs' in text.lower():
        parts = re.split(r'\s+vs\s+', text, flags=re.IGNORECASE)
        if len(parts) >= 2:
            team1 = " ".join(parts[0].strip().split()[-3:])
            team2 = " ".join(parts[1].strip().split()[:3])
            text = f"{team1} vs {team2}"
    return text.title().replace(' Vs ', ' vs ')

def extract_all_m3u8(url):
    """Mổ xẻ lấy link video và khớp tên BLV bằng thuật toán 'Nội soi đa điểm'"""
    try:
        res = requests.get(url, impersonate="chrome110", timeout=15)
        html = res.text
        soup = BeautifulSoup(html, 'html.parser')
        streams, seen = [], set()
        
        # Bẫy tên BLV đa tầng: Tìm cả name, nickname, title, blv
        blv_map = {}
        json_data = re.findall(r'["\']?(?:name|nickname|title|blv|label)["\']?\s*:\s*["\']([^"\']+)["\'].*?["\']?(?:url|link|src|iframe)["\']?\s*:\s*["\']([^"\']+)["\']', html, re.I)
        for b_name, b_url in json_data:
            u = b_url.replace('\\/', '/').replace('\\', '').replace('u0026', '&')
            try: 
                decoded_name = codecs.decode(b_name.encode(), 'unicode_escape')
                if 3 < len(decoded_name) < 40: blv_map[u] = decoded_name
            except: blv_map[u] = b_name

        def add(link, name):
            link = link.replace('\\', '').replace('\\u0026', '&').replace('u0026', '&').strip()
            if link not in seen and '.m3u8' in link:
                final_n = blv_map.get(link, name).replace("CƯỢC NGAY", "").strip()
                # Nếu tên vẫn là rác hoặc quá dài, dùng mặc định
                if not final_n or len(final_n) > 20: final_n = "LIVE"
                streams.append({'url': link, 'name': final_n})
                seen.add(link)

        # Quét các nút bấm lấy tên luồng trực tiếp
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
    base_domain = "/".join(current_home_url.split('/')[:3])
    
    try:
        res = requests.get(current_home_url, impersonate="chrome110", timeout=20)
        soup = BeautifulSoup(res.text, 'html.parser')
        matches_raw = []
        
        for a_tag in soup.find_all('a', href=True):
            href = a_tag['href']
            if '/truc-tiep/' in href:
                full_link = href if href.startswith('http') else f"{current_home_url.rstrip('/')}{href}"
                raw_text = (a_tag.get('title') or a_tag.text or full_link).lower()
                if any(kw in raw_text for kw in BLACKLIST): continue
                
                imgs = a_tag.find_all('img') or (a_tag.parent.find_all('img') if a_tag.parent else [])
                logo = ""
                for img in imgs:
                    src = img.get('data-src') or img.get('src') or ""
                    if src and '/categories/' not in src:
                        logo = src if src.startswith('http') else f"https:{src}" if src.startswith('//') else src
                        break

                time_tag, sort_val = get_match_time(full_link)
                if not any(m['url'] == full_link for m in matches_raw):
                    matches_raw.append({'url': full_link, 'raw_title': a_tag.text.strip(), 'time': time_tag, 'logo': logo, 'sort': sort_val})
        
        matches_raw.sort(key=lambda x: x['sort'])
        
        playlist = "#EXTM3U\n"
        for m in matches_raw:
            streams = extract_all_m3u8(m['url'])
            if streams:
                clean_name = clean_only_teams(m['raw_title'])
                if len(clean_name) < 5:
                    clean_name = m['url'].split('/')[-2].replace('-', ' ').title()
                    clean_name = re.sub(r'\d{4}.*', '', clean_name).strip()

                for s in streams:
                    # Gắn BLV vào đúng vị trí bác yêu cầu: [Thời gian] [Tên BLV] Tên Trận
                    display_name = f"{m['time']} [{s['name']}] {clean_name}"
                    
                    playlist += f'#EXTINF:-1 tvg-logo="{m["logo"]}", {display_name}\n'
                    playlist += f'#EXTVLCOPT:http-user-agent={UA}\n'
                    playlist += f'#EXTVLCOPT:http-referer={base_domain}/\n'
                    playlist += f'#EXTVLCOPT:http-origin={base_domain}\n'
                    
                    final_url = s["url"]
                    if "|" not in final_url: final_url += f"|Referer={base_domain}/&User-Agent={UA}"
                    playlist += f'{final_url}\n'

        with open("buncha_live.m3u", "w", encoding="utf-8") as f:
            f.write(playlist)
        print(f"🎉 Đã gắp xong link với BLV chuẩn!")
        
    except Exception as e: print(f"Lỗi: {e}")

if __name__ == "__main__":
    main()
