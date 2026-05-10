from curl_cffi import requests
from bs4 import BeautifulSoup
import re
import codecs
from datetime import datetime

# Cấu hình
TARGET_URL = "https://bunchatv4.net/"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

def get_match_time(url):
    try:
        m = re.search(r'-(\d{4})-(\d{2})-(\d{2})-(\d{4})', url)
        if m:
            t = f"{m.group(1)[:2]}:{m.group(1)[2:]}"
            d = f"{m.group(2)}/{m.group(3)}"
            sort_val = datetime.strptime(f"{m.group(4)}-{m.group(3)}-{m.group(2)} {t}", "%Y-%m-%d %H:%M")
            return f"[{t} {d}]", sort_val
    except: pass
    return "", datetime.now()

def get_matches():
    print(f"🚀 Đang quét trang chủ để lấy Logo và Tên chuẩn...")
    try:
        res = requests.get(TARGET_URL, impersonate="chrome110", timeout=20)
        soup = BeautifulSoup(res.text, 'html.parser')
        matches = []
        
        # Quét các khối chứa trận
        items = soup.find_all(['div', 'a', 'li'], class_=re.compile(r'item|match|live|box', re.I))
        
        for item in items:
            a_tag = item if item.name == 'a' else item.find('a', href=True)
            if not a_tag or '/truc-tiep/' not in a_tag['href']: continue
            
            url = a_tag['href'] if a_tag['href'].startswith('http') else f"https://bunchatv4.net{a_tag['href']}"
            
            # 1. Lọc Tên Trận (Xóa rác)
            name = item.get_text(" ", strip=True)
            name = re.sub(r'\s+', ' ', name)
            # Xóa các cụm từ rác hay xuất hiện trên web bóng đá
            trash_words = ["CƯỢC NGAY", "Live", "Trực tiếp", "Bóng đá", "Click xem", "Hot", "vào", "vs -"]
            for word in trash_words:
                name = name.replace(word, "")
            name = re.sub(r'\d+\s*[-:]\s*\d+', ' vs ', name).strip()
            
            # 2. Truy tìm Logo (Quét mọi ngóc ngách)
            img = item.find('img')
            logo = ""
            if img:
                # Danh sách các thuộc tính web hay dùng để giấu ảnh
                for attr in ['data-src', 'data-lazy-src', 'data-original', 'data-srcset', 'src']:
                    logo = img.get(attr) or ""
                    if logo: break
                
                if '/categories/' in logo or 'icon' in logo.lower(): logo = ""
                if logo.startswith('//'): logo = "https:" + logo
            
            time_tag, sort_val = get_match_time(url)
            
            # Chốt chặn tên từ URL nếu quét HTML bị lỗi
            if len(name) < 5 or "vs" not in name.lower():
                slug = url.split('/')[-2].replace('-', ' ').title()
                name = re.sub(r'\d{4}.*', '', slug).strip()

            if not any(m['url'] == url for m in matches):
                matches.append({'url': url, 'title': name, 'logo': logo, 'time': time_tag, 'sort': sort_val})
        
        matches.sort(key=lambda x: x['sort'])
        return matches
    except Exception as e:
        print(f"Lỗi: {e}"); return []

def extract_streams(url):
    streams = []
    seen = set()
    try:
        res = requests.get(url, impersonate="chrome110", timeout=15)
        html = res.text
        
        # Bẫy BLV
        blv_dict = {}
        # Cập nhật Regex bắt JSON chuẩn hơn
        pairs = re.findall(r'["\']?(?:name|title)["\']?\s*:\s*["\']([^"\']+)["\'].*?["\']?(?:url|src|link)["\']?\s*:\s*["\']([^"\']+)["\']', html, re.I)
        for b_name, b_url in pairs:
            u_clean = b_url.replace('\\/', '/').replace('\\', '').replace('u0026', '&')
            try: 
                decoded_name = codecs.decode(b_name.encode(), 'unicode_escape')
                blv_dict[u_clean] = decoded_name
            except: 
                blv_dict[u_clean] = b_name

        def add(l, n):
            l = l.replace('\\/', '/').replace('\\', '').replace('u0026', '&').strip()
            if l not in seen and '.m3u8' in l:
                # Ưu tiên lấy tên từ JSON nếu link khớp
                final_n = blv_dict.get(l, n)
                # Dọn dẹp tên BLV nếu bị dính rác
                final_n = final_n.replace("CƯỢC NGAY", "").strip()
                streams.append({'url': l, 'name': final_n})
                seen.add(l)

        # Quét link m3u8 toàn trang
        all_links = re.findall(r'(https?://[^\s"\'<>]*\.m3u8[^\s"\'<>]*)', html)
        for l in all_links: add(l, "Luồng Nhanh")
            
        # Quét Iframe lồng nhau
        iframes = re.findall(r'<iframe.*?src=["\'](.*?)["\']', html)
        for ifr in iframes:
            if ifr.startswith('//'): ifr = "https:" + ifr
            try:
                ifr_res = requests.get(ifr, impersonate="chrome110", timeout=7)
                ifr_links = re.findall(r'(https?://[^\s"\'<>]*\.m3u8[^\s"\'<>]*)', ifr_res.text)
                for l in ifr_links: add(l, "Luồng Chính")
            except: pass
            
    except: pass
    return streams

def main():
    matches = get_matches()
    if not matches: return

    playlist = "#EXTM3U\n"
    count = 0
    print(f"✅ Tìm thấy {len(matches)} trận. Bắt đầu gắp link...")

    for m in matches:
        print(f"-> {m['time']} {m['title']}", end=" ", flush=True)
        links = extract_streams(m['url'])
        if links:
            for s in links:
                # Tên BLV nếu có thì gắn vào, không thì thôi
                blv_part = f" ({s['name']})" if s['name'] and s['name'] != "Luồng Nhanh" else ""
                full_name = f"{m['time']} {m['title']}{blv_part}"
                
                playlist += f'#EXTINF:-1 tvg-logo="{m["logo"]}", {full_name}\n'
                playlist += f'#EXTVLCOPT:http-user-agent={UA}\n'
                playlist += f'{s["url"]}\n'
            count += 1
            print(f"[OK - {len(links)} luồng]")
        else: print("[X]")

    with open("buncha_live.m3u", "w", encoding="utf-8") as f:
        f.write(playlist)
    print(f"\n🎉 HOÀN TẤT! Đã gắp xong {count} trận.")

if __name__ == "__main__":
    main()
