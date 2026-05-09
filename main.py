from curl_cffi import requests
from bs4 import BeautifulSoup
import re
import codecs

def clean_match_title(raw_text):
    if not raw_text: return ""
    title = re.sub(r'\s+', ' ', raw_text.strip())
    title = re.sub(r'\s+\d+\s*[-:]\s*\d+\s+', ' vs ', title)
    return title

def extract_name_from_url(url):
    try:
        parts = [p for p in url.split('/') if p]
        slug = ""
        for part in parts:
            if '-vs-' in part:
                slug = part
                break
        if slug:
            name = re.sub(r'-\d{3,4}-\d{2}-\d{2}-\d{4}.*', '', slug)
            name = name.replace('-', ' ').title()
            name = name.replace(' Vs ', ' vs ')
            return name
    except:
        pass
    return ""

def get_matches(url):
    print(f"Đang quét trang chủ: {url}")
    try:
        response = requests.get(url, impersonate="chrome110", timeout=15)
        soup = BeautifulSoup(response.text, 'html.parser')
        matches = []
        
        for a_tag in soup.find_all('a', href=True):
            href = a_tag['href']
            if '/truc-tiep/' in href or '/truoc-tran/' in href:
                full_link = href if href.startswith('http') else f"https://bunchatv4.net{href}"
                
                title = extract_name_from_url(full_link)
                if not title:
                    raw_title = a_tag.get('title') or a_tag.text.strip()
                    title = re.sub(r'\s+', ' ', raw_title)
                    title = re.sub(r'\s+\d+\s*[-:]\s*\d+\s+', ' vs ', title)
                    if title.lower() in ['bóng đá', 'trực tiếp', 'trang chủ']: 
                        title = full_link.split('/')[-1]

                imgs = a_tag.find_all('img')
                if not imgs and a_tag.parent:
                    imgs = a_tag.parent.find_all('img')
                
                logo_url = ""
                for img in imgs:
                    src = img.get('data-src') or img.get('data-original') or img.get('src') or ""
                    if src and '/categories/' not in src and 'icon' not in src:
                        logo_url = src
                        if logo_url.startswith('//'):
                            logo_url = 'https:' + logo_url
                        break 
                
                if title and re.search('[a-zA-Z]', title):
                    if not any(m['url'] == full_link for m in matches):
                        matches.append({'url': full_link, 'title': title, 'logo': logo_url})
                    
        return matches
    except Exception as e:
        print(f"Lỗi quét trang chủ: {e}")
        return []

def clean_stream_link(link):
    """Làm sạch link bị mã hóa trong Javascript"""
    link = link.replace('\\/', '/')
    link = link.replace('\\u0026', '&').replace('u0026', '&') # Sửa lỗi mã hóa dấu &
    link = link.replace('\\', '')
    return link

