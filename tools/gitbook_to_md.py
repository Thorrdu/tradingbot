import argparse
import os
import re
import sys
import time
import json
import zipfile
from urllib.parse import urljoin, urlparse, urlunparse, urldefrag
import requests
from bs4 import BeautifulSoup
from markdownify import markdownify as md
from tenacity import retry, wait_exponential, stop_after_attempt
from tqdm import tqdm

HEADERS = {
    "User-Agent": "SiteExporter/1.0 (+for personal archival; contact if issues)"
}

GITBOOK_SEARCH_CANDIDATES = [
    "search.json",                # legacy gitbook
    "assets/search.json",         # some builds
    "_next/static/chunks",        # modern GitBook uses Next; we’ll still parse DOM
]

def sanitize_filename(name: str) -> str:
    name = name.strip().replace("/", "-").replace("\\", "-")
    name = re.sub(r"[\:\*\?\"<>\|\#\%\{\}\$\!\@\+`=]+", "-", name)
    name = re.sub(r"\s+", " ", name).strip()
    name = name[:120] if len(name) > 120 else name
    return name or "page"

def normalize_url(url: str) -> str:
    url, _ = urldefrag(url)
    p = urlparse(url)
    # remove querystrings that are often analytics only
    return urlunparse((p.scheme, p.netloc, p.path, "", "", ""))

def is_same_site(root, url):
    r = urlparse(root)
    u = urlparse(url)
    return (u.netloc == r.netloc) and u.scheme in ("http", "https")

def ensure_dir(path):
    os.makedirs(path, exist_ok=True)

def extract_sidebar_links(soup, base_url):
    """
    Try to extract sidebar/nav links in GitBook layout to preserve order & hierarchy.
    """
    links = []
    # GitBook often uses nav[aria-label="Table of contents"] or aside nav
    candidates = soup.select('nav[aria-label], aside nav, aside, nav')
    seen = set()
    for nav in candidates:
        for a in nav.select('a[href]'):
            href = a.get("href")
            if not href:
                continue
            href = urljoin(base_url, href)
            href = normalize_url(href)
            if not is_same_site(base_url, href):
                continue
            if href in seen:
                continue
            seen.add(href)
            title = a.get_text(" ", strip=True) or href
            links.append({"title": title, "url": href})
        if links:
            break  # first plausible nav is usually correct
    return links

@retry(wait=wait_exponential(multiplier=1, min=1, max=10), stop=stop_after_attempt(5))
def get(url):
    r = requests.get(url, headers=HEADERS, timeout=20)
    # Handle GitBook rate limiting gracefully
    if r.status_code in (429, 503):
        raise requests.HTTPError(f"Transient HTTP {r.status_code}")
    r.raise_for_status()
    return r

def html_to_markdown(html: str, base_url: str) -> str:
    # Remove edit buttons, nav, and other non-content elements
    soup = BeautifulSoup(html, "html.parser")

    # Common GitBook wrappers
    for selector in [
        "nav", "aside", "header", "footer",
        'div[class*="ToC"]', 'div[class*="toc"]',
        'div[class*="GitBook"]',
        'div[class*="search"]',
        'div[class*="feedback"]',
        'div[data-component="Feedback"]',
    ]:
        for el in soup.select(selector):
            el.decompose()

    # Main content candidates
    content = soup.select_one('main, article, section[id*="content"], div[class*="content"]')
    if not content:
        content = soup.body or soup

    # Fix relative links and images
    for tag in content.find_all(["a", "img"]):
        attr = "href" if tag.name == "a" else "src"
        if tag.has_attr(attr):
            tag[attr] = urljoin(base_url, tag[attr])

    markdown = md(str(content), heading_style="ATX", strip=["style", "script"])

    # Trim excessive blank lines
    markdown = re.sub(r"\n{3,}", "\n\n", markdown).strip()
    return markdown

def derive_title(soup: BeautifulSoup) -> str:
    title = ""
    if soup.title and soup.title.text:
        title = soup.title.text.strip()
    if not title:
        h1 = soup.find(["h1"])
        if h1:
            title = h1.get_text(strip=True)
    title = title or "Untitled"
    # Remove site suffixes like " – Pionex API Docs"
    title = re.sub(r"\s+[–|-]\s+.*$", "", title).strip() or "Untitled"
    return title

