# -*- coding: utf-8 -*-
import re, time, requests
from bs4 import BeautifulSoup
from urllib.parse import quote

WIKI_HOST = "https://vi.wikipedia.org"

# Thêm redirects=1 để API tự follow redirect, giữ prop=... như cũ
API_PARSE = (
    WIKI_HOST
    + "/w/api.php?action=parse&page={title}&prop=text|links&redirects=1&format=json"
)

UA = "UET-AlumniGraph/1.0"
TIMEOUT = 10
HEADERS = {"User-Agent": UA}

EDU_KEYS = [
    "Giáo dục", "Học vấn", "Alma mater",
    "Trường theo học", "Đào tạo", "Trường", "Cơ sở đào tạo"
]


def fetch_parse_html(title, sleep=0.2, timeout=TIMEOUT):
    """
    Gọi MediaWiki API để lấy HTML + title chuẩn (sau redirect).

    Trả về:
        html        : chuỗi HTML thô của trang
        final_title : tiêu đề chuẩn sau redirect (ví dụ 'Đại học Duke')
                      nếu không lấy được thì fallback về title đầu vào.
    """
    url = API_PARSE.format(title=quote(title))
    r = requests.get(url, headers=HEADERS, timeout=timeout)
    r.raise_for_status()
    data = r.json()

    html = None
    final_title = title

    if "parse" in data:
        parse = data["parse"]
        # html như cũ
        if "text" in parse:
            text_obj = parse["text"]
            # format=legacy: text là dict {"*": "..."}
            if isinstance(text_obj, dict):
                html = next(iter(text_obj.values()))
            elif isinstance(text_obj, str):
                html = text_obj

        # lấy title chuẩn từ API (sau redirect)
        pt = parse.get("title")
        if isinstance(pt, str) and pt.strip():
            final_title = pt.strip()

    time.sleep(sleep)
    return html, final_title


def soup_from_html(html):
    return BeautifulSoup(html, "html.parser") if html else None


def normalize(t):
    if not t:
        return None
    return re.sub(r"\s+", " ", t).strip()


def is_person_page(soup):
    if not soup:
        return False
    infobox = soup.find("table", class_=lambda c: c and "infobox" in c)
    if not infobox:
        return False
    for tr in infobox.find_all("tr"):
        th = tr.find("th")
        if th and re.search(r"\bSinh\b", th.get_text(strip=True), flags=re.I):
            return True
    return False


def extract_page_links(soup):
    out = []
    if not soup:
        return out
    content = soup.find("div", id="mw-content-text") or soup
    seen = set()
    for a in content.find_all("a", href=True):
        href = a["href"]
        if href.startswith("/wiki/") and not (":" in href or "#" in href):
            title = normalize(a.get("title") or a.get_text(strip=True))
            if title and title not in seen:
                seen.add(title)
                out.append(title)
    return out


def extract_person_education(soup):
    # Return list of (university_title, year?) from a person page.
    out = []
    if not soup:
        return out
    infobox = soup.find("table", class_=lambda c: c and "infobox" in c)
    if not infobox:
        return out

    for tr in infobox.find_all("tr"):
        th = tr.find("th")
        td = tr.find("td")
        if not th or not td:
            continue
        key = th.get_text(" ", strip=True)
        if key not in EDU_KEYS:
            continue

        uni_titles = []
        for a in td.find_all("a", href=True):
            href = a["href"]
            if href.startswith("/wiki/") and not (":" in href or "#" in href):
                uni_titles.append(
                    normalize(a.get("title") or a.get_text(strip=True))
                )

        text = td.get_text(" ", strip=True)
        years = re.findall(r"\b(?:19|20)\d{2}\b", text)
        year = int(years[0]) if years else None

        for ut in uni_titles:
            if ut:
                out.append((ut, year))
    return out
