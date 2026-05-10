from curl_cffi import requests
from bs4 import BeautifulSoup
import re
import codecs
from datetime import datetime

# Cấu hình
TARGET_URL = "https://bunchatv4.net/"
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

def get_match_time(url):
    """Lấy thời gian từ link để sắp xếp"""
    try:
        match = re.search(r'-(\d{4})-(\d{2})-(\d{2})-(\d{4})', url)
        if match:
            t = f"{match.group(1)[:2]}:{match.group(1)[2:]}"
            d = f"{match.group(2)}/{match.group(3)}"
            sort_val = datetime.strptime(f"{match.group(4)}-{match.group(3)}-{match.group(2)} {t}", "%Y-%m-%d %H:%M")
            return f"[{t} {d}]", sort_val
    except: pass
    return "", datetime.now()

def get_matches(url):
    print(f"🚀 Đang quét danh sách trận từ trang chủ...")
    try:
        response = requests.get(url, impersonate="chrome110", timeout=15)
        soup = BeautifulSoup(response.text, 'html.parser')
        matches = []
        
        # Tìm tất cả các khối chứa trận đấu (thường là thẻ có link)
        for a_tag in soup.find_all('a', href=True):
            href = a_tag['href']
            if '/truc-tiep/' in href or '/truoc-tran/' in href:
                full_link = href if href.startswith('http') else f"https://bunchatv4.net{href}"
                
                # --- LẤY TÊN TRẬN (Lấy text trực tiếp từ trang chủ) ---
                # Thường tên trận nằm trong thẻ span hoặc ngay trong text của thẻ a
                raw_name = a_tag.text.strip()
                if not raw_name or len(raw_name) < 5:
                    raw_name = a_tag.get('title') or ""
                
                # Làm sạch tên: xóa tỷ số, xóa "Bóng đá", xóa xuống dòng
                clean_name = re.sub(r'\s+', ' ', raw_name)
                clean_name = re.sub(r'\s+\d+\s*[-:]\s*\d+\s+', ' vs ', clean_name)
                clean_name = clean_name.replace('Trực tiếp ', '').replace('Bóng đá ', '')

                # --- LẤY LOGO ---
                img_tag = a_tag.find('img') or (a_tag.parent.find('img') if a_tag.parent else None)
                logo_url = ""
                if img_tag:
                    logo_url = img_tag.get('data-src') or img_tag.get('src') or ""
                    if '/categories/' in logo_url: logo_url = "" # Bỏ qua icon quả bóng
                    if logo_url.startswith('//'): logo_url = 'https:' + logo_url

                time_tag, sort_val = get_match_time(full_link)
                
                if clean_name and not any(m['url'] == full_link for m in matches):
                    matches.append({
                        'url': full_link, 'title': clean_name, 
                        'time': time_tag, 'logo': logo_url, 'sort': sort_val
                    })
        
        matches.sort(key=lambda x: x['sort'])
        return matches
    except Exception as e:
        print(f"Lỗi: {e}"); return []

def extract_all_m3u8(url):
    """Mổ xẻ lấy link video và khớp tên BLV"""
    try:
        res = requests.get(url, impersonate="chrome110", timeout=15)
        html = res.text
        soup = BeautifulSoup(html, 'html.parser')
        
        streams = []
        seen = set()
        blv_map = {}

        # 1. Tìm tên BLV giấu trong mã Script
        json_data = re.findall(r'["\']?(?:name|title)["\']?\s*:\s*["\']([^"\']+)["\'].*?["\']?(?:url|link|src|iframe)["\']?\s*:\s*["\']([^"\']+)["\']', html, re.IGNORECASE)
        for b_name, b_url in json_data:
            u = b_url.replace('\\/', '/').replace('\\u0026', '&').replace('u0026', '&').replace('\\', '')
            try: blv_map[u] = codecs.decode(b_name.encode(), 'unicode_escape')
            except: blv_map[u] = b_name

        def add(link, name):
            link = link.replace('\\', '').replace('\\u0026', '&').replace('u0026', '&')
            if link not in seen and '.m3u8' in link:
                final_name = blv_map.get(link, name)
                streams.append({'url': link, 'name': final_name})
                seen.add(link)

        # 2. Quét các nút Server
        for tag in soup.find_all(['button', 'span', 'li']):
            d_link = tag.get('data-link') or tag.get('data-src') or tag.get('data-url')
            if d_link:
                if d_link.startswith('//'): d_link = 'https:' + d_link
                btn_text = tag.text.strip()
                if not btn_text or len(btn_text) > 20: btn_text = "Server"
                try:
                    s_res = requests.get(d_link, impersonate="chrome110", timeout=5)
                    for l in re.findall(r'(https?://[^\s"\'<>]*\.m3u8[^\s"\'<>]*)', s_res.text):
                        add(l, btn_text)
                except: pass

        # 3. Quét mã nguồn chính
        for l in re.findall(r'(https?://[^\s"\'<>]*\.m3u8[^\s"\'<>]*)', html):
            add(l, "Luồng Nhanh")
            
        return streams
    except: return []

def main():
    matches = get_matches(TARGET_URL)
    if not matches: return

    playlist = "#EXTM3U\n"
    count = 0
    ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

    for m in matches:
        print(f"-> {m['time']} {m['title']}")
        links = extract_all_m3u8(m['url'])
        if links:
            for s in links:
                full_name = f"{m['time']} {m['title']} ({s['name']})"
                playlist += f'#EXTINF:-1 tvg-logo="{m["logo"]}", {full_name}\n'
                playlist += f'#EXTVLCOPT:http-user-agent={ua}\n'
                playlist += f'{s["url"]}\n'
            count += 1
    
    with open("buncha_live.m3u", "w", encoding="utf-8") as f:
        f.write(playlist)
    print(f"\n🎉 Đã xong! Lấy được {count} trận.")

if __name__ == "__main__":
    main()
    
