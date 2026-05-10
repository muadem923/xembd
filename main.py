from curl_cffi import requests
from bs4 import BeautifulSoup
import re
import codecs
from datetime import datetime

# --- CẤU HÌNH ---
BITLY_URL = "https://bit.ly/bunchatv"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

# Danh sách đen: Sút bay tạp nham
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

def parse_match_info(raw_text):
    """Bóc tách AN TOÀN: Bế BLV ra riêng, xóa giải đấu, giữ 2 đội"""
    if not raw_text: return "", ""
    
    # 1. Cứu tên BLV an toàn (Chỉ lấy tối đa 4 chữ sau chữ BLV)
    blv_name = ""
    m = re.search(r'(BLV\s+[a-zA-Z0-9\sÀ-ỹ]+)', raw_text, re.I)
    if m:
        words = m.group(1).split()
        blv_name = " ".join(words[:4]).strip()
        raw_text = raw_text.replace(m.group(1), "")

    # 2. Xóa các từ khóa giải đấu, tên nước (Match nguyên từ)
    junk = [
        'League', 'Cup', 'Championship', 'Division', 'Group', 'Serie A', 'Laliga', 'Bundesliga', 'Ligue 1',
        'English', 'England', 'Italian', 'Italy', 'Spanish', 'Spain', 'French', 'France', 
        'German', 'Germany', 'Dutch', 'Portuguese', 'Chinese', 'Japanese', 'Korean', 
        'United Arab Emirates', 'Arab', 'Saudi', 'Turkish', 'Professional', 'National',
        'CƯỢC NGAY', 'Trực tiếp', 'Bóng đá', 'Live', 'Click xem', 'vào', 'Giải'
    ]
    for j in junk:
        raw_text = re.sub(r'\b' + j + r'\b', '', raw_text, flags=re.IGNORECASE)

    # 3. Xóa ngày, tháng, năm, phút, tỷ số
    raw_text = re.sub(r'\d{1,2}/\d{1,2}', '', raw_text)
    raw_text = re.sub(r'\d{4}', '', raw_text)
    raw_text = re.sub(r'\d+\s*\'', '', raw_text)
    raw_text = re.sub(r'\d+\s*[-:]\s*\d+', ' vs ', raw_text)
    
    raw_text = re.sub(r'\s+', ' ', raw_text).strip()

    # 4. Ép khung: Lấy 3-4 từ hai bên chữ 'vs' để ra đúng Đội A vs Đội B
    if 'vs' in raw_text.lower():
        parts = re.split(r'\s+vs\s+', raw_text, flags=re.IGNORECASE)
        if len(parts) >= 2:
            t1 = " ".join(parts[0].strip().split()[-4:])
            t2 = " ".join(parts[1].strip().split()[:4])
            raw_text = f"{t1} vs {t2}"

    return blv_name, raw_text.title().replace(' Vs ', ' vs ')

def extract_all_m3u8(url):
    """Bới link video bằng Object JSON thu nhỏ (Không chết Regex nữa)"""
    try:
        res = requests.get(url, impersonate="chrome110", timeout=15)
        html = res.text
        soup = BeautifulSoup(html, 'html.parser')
        streams, seen = [], set()
        
        blv_map = {}
        # CỰC KỲ AN TOÀN: Chỉ bắt các cục {...} có chứa m3u8
        try:
            blocks = re.findall(r'\{[^{}]*?\.m3u8[^{}]*?\}', html)
            for block in blocks:
                name_match = re.search(r'["\'](?:name|title|blv|nickname)["\']\s*:\s*["\']([^"\']+)["\']', block, re.I)
                url_match = re.search(r'["\'](?:url|link|src|file)["\']\s*:\s*["\']([^"\']+)["\']', block, re.I)
                if url_match:
                    u = url_match.group(1).replace('\\/', '/').replace('\\', '')
                    n = name_match.group(1) if name_match else ""
                    try: n = codecs.decode(n.encode(), 'unicode_escape')
                    except: pass
                    blv_map[u] = n
        except: pass

        def add(link, name):
            link = link.replace('\\', '').replace('\\u0026', '&').replace('u0026', '&').strip()
            if link not in seen and '.m3u8' in link:
                final_n = blv_map.get(link, name).replace("CƯỢC NGAY", "").strip()
                streams.append({'url': link, 'name': final_n})
                seen.add(link)

        # Nút bấm server
        for tag in soup.find_all(['button', 'a', 'span', 'li']):
            d_link = tag.get('data-link') or tag.get('data-src') or tag.get('data-url')
            if d_link:
                if d_link.startswith('//'): d_link = 'https:' + d_link
                btn_text = tag.text.strip()
                if btn_text and len(btn_text) < 15:
                    try:
                        if '.m3u8' not in d_link:
                            s_res = requests.get(d_link, impersonate="chrome110", timeout=5)
                            for l in re.findall(r'(https?://[^\s"\'<>]*\.m3u8[^\s"\'<>]*)', s_res.text): add(l, btn_text)
                        else: add(d_link, btn_text)
                    except: pass

        # Mã nguồn
        for l in re.findall(r'(https?://[^\s"\'<>]*\.m3u8[^\s"\'<>]*)', html):
            add(l, "Luồng Chính")
            
        return streams
    except: return []

