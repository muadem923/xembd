import requests
from bs4 import BeautifulSoup
from seleniumwire import webdriver
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
import time

def get_matches(url):
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
        response = requests.get(url, headers=headers)
        soup = BeautifulSoup(response.text, 'html.parser')
        matches = []
        for a_tag in soup.find_all('a', href=True):
            href = a_tag['href']
            if '/truc-tiep/' in href or '/truoc-tran/' in href:
                full_link = href if href.startswith('http') else f"https://xembongda.digital/{href}"
                img_tag = a_tag.find('img')
                logo_url = img_tag['src'] if img_tag and 'src' in img_tag.attrs else ""
                title = a_tag.get('title') or a_tag.text.strip().replace('\n', ' ')
                if not any(m['url'] == full_link for m in matches):
                    matches.append({'url': full_link, 'title': title, 'logo': logo_url})
        return matches
    except Exception:
        return []

def main():
    url = "https://xembongda.digital/"
    matches = get_matches(url)
    
    if not matches:
        print("Hiện tại không có trận đấu nào.")
        return
    
    options = webdriver.ChromeOptions()
    options.add_argument('--headless')
    options.add_argument('--no-sandbox') 
    options.add_argument('--disable-dev-shm-usage') 
    options.add_argument('--mute-audio')
    
    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
    playlist = "#EXTM3U\n"
    
    for match in matches:
        try:
            driver.get(match['url'])
            time.sleep(12) # Chờ 12s để video load
            for request in driver.requests:
                if request.response and '.m3u8' in request.url:
                    playlist += f'#EXTINF:-1 tvg-logo="{match["logo"]}", {match["title"]}\n{request.url}\n'
                    break
            del driver.requests
        except Exception:
            pass
            
    driver.quit()
    
    # Ghi file với tên cố định là buncha_live.m3u
    with open("buncha_live.m3u", "w", encoding="utf-8") as f:
        f.write(playlist)
    print("Đã tạo/cập nhật thành công file buncha_live.m3u")

if __name__ == "__main__":
    main()
