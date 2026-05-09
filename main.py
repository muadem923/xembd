from curl_cffi import requests
from bs4 import BeautifulSoup
import re

def clean_match_title(raw_text):
    """Làm sạch tên trận đấu và xóa tỷ số"""
    if not raw_text: return ""
    # Xóa khoảng trắng thừa
    title = re.sub(r'\s+', ' ', raw_text.strip())
    # Nhận diện và thay thế tỷ số thành chữ 'vs' (ví dụ: 1-0, 2:2 -> vs)
    title = re.sub(r'\s+\d+\s*[-:]\s*\d+\s+', ' vs ', title)
    return title

def extract_name_from_url(url):
    """Tuyệt chiêu dịch ngược tên trận từ đường link nếu web giấu text"""
    try:
        parts = [p for p in url.split('/') if p]
        # Lấy đoạn slug (ví dụ: chinese-taipei-vs-japan-2300-09-05-2026)
        slug = parts[-2] if parts[-1].isdigit() else parts[-1]
        
        # Xóa cụm giờ-ngày-tháng-năm ở đuôi đi
        name = re.sub(r'-\d{3,4}-\d{2}-\d{2}-\d{4}.*', '', slug)
        
        # Thay dấu gạch ngang thành dấu cách, viết hoa chữ cái đầu
        name = name.replace('-', ' ').title()
        name = name.replace(' Vs ', ' vs ') # Sửa lại chữ vs cho chuẩn
        return name
    except:
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
                
                # --- 1. TRUY TÌM LOGO (Mở rộng phạm vi tìm kiếm nhiều tầng) ---
                img_tag = a_tag.find('img')
                # Nếu trong thẻ <a> không có, mò ra thẻ cha bên ngoài
                if not img_tag and a_tag.parent:
                    img_tag = a_tag.parent.find('img')
                # Mò tiếp ra thẻ ông nội
                if not img_tag and a_tag.parent and a_tag.parent.parent:
                    img_tag = a_tag.parent.parent.find('img')

                logo_url = ""
                if img_tag:
                    logo_url = img_tag.get('data-src') or img_tag.get('data-original') or img_tag.get('src') or ""
                    if logo_url and logo_url.startswith('//'):
                        logo_url = 'https:' + logo_url
                
                # --- 2. TRUY TÌM TÊN TRẬN ĐẤU ---
                raw_title = a_tag.get('title') or (img_tag.get('alt') if img_tag else "")
                if not raw_title:
                    raw_title = a_tag.text
                
                # Nếu text vẫn trống, mò ra thẻ cha để lấy chữ
                if not raw_title.strip() and a_tag.parent:
                    raw_title = a_tag.parent.text
                
                title = clean_match_title(raw_title)
                
                # --- 3. CHỐT CHẶN CUỐI (Phân tích link nếu tên bị lỗi thành số) ---
                if not title or len(title) < 5 or title.isdigit():
                    title = extract_name_from_url(full_link)
                
                # Tránh lấy trùng 1 trận 2 lần
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
        
        # Cách 1: Tìm thẳng link m3u8 trong mã nguồn
        links = re.findall(r'(https?://[^\s"\'<>]*\.m3u8[^\s"\'<>]*)', html_content)
        if links: return links[0]
            
        # Cách 2: Tìm link m3u8 ẩn trong các iframe
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
        # Tạo file báo lỗi thẳng vào ứng dụng TV
        with open("buncha_live.m3u", "w", encoding="utf-8") as f:
            f.write('#EXTM3U\n#EXTINF:-1 tvg-logo="", ❌ HIỆN KHÔNG CÓ TRẬN ĐẤU HOẶC WEB BẢO TRÌ\nhttp://localhost/error.m3u8\n')
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
         playlist += '#EXTINF:-1 tvg-logo="", ❌ LỖI KHÔNG TÌM THẤY LINK STREAM BẤT KỲ TRẬN NÀO\nhttp://localhost/error.m3u8\n'

    with open("buncha_live.m3u", "w", encoding="utf-8") as f:
        f.write(playlist)
        
    print(f"\n🎉 [HOÀN TẤT] Đã tạo file buncha_live.m3u gồm {success_count} trận đấu!")

if __name__ == "__main__":
    main()
