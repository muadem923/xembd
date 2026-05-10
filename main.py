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
            d = f"{m.group(3)}/{m.group(2)}" # Sửa lại định dạng Ngày/Tháng cho chuẩn Việt Nam
            sort_val = datetime.strptime(f"{m.group(4)}-{m.group(2)}-{m.group(3)} {t}", "%Y-%m-%d %H:%M")
            return f"[{t} {d}]", sort_val
    except: pass
    return "", datetime.now()

def get_matches():
    print(f"🚀 Đang quét trang chủ: Kết hợp logic Logo cũ + Tên mới...")
    try:
        res = requests.get(TARGET_URL, impersonate="chrome110", timeout=20)
        soup = BeautifulSoup(res.text, 'html.parser')
        matches = []
        
        # Lấy tất cả các thẻ <a> chứa link trực tiếp
        for a_tag in soup.find_all('a', href=True):
            href = a_tag['href']
            if '/truc-tiep/' in href or '/truoc-tran/' in href:
                full_link = href if href.startswith('http') else f"https://bunchatv4.net{href}"
                
                # --- LOGIC LẤY LOGO TỪ FILE CHUẨN CỦA BÁC ---
                imgs = a_tag.find_all('img')
                if not imgs and a_tag.parent:
                    imgs = a_tag.parent.find_all('img')
                
                logo_url = ""
                for img in imgs:
                    # Quét đa tầng thuộc tính ảnh
                    src = img.get('data-src') or img.get('data-original') or img.get('src') or img.get('data-lazy-src') or ""
                    if src and '/categories/' not in src and 'icon' not in src.lower():
                        logo_url = src if src.startswith('http') else f"https:{src}" if src.startswith('//') else src
                        break 

                # --- LOGIC LẤY TÊN VÀ THỜI GIAN ---
                time_tag, sort_val = get_match_time(full_link)
                
                # Ưu tiên lấy tên từ Title hoặc Text của thẻ A
                raw_name = a_tag.get('title') or a_tag.text.strip()
                if not raw_name or len(raw_name) < 5:
                    # Nếu thẻ A không có tên, tìm trong các thẻ h3, h5 lân cận
                    parent = a_tag.parent
                    raw_name = parent.get_text(" ", strip=True) if parent else ""

                # Dọn rác tên trận
                clean_name = re.sub(r'\s+', ' ', raw_name)
                trash = ["CƯỢC NGAY", "Live", "Trực tiếp", "Bóng đá", "Hot", "Click", "vào"]
                for w in trash: clean_name = clean_name.replace(w, "")
                clean_name = re.sub(r'\d+\s*[-:]\s*\d+', ' vs ', clean_name).strip()
                
                # Chốt chặn nếu tên vẫn lỗi (lấy từ Slug URL)
                if len(clean_name) < 5:
                    slug = full_link.split('/')[-2].replace('-', ' ').title()
                    clean_name = re.sub(r'\d{4}.*', '', slug).strip()

                if not any(m['url'] == full_link for m in matches):
                    matches.append({
                        'url': full_link, 'title': clean_name, 
                        'time': time_tag, 'logo': logo_url, 'sort': sort_val
                    })
        
        matches.sort(key=lambda x: x['sort'])
        return matches
    except Exception as e:
        print(f"Lỗi trang chủ: {e}"); return []

def extract_all_m3u8_from_url(url):
    """Mổ xẻ lấy link video và khớp tên BLV (Giữ logic vét cạn của bác)"""
    try:
        res = requests.get(url, impersonate="chrome110", timeout=15)
        html = res.text
        soup = BeautifulSoup(html, 'html.parser')
        streams = []
        seen = set()
        
        # Bẫy tên BLV từ Script
        blv_map = {}
        json_data = re.findall(r'["\']?(?:name|title)["\']?\s*:\s*["\']([^"\']+)["\'].*?["\']?(?:url|link|src|iframe)["\']?\s*:\s*["\']([^"\']+)["\']', html, re.I)
        for b_name, b_url in json_data:
            u = b_url.replace('\\/', '/').replace('\\', '').replace('u0026', '&')
            try: blv_map[u] = codecs.decode(b_name.encode(), 'unicode_escape')
            except: blv_map[u] = b_name

        def add(link, name):
            link = link.replace('\\', '').replace('\\u0026', '&').replace('u0026', '&').strip()
            if link not in seen and '.m3u8' in link:
                final_n = blv_map.get(link, name)
                final_n = final_n.replace("CƯỢC NGAY", "").strip()
                streams.append({'url': link, 'name': final_n})
                seen.add(link)

        # 1. Quét các nút bấm (Logic bản chuẩn của bác)
        for tag in soup.find_all(['button', 'a', 'span', 'li']):
            d_link = tag.get('data-link') or tag.get('data-src') or tag.get('data-url') or tag.get('data-play')
            if d_link and ('.m3u8' in d_link or 'http' in d_link or '//' in d_link):
                if d_link.startswith('//'): d_link = 'https:' + d_link
                btn_text = tag.text.strip()
                if not btn_text or len(btn_text) > 20: btn_text = "Server"
                
                try:
                    # Với các link server phụ, ta quét nhẹ để lấy m3u8
                    if '.m3u8' not in d_link:
                        s_res = requests.get(d_link, impersonate="chrome110", timeout=5)
                        for l in re.findall(r'(https?://[^\s"\'<>]*\.m3u8[^\s"\'<>]*)', s_res.text):
                            add(l, btn_text)
                    else: add(d_link, btn_text)
                except: pass

        # 2. Vét cạn toàn bộ link m3u8 trong HTML
        for l in re.findall(r'(https?://[^\s"\'<>]*\.m3u8[^\s"\'<>]*)', html):
            add(l, "Luồng Chính")
            
        return streams
    except: return []

def main():
    matches = get_matches()
    if not matches: return

    playlist = "#EXTM3U\n"
    count = 0
    
    for m in matches:
        print(f"-> {m['time']} {m['title']}")
        links = extract_all_m3u8_from_url(m['url'])
        if links:
            for s in links:
                # Định dạng tên chuẩn: [Giờ] Tên Trận (BLV)
                blv = f" ({s['name']})" if s['name'] and s['name'] not in ["Luồng Chính", "Server"] else ""
                display_name = f"{m['time']} {m['title']}{blv}"
                
                playlist += f'#EXTINF:-1 tvg-logo="{m["logo"]}", {display_name}\n'
                playlist += f'#EXTVLCOPT:http-user-agent={UA}\n'
                playlist += f'{s["url"]}\n'
            count += 1
            
    with open("buncha_live.m3u", "w", encoding="utf-8") as f:
        f.write(playlist)
    print(f"\n🎉 HOÀN TẤT! Đã gắp xong {count} trận với đầy đủ Logo và BLV.")

if __name__ == "__main__":
    main()
