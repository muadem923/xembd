from curl_cffi import requests
from bs4 import BeautifulSoup
import re
import codecs
from datetime import datetime

# --- CẤU HÌNH ---
BITLY_URL = "https://bit.ly/bunchatv"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

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
    """Bóc giờ từ URL (vì URL chứa giờ rất chuẩn)"""
    try:
        m = re.search(r'-(\d{4})-(\d{2})-(\d{2})-(\d{4})', url)
        if m:
            t = f"{m.group(1)[:2]}:{m.group(1)[2:]}"
            d = f"{m.group(3)}/{m.group(2)}"
            sort_val = datetime.strptime(f"{m.group(4)}-{m.group(2)}-{m.group(3)} {t}", "%Y-%m-%d %H:%M")
            return f"[{t} {d}]", sort_val
    except: pass
    return "", datetime.now()

def clean_title_basic(raw_text):
    """Dọn rác CƠ BẢN: Giữ nguyên tên đội, giải đấu để không bị nát chữ"""
    if not raw_text: return "Trận Đấu"
    
    # 1. Xóa các chữ quảng cáo
    junk = ['CƯỢC NGAY', 'Trực tiếp', 'Bóng đá', 'Live', 'Click xem', 'Giải']
    for j in junk:
        raw_text = re.sub(r'(?i)\b' + j + r'\b', '', raw_text)
        
    # 2. Xóa chữ BLV... để tí nữa mình tự ghép vào cho chuẩn
    raw_text = re.sub(r'(?i)BLV\s+.*', '', raw_text)
    
    # 3. Xóa các ngày tháng thừa thãi
    raw_text = re.sub(r'\d{1,2}/\d{1,2}', '', raw_text)
    raw_text = re.sub(r'\d{4}', '', raw_text)
    
    return re.sub(r'\s+', ' ', raw_text).strip(' -')

def extract_streams(url):
    """Hàm VÉT CẠN nguyên bản từ file gốc của bác"""
    try:
        res = requests.get(url, impersonate="chrome110", timeout=15)
        html = res.text
        soup = BeautifulSoup(html, 'html.parser')
        streams = []
        seen = set()
        
        # BẪY TÊN BLV KÉP (NGUYÊN BẢN)
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
            if link not in seen and '.m3u8' in link:
                final_name = blv_map.get(link, fallback_name).replace("CƯỢC NGAY", "").strip()
                streams.append({'url': link, 'name': final_name})
                seen.add(link)

        for tag in soup.find_all(['button', 'a', 'span', 'li']):
            d_link = tag.get('data-link') or tag.get('data-src') or tag.get('data-url')
            if d_link:
                if d_link.startswith('//'): d_link = 'https:' + d_link
                btn_name = tag.text.strip()
                if not btn_name or len(btn_name) > 20: btn_name = "Luồng Chính"
                
                if '.m3u8' not in d_link:
                    try:
                        s_res = requests.get(d_link, impersonate="chrome110", timeout=5)
                        for l in re.findall(r'(https?://[^\s"\'<>]*\.m3u8[^\s"\'<>]*)', s_res.text):
                            add_stream(l, btn_name)
                    except: pass
                else: add_stream(d_link, btn_name)

        for l in re.findall(r'(https?://[^\s"\'<>]*\.m3u8[^\s"\'<>]*)', html):
            add_stream(l, "Luồng Phụ")
            
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
                
                # BỐC TÊN TỪ HTML CHỨ KHÔNG DÙNG URL NỮA!
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
                    blv_name = s['name']
                    
                    if blv_name and blv_name not in ["Luồng Chính", "Luồng Phụ", "Server"]:
                        blv_tag = f"[{blv_name}] " if "BLV" in blv_name.upper() else f"[BLV {blv_name}] "
                    else:
                        blv_tag = ""
                    
                    display_name = f"{m['time']} {blv_tag}{m['clean_title']}"
                    
                    playlist += f'#EXTINF:-1 tvg-logo="{m["logo"]}", {display_name}\n'
                    playlist += f'#EXTVLCOPT:http-user-agent={UA}\n'
                    playlist += f'#EXTVLCOPT:http-referer={base_domain}/\n'
                    playlist += f'#EXTVLCOPT:http-origin={base_domain}\n'
                    
                    # TUYỆT ĐỐI KHÔNG NỐI THÊM "|" VÀO ĐUÔI LINK NỮA ĐỂ TRÁNH LỖI TOKEN
                    playlist += f'{s["url"]}\n'
                count += 1

        with open("buncha_live.m3u", "w", encoding="utf-8") as f:
            f.write(playlist)
        print(f"🎉 ĐÃ KHÔI PHỤC THÀNH CÔNG BẢN GỐC! Link sạch và phát ầm ầm.")
        
    except Exception as e: print(f"Lỗi: {e}")

if __name__ == "__main__":
    main()