def extract_all_m3u8_from_url(url):
    """Nội soi toàn diện: Quét JSON, Quét Nút bấm, Quét Iframe"""
    try:
        res = requests.get(url, impersonate="chrome110", timeout=15)
        html_content = res.text
        soup = BeautifulSoup(html_content, 'html.parser')
        
        streams = []
        seen_links = set()
        url_to_name = {}

        # --- BƯỚC 1: NỘI SOI JAVASCRIPT/JSON CỦA WEB ---
        # Tìm các đoạn code có dạng: name: "BLV Shin", url: "https..."
        json_pattern1 = re.findall(r'["\']?(?:name|title)["\']?\s*:\s*["\']([^"\']+)["\'].*?["\']?(?:url|link|src|iframe)["\']?\s*:\s*["\']([^"\']+)["\']', html_content, re.IGNORECASE)
        json_pattern2 = re.findall(r'["\']?(?:url|link|src|iframe)["\']?\s*:\s*["\']([^"\']+)["\'].*?["\']?(?:name|title)["\']?\s*:\s*["\']([^"\']+)["\']', html_content, re.IGNORECASE)
        
        for name, link in json_pattern1:
            url_to_name[clean_stream_link(link)] = codecs.decode(name.encode(), 'unicode_escape')
            
        for link, name in json_pattern2:
            url_to_name[clean_stream_link(link)] = codecs.decode(name.encode(), 'unicode_escape')

        # --- BƯỚC 2: QUÉT NÚT BẤM HTML (Đề phòng web không dùng JSON) ---
        for tag in soup.find_all(['button', 'a', 'span', 'li', 'div']):
            text = re.sub(r'\s+', ' ', tag.text.strip())
            if text and 2 <= len(text) <= 25: # Nếu là 1 cụm từ ngắn giống tên BLV
                tag_html = str(tag)
                urls = re.findall(r'(https?://[^\s"\'<>]+|//[^\s"\'<>]+)', tag_html)
                for u in urls:
                    u = clean_stream_link(u)
                    if u.startswith('//'): u = 'https:' + u
                    if len(u) > 10: url_to_name[u] = text

        def add_stream(m3u8_link, name):
            m3u8_link = clean_stream_link(m3u8_link)
            if m3u8_link not in seen_links:
                name = name.replace('Đang phát', '').replace('Chọn', '').strip()
                if not name or name == '-': name = f"Luồng {len(streams)+1}"
                streams.append({'url': m3u8_link, 'name': name})
                seen_links.add(m3u8_link)

        # --- BƯỚC 3: RÁP TÊN VÀO LINK ---
        # 3.1 Gắn tên cho các link tìm thấy trực tiếp
        for u, name in url_to_name.items():
            if '.m3u8' in u:
                add_stream(u, name)
            elif 'http' in u or u.startswith('//'):
                # Nếu là link iframe, truy cập vào để moi m3u8 ra
                try:
                    iframe_res = requests.get(u, impersonate="chrome110", timeout=10)
                    sub_links = re.findall(r'(https?://[^\s"\'<>]*\.m3u8[^\s"\'<>]*)', iframe_res.text)
                    for l in sub_links: add_stream(l, name)
                except:
                    pass

        # 3.2 Vét cạn (Nếu web còn giấu m3u8 ở đâu đó mà bước trên chưa móc ra)
        main_links = re.findall(r'(https?://[^\s"\'<>]*\.m3u8[^\s"\'<>]*)', html_content)
        for l in main_links:
            # Ưu tiên tìm tên trong mớ JSON, nếu không có mới dùng chữ "Dự phòng"
            l_clean = clean_stream_link(l)
            name = url_to_name.get(l_clean, "Luồng Dự Phòng")
            add_stream(l, name)
            
        return streams
    except Exception as e:
        print(f"Lỗi trích xuất: {e}")
        return []

def main():
    target_url = "https://bunchatv4.net/"
    matches = get_matches(target_url)
    
    if not matches:
        print("Không có trận đấu nào hoặc web chặn kết nối.")
        with open("buncha_live.m3u", "w", encoding="utf-8") as f:
            f.write('#EXTM3U\n#EXTINF:-1 tvg-logo="", ❌ HIỆN KHÔNG CÓ TRẬN ĐẤU\nhttp://localhost/error.m3u8\n')
        return

    playlist = "#EXTM3U\n"
    success_count = 0
    user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    
    print(f"✅ Đã tìm thấy {len(matches)} trận đấu. Bắt đầu lặn lấy toàn bộ luồng BLV...")
    
    for match in matches:
        print(f"\nĐang xử lý: {match['title']}")
        streams = extract_all_m3u8_from_url(match['url'])
        
        if streams:
            for stream in streams:
                # Phép màu hiện tên BLV ở đây
                display_name = match['title']
                if stream['name'] and stream['name'] != "Luồng Dự Phòng":
                    display_name = f"{match['title']} ({stream['name']})"
                
                playlist += f'#EXTINF:-1 tvg-logo="{match["logo"]}", {display_name}\n'
                playlist += f'#EXTVLCOPT:http-user-agent={user_agent}\n'
                playlist += f'{stream["url"]}\n'
                
            success_count += 1
            print(f"  -> Lấy thành công {len(streams)} luồng: {', '.join([s['name'] for s in streams])}")
        else:
            print("  -> Thất bại (Không tìm thấy luồng stream nào).")
            
    if success_count == 0:
         playlist += '#EXTINF:-1 tvg-logo="", ❌ LỖI KHÔNG TÌM THẤY LINK STREAM\nhttp://localhost/error.m3u8\n'

    with open("buncha_live.m3u", "w", encoding="utf-8") as f:
        f.write(playlist)
        
    print(f"\n🎉 [HOÀN TẤT] Đã tạo file buncha_live.m3u thành công rực rỡ!")

if __name__ == "__main__":
    main()
