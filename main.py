from curl_cffi import requests
from bs4 import BeautifulSoup
import re
import codecs
from datetime import datetime

# Cấu hình
TARGET_URL = "https://bunchatv4.net/"
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

def get_match_info_from_url(url):
    """Bóc tách tên đội và thời gian từ đường link"""
    try:
        slug = url.split('/')[-2] if url.endswith('/') else url.split('/')[-1]
        match = re.search(r'(.+?)-(\d{4})-(\d{2})-(\d{2})-(\d{4})', slug)
        if match:
            name_raw = match.group(1).replace('-', ' ').title().replace(' Vs ', ' vs ')
            time_str = f"{match.group(2)[:2]}:{match.group(2)[2:]}" 
            date_str = f"{match.group(3)}/{match.group(4)}"
            sort_key = datetime.strptime(f"{match.group(5)}-{match.group(4)}-{match.group(3)} {time_str}", "%Y-%m-%d %H:%M")
            return name_raw, f"[{time_str} {date_str}]", sort_key
    except: pass
    return url.split('/')[-1], "", datetime.now()

def get_matches(url):
    print(f"🚀 Đang quét trang chủ: {url}")
    try:
        response = requests.get(url, impersonate="chrome110", timeout=15)
        soup = BeautifulSoup(response.text, 'html.parser')
        matches = []
        
        for a_tag in soup.find_all('a', href=True):
            href = a_tag['href']
            if '/truc-tiep/' in href or '/truoc-tran/' in href:
                full_link = href if href.startswith('http') else f"https://bunchatv4.net{href}"
                
                # --- LẤY LOGO (Logic từ bản chuẩn của bác) ---
                imgs = a_tag.find_all('img')
                if not imgs and a_tag.parent: imgs = a_tag.parent.find_all('img')
                
                logo_url = ""
                for img in imgs:
                    src = img.get('data-src') or img.get('data-original') or img.get('src') or ""
                    if src and '/categories/' not in src: # Sút ảnh quả bóng
                        logo_url = src if src.startswith('http') else f"https:{src}" if src.startswith('//') else src
                        break 

                name, time_tag, sort_key = get_match_info_from_url(full_link)
                
                if not any(m['url'] == full_link for m in matches):
                    matches.append({
                        'url': full_link, 'title': name, 
                        'time_tag': time_tag, 'logo': logo_url, 'sort': sort_key
                    })
        
        matches.sort(key=lambda x: x['sort'])
        return matches
    except Exception as e:
        print(f"Lỗi: {e}"); return []

def extract_all_m3u8_from_url(url):
    """Mổ xẻ sâu để lấy link và khớp tên BLV từ JSON"""
    try:
        res = requests.get(url, impersonate="chrome110", timeout=15)
        html_content = res.text
        soup = BeautifulSoup(html_content, 'html.parser')
        
        streams = []
        seen_links = set()
        
        # Mẹo: Quét toàn bộ tên BLV giấu trong Script trước
        blv_map = {}
        json_data = re.findall(r'["\']?(?:name|title)["\']?\s*:\s*["\']([^"\']+)["\'].*?["\']?(?:url|link|src|iframe)["\']?\s*:\s*["\']([^"\']+)["\']', html_content, re.IGNORECASE)
        for b_name, b_url in json_data:
            clean_u = b_url.replace('\\/', '/').replace('\\', '')
            try: blv_map[clean_u] = codecs.decode(b_name.encode(), 'unicode_escape')
            except: blv_map[clean_u] = b_name

        def add_stream(link, name):
            link = link.replace('\\', '').replace('\\u0026', '&').replace('u0026', '&')
            if link not in seen_links:
                # Nếu link này có trong bản đồ BLV thì lấy tên đó
                final_name = blv_map.get(link, name)
                streams.append({'url': link, 'name': final_name})
                seen_links.add(link)

        # 1. Quét các nút bấm (Server phụ)
        for tag in soup.find_all(['button', 'a', 'span', 'li']):
            d_link = tag.get('data-link') or tag.get('data-src') or tag.get('data-url')
            if d_link and ('.m3u8' in d_link or 'http' in d_link):
                if d_link.startswith('//'): d_link = 'https:' + d_link
                blv_btn = tag.text.strip()
                if not blv_btn or len(blv_btn) > 20: blv_btn = "Server"
                
                try:
                    s_res = requests.get(d_link, impersonate="chrome110", timeout=8)
                    s_links = re.findall(r'(https?://[^\s"\'<>]*\.m3u8[^\s"\'<>]*)', s_res.text)
                    for l in s_links: add_stream(l, blv_btn)
                except: pass

        # 2. Iframe và Mã nguồn gốc
        iframes = [i.get('src') for i in soup.find_all('iframe') if i.get('src')]
        for ifr in iframes:
            if ifr.startswith('//'): ifr = 'https:' + ifr
            try:
                i_res = requests.get(ifr, impersonate="chrome110", timeout=8)
                i_links = re.findall(r'(https?://[^\s"\'<>]*\.m3u8[^\s"\'<>]*)', i_res.text)
                for l in i_links: add_stream(l, "Luồng Chính")
            except: pass
                    
        main_links = re.findall(r'(https?://[^\s"\'<>]*\.m3u8[^\s"\'<>]*)', html_content)
        for l in main_links: add_stream(l, "Luồng Nhanh")
            
        return streams
    except Exception: return []

def main():
    matches = get_matches(TARGET_URL)
    if not matches: return

    playlist = "#EXTM3U\n"
    success_count = 0
    
    print(f"✅ Đã gắp {len(matches)} trận. Đang lấy link...")
    
    for m in matches:
        print(f"\n-> {m['time_tag']} {m['title']}")
        streams = extract_all_m3u8_from_url(m['url'])
        
        if streams:
            for s in streams:
                # Định dạng: [Giờ] Tên Trận (BLV)
                display_name = f"{m['time_tag']} {m['title']} ({s['name']})"
                playlist += f'#EXTINF:-1 tvg-logo="{m["logo"]}", {display_name}\n'
                playlist += f'#EXTVLCOPT:http-user-agent={USER_AGENT}\n'
                playlist += f'{s["url"]}\n'
            success_count += 1
            print(f"  -> OK: {len(streams)} luồng")
        else: print("  -> X")

    with open("buncha_live.m3u", "w", encoding="utf-8") as f:
        f.write(playlist)
    print(f"\n🎉 HOÀN TẤT!")

if __name__ == "__main__":
    main()
    
