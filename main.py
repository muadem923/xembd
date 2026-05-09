from curl_cffi import requests
from bs4 import BeautifulSoup
import re

def extract_name_from_url(url):
    """Tuyệt chiêu: Ưu tiên bóc tách tên 2 đội trực tiếp từ link gốc"""
    try:
        parts = [p for p in url.split('/') if p]
        slug = ""
        # Tìm đoạn có chứa chữ '-vs-' (ví dụ: chinese-taipei-vs-japan)
        for part in parts:
            if '-vs-' in part:
                slug = part
                break
        
        if slug:
            # Cắt bỏ phần ngày tháng giờ ở đuôi (ví dụ: -2300-09-05-2026)
            name = re.sub(r'-\d{3,4}-\d{2}-\d{2}-\d{4}.*', '', slug)
            # Thay gạch ngang thành dấu cách, viết hoa chữ cái đầu
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
                
                # --- 1. LẤY TÊN TRẬN CHUẨN 100% TỪ LINK ---
                title = extract_name_from_url(full_link)
                
                # Nếu bóc từ link thất bại (hiếm), mới mò HTML như cũ
                if not title:
                    raw_title = a_tag.get('title') or a_tag.text.strip()
                    title = re.sub(r'\s+', ' ', raw_title)
                    title = re.sub(r'\s+\d+\s*[-:]\s*\d+\s+', ' vs ', title)
                    if title.lower() in ['bóng đá', 'trực tiếp', 'trang chủ']: 
                        title = full_link.split('/')[-1]

                # --- 2. TRUY TÌM LOGO CHUẨN (Loại bỏ logo quả bóng) ---
                imgs = a_tag.find_all('img')
                if not imgs and a_tag.parent:
                    imgs = a_tag.parent.find_all('img')
                
                logo_url = ""
                for img in imgs:
                    src = img.get('data-src') or img.get('data-original') or img.get('src') or ""
                    # Lọc bỏ các ảnh chứa chữ categories, icon, logo web chung
                    if src and '/categories/' not in src and 'icon' not in src:
                        logo_url = src
                        if logo_url.startswith('//'):
                            logo_url = 'https:' + logo_url
                        break # Tìm được 1 ảnh hợp lệ là dừng luôn
                
                # --- Thêm vào danh sách (chống trùng) ---
                # Chỉ thêm nếu tên trận có ý nghĩa (chứa chữ cái)
                if title and re.search('[a-zA-Z]', title):
                    if not any(m['url'] == full_link for m in matches):
                        matches.append({'url': full_link, 'title': title, 'logo': logo_url})
                    
        return matches
    except Exception as e:
        print(f"Lỗi quét trang chủ: {e}")
        return []

def extract_m3u8_from_url(url):
    """Lặn sâu vào từng trận để lôi link video m3u8 ra"""
    try:
        res = requests.get(url, impersonate="chrome110", timeout=15)
        html_content = res.text
        
        links = re.findall(r'(https?://[^\s"\'<>]*\.m3u8[^\s"\'<>]*)', html_content)
        if links: return links[0]
            
        soup = BeautifulSoup(html_content, 'html.parser')
        for iframe in soup.find_all('iframe'):
            iframe_src = iframe.get('src')
            if iframe_src:
                if iframe_src.startswith('//'): iframe_src = 'https:' + iframe_src
                iframe_res = requests.get(iframe_src, impersonate="chrome110", timeout=15)
                iframe_links = re.findall(r'(https?://[^\s"\'<>]*\.m3u8[^\s"\'<>]*)', iframe_res.text)
                if iframe_links: return iframe_links[0]
                    
    except Exception:
        pass
    return None

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
    
    print(f"✅ Đã tìm thấy {len(matches)} trận đấu. Bắt đầu lấy link video...")
    
    for match in matches:
        print(f"Đang lấy: {match['title']}")
        m3u8_link = extract_m3u8_from_url(match['url'])
        
        if m3u8_link:
            m3u8_link = m3u8_link.replace('\\', '') 
            playlist += f'#EXTINF:-1 tvg-logo="{match["logo"]}", {match["title"]}\n{m3u8_link}\n'
            success_count += 1
            print("  -> Lấy thành công!")
        else:
            print("  -> Thất bại (Không tìm thấy luồng stream).")
            
    if success_count == 0:
         playlist += '#EXTINF:-1 tvg-logo="", ❌ LỖI KHÔNG TÌM THẤY LINK STREAM\nhttp://localhost/error.m3u8\n'

    with open("buncha_live.m3u", "w", encoding="utf-8") as f:
        f.write(playlist)
        
    print(f"\n🎉 [HOÀN TẤT] Đã tạo file buncha_live.m3u gồm {success_count} trận đấu!")

if __name__ == "__main__":
    main()
