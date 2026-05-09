from curl_cffi import requests
from bs4 import BeautifulSoup
import re
import codecs
import time

# Khởi tạo phiên làm việc để tăng tốc độ kết nối
session = requests.Session()
user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

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
            if '-vs-' in part: slug = part; break
        if slug:
            name = re.sub(r'-\d{3,4}-\d{2}-\d{2}-\d{4}.*', '', slug)
            name = name.replace('-', ' ').title().replace(' Vs ', ' vs ')
            return name
    except: pass
    return ""

def get_matches(url):
    print(f"🚀 Đang quét trang chủ: {url}")
    try:
        response = session.get(url, impersonate="chrome110", timeout=10)
        soup = BeautifulSoup(response.text, 'html.parser')
        matches = []
        for a_tag in soup.find_all('a', href=True):
            href = a_tag['href']
            if '/truc-tiep/' in href or '/truoc-tran/' in href:
                full_link = href if href.startswith('http') else f"https://bunchatv4.net{href}"
                title = extract_name_from_url(full_link) or clean_match_title(a_tag.text)
                
                img_tag = a_tag.find('img') or (a_tag.parent.find('img') if a_tag.parent else None)
                logo_url = ""
                if img_tag:
                    logo_url = img_tag.get('data-src') or img_tag.get('src') or ""
                    if logo_url.startswith('//'): logo_url = 'https:' + logo_url
                
                if title and not any(m['url'] == full_link for m in matches):
                    matches.append({'url': full_link, 'title': title, 'logo': logo_url})
        return matches
    except Exception as e:
        print(f"❌ Lỗi trang chủ: {e}")
        return []

def extract_streams(match_url):
    """Hàm lấy link video - Ưu tiên tốc độ, không chờ đợi lâu"""
    streams = []
    seen = set()
    try:
        # Giới hạn thời gian chờ chỉ 5 giây
        res = session.get(match_url, impersonate="chrome110", timeout=5)
        html = res.text
        
        # 1. Tìm m3u8 trực tiếp trong mã nguồn (Nhanh nhất)
        raw_links = re.findall(r'(https?://[^\s"\'<>]*\.m3u8[^\s"\'<>]*)', html)
        for l in raw_links:
            link = l.replace('\\/', '/').replace('\\u0026', '&').replace('u0026', '&').replace('\\', '')
            if link not in seen:
                streams.append({'url': link, 'name': 'Luồng chính'})
                seen.add(link)

        # 2. Tìm tên BLV trong JSON/Script (Nếu có)
        blv_data = re.findall(r'["\']?(?:name|title)["\']?\s*:\s*["\']([^"\']+)["\']', html)
        # Chỉ lấy 1-2 BLV tiêu biểu để tránh treo
        if blv_data and streams:
            for i in range(min(len(streams), len(blv_data))):
                try:
                    streams[i]['name'] = codecs.decode(blv_data[i].encode(), 'unicode_escape')
                except: pass

    except: pass
    return streams

def main():
    start_time = time.time()
    matches = get_matches("https://bunchatv4.net/")
    
    if not matches:
        print("Trang web không có trận nào."); return

    playlist = "#EXTM3U\n"
    count = 0
    
    print(f"✅ Tìm thấy {len(matches)} trận. Đang lấy link tuần tự...")
    
    for match in matches:
        # Kiểm tra nếu chạy quá 5 phút thì dừng để lưu file luôn, không chạy tiếp
        if time.time() - start_time > 300: 
            print("⏳ Sắp hết thời gian cho phép, đang lưu kết quả..."); break
            
        print(f"-> {match['title']}", end=" ", flush=True)
        streams = extract_streams(match['url'])
        
        if streams:
            for s in streams:
                name = f"{match['title']} ({s['name']})" if s['name'] else match['title']
                playlist += f'#EXTINF:-1 tvg-logo="{match["logo"]}", {name}\n'
                playlist += f'#EXTVLCOPT:http-user-agent={user_agent}\n'
                playlist += f'{s["url"]}\n'
            count += 1
            print(f"[OK ({len(streams)})]")
        else:
            print("[X]")

    with open("buncha_live.m3u", "w", encoding="utf-8") as f:
        f.write(playlist)
    
    print(f"\n🎉 HOÀN TẤT trong {int(time.time() - start_time)} giây. Lấy được {count} trận.")

if __name__ == "__main__":
    main()
    
