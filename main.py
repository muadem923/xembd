from curl_cffi import requests
from bs4 import BeautifulSoup
import re

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

def extract_all_m3u8_from_url(url):
    """Chiêu thức vét cạn: Tìm toàn bộ link m3u8 và tên BLV"""
    try:
        res = requests.get(url, impersonate="chrome110", timeout=15)
        soup = BeautifulSoup(res.text, 'html.parser')
        
        streams = []
        seen_links = set() # Dùng để chống trùng lặp link
        
        def add_stream(link, name):
            link = link.replace('\\', '')
            if link not in seen_links:
                streams.append({'url': link, 'name': name})
                seen_links.add(link)

        # 1. BẮT CÁC NÚT BẤM (Các tab BLV, Server)
        # Các web thường giấu link trong thuộc tính data-link, data-src ở các thẻ span, button, li
        for tag in soup.find_all(['button', 'a', 'span', 'li', 'div']):
            data_link = tag.get('data-link') or tag.get('data-src') or tag.get('data-url') or tag.get('data-play')
            if data_link and ('http' in data_link or '//' in data_link):
                if data_link.startswith('//'): data_link = 'https:' + data_link
                
                # Cố gắng đọc tên BLV trên cái nút đó
                blv_name = re.sub(r'\s+', ' ', tag.text.strip())
                if not blv_name or len(blv_name) > 25: 
                    blv_name = "Server Phụ"
                    
                try:
                    sub_res = requests.get(data_link, impersonate="chrome110", timeout=10)
                    sub_links = re.findall(r'(https?://[^\s"\'<>]*\.m3u8[^\s"\'<>]*)', sub_res.text)
                    for l in sub_links: add_stream(l, blv_name)
                except:
                    pass

        # 2. BẮT CÁC IFRAME HIỂN THỊ SẴN
        for iframe in soup.find_all('iframe'):
            iframe_src = iframe.get('src')
            if iframe_src:
                if iframe_src.startswith('//'): iframe_src = 'https:' + iframe_src
                try:
                    iframe_res = requests.get(iframe_src, impersonate="chrome110", timeout=10)
                    iframe_links = re.findall(r'(https?://[^\s"\'<>]*\.m3u8[^\s"\'<>]*)', iframe_res.text)
                    for l in iframe_links: add_stream(l, "Luồng Chính")
                except:
                    pass
                    
        # 3. VÉT CẠN TRONG MÃ NGUỒN GỐC (Trường hợp web không dùng iframe)
        main_links = re.findall(r'(https?://[^\s"\'<>]*\.m3u8[^\s"\'<>]*)', res.text)
        for l in main_links:
            add_stream(l, "Luồng Nhanh")
            
        return streams
    except Exception:
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
                # Nếu trận đấu có nhiều hơn 1 luồng, ta gắn thêm tên BLV vào ngoặc đơn
                display_name = match['title']
                if len(streams) > 1 and stream['name']:
                    display_name = f"{match['title']} ({stream['name']})"
                
                playlist += f'#EXTINF:-1 tvg-logo="{match["logo"]}", {display_name}\n'
                playlist += f'#EXTVLCOPT:http-user-agent={user_agent}\n'
                playlist += f'{stream["url"]}\n'
                
            success_count += 1
            print(f"  -> Lấy thành công {len(streams)} luồng (Gồm: {', '.join([s['name'] for s in streams])})")
        else:
            print("  -> Thất bại (Không tìm thấy luồng stream nào).")
            
    if success_count == 0:
         playlist += '#EXTINF:-1 tvg-logo="", ❌ LỖI KHÔNG TÌM THẤY LINK STREAM\nhttp://localhost/error.m3u8\n'

    with open("buncha_live.m3u", "w", encoding="utf-8") as f:
        f.write(playlist)
        
    print(f"\n🎉 [HOÀN TẤT] Đã tạo file buncha_live.m3u thành công rực rỡ!")

if __name__ == "__main__":
    main()
