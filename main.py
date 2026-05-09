from curl_cffi import requests
from bs4 import BeautifulSoup
import re

def clean_match_title(raw_text):
    """
    Hàm này dùng để dọn dẹp tên trận đấu.
    Chuyển các dạng: "Đội A 1 - 0 Đội B" hoặc "Đội A 2-1 Đội B" -> "Đội A vs Đội B"
    """
    # 1. Xóa khoảng trắng thừa và dấu xuống dòng
    title = re.sub(r'\s+', ' ', raw_text.strip())
    
    # 2. Tìm và thay thế tỷ số (các cụm số cách nhau bởi dấu - hoặc :) thành chữ " vs "
    # Ví dụ: nhận diện " 1 - 0 ", " 2:2 "
    title = re.sub(r'\s+\d+\s*[-:]\s*\d+\s+', ' vs ', title)
    
    return title

def get_matches(url):
    print(f"Đang quét trang chủ: {url}")
    try:
        # Dùng impersonate để giả dạng Chrome thật, không bị web chặn
        response = requests.get(url, impersonate="chrome110", timeout=15)
        soup = BeautifulSoup(response.text, 'html.parser')
        matches = []
        
        for a_tag in soup.find_all('a', href=True):
            href = a_tag['href']
            # Chỉ lấy các link dẫn vào xem trực tiếp
            if '/truc-tiep/' in href or '/truoc-tran/' in href:
                full_link = href if href.startswith('http') else f"https://bunchatv4.net{href}"
                
                # --- LẤY LOGO TRẬN ĐẤU ---
                img_tag = a_tag.find('img')
                logo_url = ""
                if img_tag:
                    # Ưu tiên lấy data-src (ảnh giấu để chống load chậm), nếu không có mới lấy src
                    logo_url = img_tag.get('data-src') or img_tag.get('data-original') or img_tag.get('src') or ""
                    if logo_url and logo_url.startswith('//'):
                        logo_url = 'https:' + logo_url
                
                # --- LẤY VÀ LÀM SẠCH TÊN TRẬN ĐẤU ---
                raw_title = a_tag.get('title') or (img_tag.get('alt') if img_tag else "")
                if not raw_title:
                    raw_title = a_tag.text # Lấy toàn bộ chữ xuất hiện trong khung trận đấu
                
                # Chạy qua hàm làm sạch ở trên để xóa tỷ số
                title = clean_match_title(raw_title)
                
                # Nếu lọc xong mà không còn chữ gì, lấy link làm tên dự phòng
                if not title or len(title) < 2:
                    title = full_link.split('/')[-1]
                
                # Chống trùng lặp (tránh quét 1 trận 2 lần)
                if not any(m['url'] == full_link for m in matches):
                    matches.append({'url': full_link, 'title': title, 'logo': logo_url})
                    
        return matches
    except Exception as e:
        print(f"Lỗi quét trang chủ: {e}")
        return []

def extract_m3u8_from_url(url):
    """
    Hàm lặn sâu vào từng trận để lôi link m3u8 ra
    """
    try:
        res = requests.get(url, impersonate="chrome110", timeout=15)
        html_content = res.text
        
        # Cách 1: Tìm thẳng link m3u8 trong mã nguồn
        links = re.findall(r'(https?://[^\s"\'<>]*\.m3u8[^\s"\'<>]*)', html_content)
        if links: return links[0]
            
        # Cách 2: Tìm link m3u8 ẩn trong các iframe (server như taoxanh, rapidlive)
        soup = BeautifulSoup(html_content, 'html.parser')
        for iframe in soup.find_all('iframe'):
            iframe_src = iframe.get('src')
            if iframe_src:
                if iframe_src.startswith('//'): iframe_src = 'https:' + iframe_src
                iframe_res = requests.get(iframe_src, impersonate="chrome110", timeout=15)
                iframe_links = re.findall(r'(https?://[^\s"\'<>]*\.m3u8[^\s"\'<>]*)', iframe_res.text)
                if iframe_links: return iframe_links[0]
                    
    except Exception as e:
        pass
    return None

def main():
    target_url = "https://bunchatv4.net/"
    matches = get_matches(target_url)
    
    if not matches:
        print("Không có trận đấu nào hoặc web chặn kết nối.")
        with open("buncha_live.m3u", "w", encoding="utf-8") as f:
            f.write('#EXTM3U\n#EXTINF:-1 tvg-logo="", ❌ HIỆN KHÔNG CÓ TRẬN ĐẤU HOẶC WEB BẢO TRÌ\nhttp://localhost/error.m3u8\n')
        return

    playlist = "#EXTM3U\n"
    success_count = 0
    
    for match in matches:
        print(f"Đang lấy link: {match['title']}")
        m3u8_link = extract_m3u8_from_url(match['url'])
        
        if m3u8_link:
            m3u8_link = m3u8_link.replace('\\', '') 
            # Dòng này gắn TÊN và LOGO vào file m3u
            playlist += f'#EXTINF:-1 tvg-logo="{match["logo"]}", {match["title"]}\n{m3u8_link}\n'
            success_count += 1
            print("  -> Lấy thành công!")
        else:
            print("  -> Thất bại (Không tìm thấy luồng stream).")
            
    if success_count == 0:
         playlist += '#EXTINF:-1 tvg-logo="", ❌ LỖI KHÔNG TÌM THẤY LINK STREAM BẤT KỲ TRẬN NÀO\nhttp://localhost/error.m3u8\n'

    with open("buncha_live.m3u", "w", encoding="utf-8") as f:
        f.write(playlist)
        
    print(f"\n[HOÀN TẤT] Đã tạo file buncha_live.m3u gồm {success_count} trận đấu!")

if __name__ == "__main__":
    main()
