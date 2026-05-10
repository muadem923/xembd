from curl_cffi import requests
from bs4 import BeautifulSoup
import re
import codecs
from datetime import datetime

# Cấu hình
TARGET_URL = "https://bunchatv4.net/"
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

def get_match_info_from_url(url):
    """Bóc tách tên đội và thời gian trực tiếp từ đường link"""
    try:
        slug = url.split('/')[-2] if url.endswith('/') else url.split('/')[-1]
        # Regex tìm: doi-a-vs-doi-b-gio-ngay-thang-nam
        match = re.search(r'(.+?)-(\d{4})-(\d{2})-(\d{2})-(\d{4})', slug)
        if match:
            name_raw = match.group(1).replace('-', ' ').title().replace(' Vs ', ' vs ')
            time_str = f"{match.group(2)[:2]}:{match.group(2)[2:]}" # 1900 -> 19:00
            date_str = f"{match.group(3)}/{match.group(4)}" # ngay/thang
            # Tạo object datetime để sắp xếp
            sort_key = datetime.strptime(f"{match.group(5)}-{match.group(4)}-{match.group(3)} {time_str}", "%Y-%m-%d %H:%M")
            return name_raw, f"{time_str} {date_str}", sort_key
    except: pass
    return url.split('/')[-2].replace('-', ' ').title(), "Đang đá", datetime.now()

def get_matches():
    print(f"🚀 Đang quét trang chủ: {TARGET_URL}")
    try:
        res = requests.get(TARGET_URL, impersonate="chrome110", timeout=15)
        soup = BeautifulSoup(res.text, 'html.parser')
        matches = []
        for a in soup.find_all('a', href=True):
            href = a['href']
            if '/truc-tiep/' in href:
                full_link = href if href.startswith('http') else f"https://bunchatv4.net{href}"
                
                # Lấy Logo (Bỏ qua logo categories)
                img = a.find('img') or (a.parent.find('img') if a.parent else None)
                logo = ""
                if img:
                    logo = img.get('data-src') or img.get('src') or ""
                    if '/categories/' in logo: logo = "" # Sút quả bóng đi
                    if logo.startswith('//'): logo = 'https:' + logo

                name, start_time, sort_key = get_match_info_from_url(full_link)
                
                if not any(m['url'] == full_link for m in matches):
                    matches.append({
                        'url': full_link, 'name': name, 
                        'time': start_time, 'logo': logo, 'sort': sort_key
                    })
        
        # SẮP XẾP THEO THỜI GIAN
        matches.sort(key=lambda x: x['sort'])
        return matches
    except Exception as e:
        print(f"Lỗi quét trang chủ: {e}"); return []

def extract_streams(url):
    """Moi link m3u8 và tên BLV"""
    streams = []
    try:
        res = requests.get(url, impersonate="chrome110", timeout=8)
        html = res.text
        # Tìm link m3u8
        links = re.findall(r'(https?://[^\s"\'<>]*\.m3u8[^\s"\'<>]*)', html)
        # Tìm tên BLV trong script
        names = re.findall(r'["\']?(?:name|title)["\']?\s*:\s*["\']([^"\']+)["\']', html)
        
        seen = set()
        for i, l in enumerate(links):
            l = l.replace('\\/', '/').replace('\\u0026', '&').replace('u0026', '&').replace('\\', '')
            if l not in seen:
                blv = "Luồng chính"
                if i < len(names):
                    try: blv = codecs.decode(names[i].encode(), 'unicode_escape')
                    except: pass
                streams.append({'url': l, 'name': blv})
                seen.add(l)
    except: pass
    return streams

def main():
    matches = get_matches()
    if not matches: print("Không có trận nào."); return

    playlist = "#EXTM3U\n"
    count = 0
    print(f"✅ Đã sắp xếp {len(matches)} trận theo giờ đá. Đang lấy luồng...")

    for m in matches:
        print(f"-> [{m['time']}] {m['name']}", end=" ", flush=True)
        streams = extract_streams(m['url'])
        if streams:
            for s in streams:
                # Định dạng tên: [Giờ] Tên Trận (BLV)
                full_name = f"[{m['time']}] {m['name']} ({s['name']})"
                playlist += f'#EXTINF:-1 tvg-logo="{m["logo"]}", {full_name}\n'
                playlist += f'#EXTVLCOPT:http-user-agent={USER_AGENT}\n'
                playlist += f'{s["url"]}\n'
            count += 1
            print(f"[OK - {len(streams)} luồng]")
        else: print("[X]")

    with open("buncha_live.m3u", "w", encoding="utf-8") as f:
        f.write(playlist)
    print(f"\n🎉 Xong! Đã cập nhật {count} trận vào file vĩnh viễn.")

if __name__ == "__main__":
    main()
    
