from curl_cffi import requests
from bs4 import BeautifulSoup
import re

def get_matches(url):
    print(f"Đang quét trang chủ: {url}")
    try:
        # Impersonate 'chrome110' giúp qua mặt Cloudflare cực tốt
        response = requests.get(url, impersonate="chrome110", timeout=15)
        soup = BeautifulSoup(response.text, 'html.parser')
        matches = []
        
        for a_tag in soup.find_all('a', href=True):
            href = a_tag['href']
            if '/truc-tiep/' in href or '/truoc-tran/' in href:
                full_link = href if href.startswith('http') else f"https://bunchatv4.net{href}"
                img_tag = a_tag.find('img')
                logo_url = img_tag['src'] if img_tag and 'src' in img_tag.attrs else ""
                title = a_tag.get('title') or a_tag.text.strip().replace('\n', ' ')
                
                if not any(m['url'] == full_link for m in matches):
                    matches.append({'url': full_link, 'title': title, 'logo': logo_url})
        return matches
    except Exception as e:
        print(f"Lỗi quét trang chủ: {e}")
        return []

def extract_m3u8_from_url(url):
    try:
        # Tải mã nguồn trang xem trực tiếp
        res = requests.get(url, impersonate="chrome110", timeout=15)
        html_content = res.text
        
        # CÁCH 1: Tìm link m3u8 nằm thẳng trong mã nguồn trang
        # Regex này sẽ tìm mọi chuỗi bắt đầu bằng http và kết thúc bằng .m3u8 (kèm theo token nếu có)
        links = re.findall(r'(https?://[^\s"\'<>]*\.m3u8[^\s"\'<>]*)', html_content)
        if links:
            return links[0] # Lấy link đầu tiên tìm được
            
        # CÁCH 2: Tìm link m3u8 ẩn trong các iframe (khung phát video nhúng)
        soup = BeautifulSoup(html_content, 'html.parser')
        for iframe in soup.find_all('iframe'):
            iframe_src = iframe.get('src')
            if iframe_src:
                # Sửa link iframe nếu nó bị thiếu https:
                if iframe_src.startswith('//'):
                    iframe_src = 'https:' + iframe_src
                
                iframe_res = requests.get(iframe_src, impersonate="chrome110", timeout=15)
                iframe_links = re.findall(r'(https?://[^\s"\'<>]*\.m3u8[^\s"\'<>]*)', iframe_res.text)
                if iframe_links:
                    return iframe_links[0]
                    
    except Exception as e:
        print(f"Lỗi khi moi link từ {url}: {e}")
    return None

def main():
    target_url = "https://bunchatv4.net/"
    matches = get_matches(target_url)
    
    if not matches:
        print("Không có trận đấu nào hoặc web chặn kết nối.")
        # Tạo file báo lỗi lên app TV
        with open("buncha_live.m3u", "w", encoding="utf-8") as f:
            f.write('#EXTM3U\n#EXTINF:-1 tvg-logo="", ❌ HIỆN KHÔNG CÓ TRẬN ĐẤU HOẶC WEB ĐANG BẢO TRÌ\nhttp://localhost/error.m3u8\n')
        return

    playlist = "#EXTM3U\n"
    success_count = 0
    
    for match in matches:
        print(f"Đang moi link: {match['title']}")
        m3u8_link = extract_m3u8_from_url(match['url'])
        
        if m3u8_link:
            # Xử lý dọn dẹp link nếu bị dính ký tự thừa do cắt bằng regex
            m3u8_link = m3u8_link.replace('\\', '') 
            playlist += f'#EXTINF:-1 tvg-logo="{match["logo"]}", {match["title"]}\n{m3u8_link}\n'
            success_count += 1
            print("  -> Có link!")
        else:
            print("  -> Không tìm thấy m3u8 ẩn trong mã nguồn.")
            
    if success_count == 0:
         playlist += '#EXTINF:-1 tvg-logo="", ❌ TÌM ĐƯỢC TRẬN NHƯNG KHÔNG ĐỌC ĐƯỢC LINK VIDEO DO BẢO MẬT\nhttp://localhost/error.m3u8\n'

    with open("buncha_live.m3u", "w", encoding="utf-8") as f:
        f.write(playlist)
    print(f"\nHOÀN TẤT! Đã lấy thành công {success_count} trận.")

if __name__ == "__main__":
    main()