def main():
    current_home_url = expand_url(BITLY_URL)
    base_domain = "/".join(current_home_url.split('/')[:3])
    
    print(f"🚀 Đang lấy danh sách trận...")
    try:
        res = requests.get(current_home_url, impersonate="chrome110", timeout=20)
        soup = BeautifulSoup(res.text, 'html.parser')
        matches_raw = []
        
        for a_tag in soup.find_all('a', href=True):
            href = a_tag['href']
            if '/truc-tiep/' in href:
                full_link = href if href.startswith('http') else f"{current_home_url.rstrip('/')}{href}"
                raw_text = (a_tag.get('title') or a_tag.text or full_link).strip()
                
                if any(kw in raw_text.lower() for kw in BLACKLIST): continue
                
                # --- XỬ LÝ AN TOÀN TRƯỚC KHI LƯU ---
                home_blv, clean_name = parse_match_info(raw_text)
                
                if len(clean_name) < 5:
                    clean_name = full_link.split('/')[-2].replace('-', ' ').title()
                    clean_name = re.sub(r'\d{4}.*', '', clean_name).strip()

                imgs = a_tag.find_all('img') or (a_tag.parent.find_all('img') if a_tag.parent else [])
                logo = ""
                for img in imgs:
                    src = img.get('data-src') or img.get('src') or ""
                    if src and '/categories/' not in src:
                        logo = src if src.startswith('http') else f"https:{src}" if src.startswith('//') else src
                        break

                time_tag, sort_val = get_match_time(full_link)
                if not any(m['url'] == full_link for m in matches_raw):
                    matches_raw.append({
                        'url': full_link, 'clean_name': clean_name, 'home_blv': home_blv, 
                        'time': time_tag, 'logo': logo, 'sort': sort_val
                    })
        
        matches_raw.sort(key=lambda x: x['sort'])
        
        playlist = "#EXTM3U\n"
        print(f"✅ Bắt đầu xử lý từng trận và tổng hợp tên...")
        
        for m in matches_raw:
            streams = extract_all_m3u8(m['url'])
            if streams:
                for s in streams:
                    stream_name = s['name']
                    # Ưu tiên 1: Tên trên web (JSON bới được)
                    # Ưu tiên 2: Tên BLV bắt được ngoài trang chủ
                    if stream_name in ["Luồng Chính", "Server", "Luồng Nhanh", "LIVE", ""]:
                        stream_name = m['home_blv']
                    
                    blv_tag = f"[{stream_name}] " if stream_name else ""
                    display_name = f"{m['time']} {blv_tag}{m['clean_name']}"
                    
                    playlist += f'#EXTINF:-1 tvg-logo="{m["logo"]}", {display_name}\n'
                    playlist += f'#EXTVLCOPT:http-user-agent={UA}\n'
                    playlist += f'#EXTVLCOPT:http-referer={base_domain}/\n'
                    playlist += f'#EXTVLCOPT:http-origin={base_domain}\n'
                    
                    final_url = s["url"]
                    if "|" not in final_url: final_url += f"|Referer={base_domain}/&User-Agent={UA}"
                    playlist += f'{final_url}\n'

        with open("buncha_live.m3u", "w", encoding="utf-8") as f:
            f.write(playlist)
        print(f"🎉 HOÀN TẤT! Đã gắp xong.")
        
    except Exception as e: print(f"Lỗi: {e}")

if __name__ == "__main__":
    main()
