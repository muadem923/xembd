from curl_cffi import requests
from bs4 import BeautifulSoup
import re
import codecs
from datetime import datetime

# --- CẤU HÌNH ---
BITLY_URL = "https://bit.ly/bunchatv"
# Dùng đúng UA chuẩn bác đã cung cấp
UA = "Mozilla/5.0 AppleWebKit/537.36 Chrome/81.0.4044.138 Safari/537.36"

# Danh sách đen: Cấm tiệt các môn không phải bóng đá
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
    """Bóc giờ từ URL và format chuẩn: 19h00 ngày 11/05"""
    try:
        m = re.search(r'-(\d{4})-(\d{2})-(\d{2})-(\d{4})', url)
        if m:
            t = f"{m.group(1)[:2]}h{m.group(1)[2:]}" # 19h00
            d = f"{m.group(3)}/{m.group(2)}"         # 11/05
            sort_val = datetime.strptime(f"{m.group(4)}-{m.group(2)}-{m.group(3)} {m.group(1)[:2]}:{m.group(1)[2:]}", "%Y-%m-%d %H:%M")
            return f"{t} ngày {d}", sort_val
    except: pass
    return "", datetime.now()

def clean_title_basic(raw_text):
    """Dọn rác giữ nguyên tên 2 đội"""
    if not raw_text: return "Trận Đấu"
    
    junk = ['CƯỢC NGAY', 'Trực tiếp', 'Bóng đá', 'Live', 'Click xem', 'Giải']
    for j in junk:
        raw_text = re.sub(r'(?i)\b' + j + r'\b', '', raw_text)
        
    raw_text = re.sub(r'(?i)BLV\s+.*', '', raw_text)
    raw_text = re.sub(r'\d{1,2}/\d{1,2}', '', raw_text)
    raw_text = re.sub(r'\d{4}', '', raw_text)
    
    return re.sub(r'\s+', ' ', raw_text).strip(' -').replace('vs vs', 'vs').replace('Vs', 'vs')

def extract_streams(url):
    """BỘ QUÉT MỚI: Hỗ trợ tìm và bắt cả .m3u8 và .flv"""
    try:
        res = requests.get(url, impersonate="chrome110", timeout=15)
        html = res.text
        soup = BeautifulSoup(html, 'html.parser')
        streams = []
        seen = set()
        
        blv_map = {}
        for m in re.finditer(r'["\'](?:name|title|blv)["\']\s*:\s*["\']([^"\']+)["\'].*?["\'](?:url|src|link)["\']\s*:\s*["\']([^"\']+)["\']', html, re.I):
            u = m.group(2).replace('\\/', '/').replace('\\', '')
            try: n = bytes(m.group(1), 'utf-8').decode('unicode_escape')
            except: n = m.group(1)
            blv_map[u] = n
            
        for m in re.finditer(r'["\'](?:url|src|link)["\']\s*:\s*["\']([^"\']+)["\'].*?["\'](?:name|title|blv)["\']\s*:\s*["\']([^"\']+)["\']', html, re.I):
            u = m.group(1).replace('\\/', '/').replace('\\', '')
            try: n = bytes(m.group(2), 'utf-8').decode('unicode_escape')
            except: n = m.group(2)
            blv_map[u] = n

        def add_stream(link, fallback_name):
            link = link.replace('\\', '').replace('u0026', '&').strip()
            # Điều kiện mới: Tìm cả m3u8 và flv
            if link not in seen and ('.m3u8' in link or '.flv' in link):
                final_name = blv_map.get(link, fallback_name).replace("CƯỢC NGAY", "").strip()
                streams.append({'url': link, 'name': final_n})
                seen.add(link)

        for tag in soup.find_all(['button', 'a', 'span', 'li']):
            d_link = tag.get('data-link') or tag.get('data-src') or tag.get('data-url')
            if d_link:
                if d_link.startswith('//'): d_link = 'https:' + d_link
                btn_name = tag.text.strip()
                if not btn_name or len(btn_name) > 20: btn_name = ""
                
                if '.m3u8' not in d_link and '.flv' not in d_link:
                    try:
                        s_res = requests.get(d_link, impersonate="chrome110", timeout=5)
                        # Quét m3u8 và flv trong trang con
                        for l in re.findall(r'(https?://[^\s"\'<>]*\.(?:m3u8|flv)[^\s"\'<>]*)', s_res.text):
                            add_stream(l, btn_name)
                    except: pass
                else: 
                    add_stream(d_link, btn_name)

        # Quét HTML chính lấy link trực tiếp
        for l in re.findall(r'(https?://[^\s"\'<>]*\.(?:m3u8|flv)[^\s"\'<>]*)', html):
            add_stream(l, "")
            
        return streams
    except: return []

def main():
    current_home_url = expand_url(BITLY_URL)
    
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
                clean_title = clean_title_basic(raw_title)
                
                if not any(m['url'] == full_link for m in matches):
                    matches.append({
                        'url': full_link, 'clean_title': clean_title,
                        'time': time_tag, 'logo': logo, 'sort': sort_val
                    })
        
        matches.sort(key=lambda x: x['sort'])
        
        playlist = "#EXTM3U\n"
        print("✅ Đang tổng hợp Link...")
        
        count = 0
        for m in matches:
            streams = extract_streams(m['url'])
            if streams:
                for s in streams:
                    # Lấy phần mở rộng flv hoặc m3u8 từ URL
                    ext = "flv" if ".flv" in s['url'].lower() else "m3u8"
                    
                    blv_name = s['name']
                    # Xử lý gắn chữ BLV
                    if blv_name and blv_name not in ["Luồng Chính", "Luồng Phụ", "Server", ""]:
                        blv_tag = f"BLV {blv_name}" if "BLV" not in blv_name.upper() else blv_name
                    else:
                        blv_tag = ""
                    
                    # CẤU TRÚC CHUẨN: 19h00 ngày 11/05 Bali United vs Borneo FC Samarinda BLV MÃ SIÊU flv
                    display_parts = [m['time'], m['clean_title'], blv_tag, ext]
                    display_name = " ".join(part for part in display_parts if part)
                    
                    # DÙNG MẪU CHUẨN CỦA BÁC
                    playlist += f'#EXTINF:0 group-title="Bún Chả TV" tvg-logo="{m["logo"]}",{display_name}\n'
                    playlist += f'#EXTVLCOPT:http-user-agent={UA}\n'
                    playlist += f'{s["url"]}\n'
                count += 1

        with open("buncha_live.m3u", "w", encoding="utf-8") as f:
            f.write(playlist)
        print(f"🎉 HOÀN TẤT! Đã gắp xong {count} trận chuẩn mẫu.")
        
    except Exception as e: print(f"Lỗi: {e}")

if __name__ == "__main__":
    main()
    