def write_markdown(out_dir, rel_path, title, markdown):
    ensure_dir(os.path.join(out_dir, os.path.dirname(rel_path)))
    header = f"# {title}\n\n" if not markdown.lstrip().startswith("# ") else ""
    with open(os.path.join(out_dir, rel_path), "w", encoding="utf-8") as f:
        f.write(header + markdown + "\n")

def guess_relpath(root, page_url, page_title):
    """
    Use path segments to create folders; fallback to title-based filename.
    """
    rp = urlparse(page_url).path
    # Remove trailing slash
    if rp.endswith("/"):
        rp = rp[:-1]
    if not rp or rp == urlparse(root).path.rstrip("/"):
        fname = "index.md"
        return fname
    parts = [p for p in rp.split("/") if p]
    # Last part becomes filename, others are directories
    if parts:
        filename = sanitize_filename(parts[-1]) + ".md"
        directory = "/".join(sanitize_filename(p) for p in parts[:-1])
        rel = os.path.join(directory, filename) if directory else filename
        return rel
    # Fallback to title
    return sanitize_filename(page_title) + ".md"

def zip_dir(dir_path, zip_path):
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        for root, _, files in os.walk(dir_path):
            for file in files:
                fp = os.path.join(root, file)
                z.write(fp, os.path.relpath(fp, dir_path))

def main():
    parser = argparse.ArgumentParser(description="Export GitBook docs to Markdown and ZIP.")
    parser.add_argument("--root", required=True, help="Root URL of the GitBook site (e.g., https://.../apidocs/).")
    parser.add_argument("--out", required=True, help="Output directory for Markdown files.")
    parser.add_argument("--zip", action="store_true", help="Also create a ZIP archive of the output folder.")
    parser.add_argument("--delay", type=float, default=0.5, help="Delay between requests (seconds).")
    args = parser.parse_args()

    root = args.root if args.root.endswith("/") else args.root + "/"
    out_dir = os.path.abspath(args.out)
    ensure_dir(out_dir)

    print(f"[+] Fetching root: {root}")
    r = get(root)
    soup = BeautifulSoup(r.text, "html.parser")

    # Try to extract sidebar-ordered links first
    sidebar_links = extract_sidebar_links(soup, root)
    urls = []
    if sidebar_links:
        urls = [normalize_url(item["url"]) for item in sidebar_links]
        # Ensure root page is first
        if normalize_url(root) not in urls:
            urls.insert(0, normalize_url(root))
    else:
        # Fallback: crawl all internal links found on root page
        print("[!] Sidebar not found; falling back to shallow crawl.")
        found = set([normalize_url(root)])
        queue = [normalize_url(root)]
        while queue:
            current = queue.pop(0)
            try:
                rr = get(current)
            except Exception as e:
                print(f"[warn] {current}: {e}")
                continue
            s = BeautifulSoup(rr.text, "html.parser")
            for a in s.select("a[href]"):
                href = urljoin(current, a.get("href"))
                href = normalize_url(href)
                if is_same_site(root, href) and href not in found:
                    found.add(href)
                    queue.append(href)
            time.sleep(args.delay)
        urls = list(found)

    # De-duplicate while preserving order
    seen = set()
    ordered = []
    for u in urls:
        if u not in seen:
            seen.add(u)
            ordered.append(u)

    pages = []
    for u in ordered:
        try:
            rr = get(u)
            s = BeautifulSoup(rr.text, "html.parser")
            title = derive_title(s)
            markdown = html_to_markdown(rr.text, u)
            relpath = guess_relpath(root, u, title)
            write_markdown(out_dir, relpath, title, markdown)
            pages.append({"title": title, "url": u, "path": relpath})
            print(f"[ok] {u} -> {relpath}")
        except Exception as e:
            print(f"[err] {u}: {e}")
        time.sleep(args.delay)

    # Write an index file with mapping
    with open(os.path.join(out_dir, "_export.json"), "w", encoding="utf-8") as f:
        json.dump(pages, f, ensure_ascii=False, indent=2)

    # README
    with open(os.path.join(out_dir, "README.md"), "w", encoding="utf-8") as f:
        f.write("# Exported GitBook\n\n")
        f.write(f"Source: {root}\n\n")
        f.write("This folder contains Markdown conversions of each page.\n")

    if args.zip:
        zip_path = os.path.abspath(out_dir) + ".zip"
        zip_dir(out_dir, zip_path)
        print(f"[+] ZIP created at: {zip_path}")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(1)
