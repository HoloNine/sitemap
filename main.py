#!/usr/bin/env python3
"""Discover a website's sitemap and export its page URLs to CSV."""

import argparse
import csv
import gzip
import sys
from urllib.parse import urljoin, urlparse

import requests
from lxml import etree
from requests.adapters import HTTPAdapter
from urllib3.util import Retry

USER_AGENT = (
    "Mozilla/5.0 (compatible; SitemapExporter/1.0; "
    "+https://github.com/sitemap-exporter)"
)
TIMEOUT = 10
COMMON_SITEMAP_PATHS = ("/sitemap.xml", "/sitemap_index.xml", "/sitemap.xml.gz")
SITEMAP_NS = "http://www.sitemaps.org/schemas/sitemap/0.9"


def build_session() -> requests.Session:
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT, "Accept": "*/*"})
    retry = Retry(
        total=3,
        backoff_factor=1,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=("GET", "HEAD"),
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session


def normalize_site_url(url: str) -> str:
    if not urlparse(url).scheme:
        url = f"https://{url}"
    parsed = urlparse(url)
    return f"{parsed.scheme}://{parsed.netloc}"


def find_sitemap_urls(session: requests.Session, site_url: str) -> list[str]:
    robots_url = urljoin(site_url + "/", "robots.txt")
    try:
        resp = session.get(robots_url, timeout=TIMEOUT)
        if resp.ok:
            sitemaps = [
                line.split(":", 1)[1].strip()
                for line in resp.text.splitlines()
                if line.lower().startswith("sitemap:")
            ]
            if sitemaps:
                return sitemaps
    except requests.RequestException:
        pass

    for path in COMMON_SITEMAP_PATHS:
        candidate = urljoin(site_url, path)
        try:
            resp = session.head(candidate, timeout=TIMEOUT, allow_redirects=True)
            if resp.ok:
                return [candidate]
        except requests.RequestException:
            continue

    return []


def fetch_sitemap_bytes(session: requests.Session, url: str) -> bytes:
    resp = session.get(url, timeout=TIMEOUT)
    resp.raise_for_status()
    content = resp.content
    is_gzip = url.endswith(".gz") or content[:2] == b"\x1f\x8b"
    if is_gzip:
        content = gzip.decompress(content)
    return content


def parse_sitemap(
    session: requests.Session, url: str, visited: set[str], pages: list[str]
) -> None:
    if url in visited:
        return
    visited.add(url)

    try:
        content = fetch_sitemap_bytes(session, url)
    except (requests.RequestException, OSError):
        print(f"warning: failed to fetch {url}", file=sys.stderr)
        return

    try:
        root = etree.fromstring(content)
    except etree.XMLSyntaxError:
        print(f"warning: failed to parse {url}", file=sys.stderr)
        return

    tag = etree.QName(root.tag).localname

    if tag == "sitemapindex":
        for loc in root.findall(f"{{{SITEMAP_NS}}}sitemap/{{{SITEMAP_NS}}}loc"):
            if loc.text:
                parse_sitemap(session, loc.text.strip(), visited, pages)
    elif tag == "urlset":
        for loc in root.findall(f"{{{SITEMAP_NS}}}url/{{{SITEMAP_NS}}}loc"):
            if loc.text:
                pages.append(loc.text.strip())


def write_csv(pages: list[str], output_path: str) -> None:
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["url"])
        for page in pages:
            writer.writerow([page])


def default_output_path(site_url: str) -> str:
    domain = urlparse(site_url).netloc.replace(":", "_")
    safe_domain = "".join(c if c.isalnum() else "_" for c in domain)
    return f"{safe_domain}_urls.csv"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Discover a website's sitemap and export its URLs to CSV."
    )
    parser.add_argument("url", help="Website URL, e.g. https://example.com")
    parser.add_argument("-o", "--output", help="Output CSV path")
    args = parser.parse_args()

    site_url = normalize_site_url(args.url)
    session = build_session()

    sitemap_urls = find_sitemap_urls(session, site_url)
    if not sitemap_urls:
        print(f"error: no sitemap found for {site_url}", file=sys.stderr)
        sys.exit(1)

    print(f"found {len(sitemap_urls)} sitemap(s): {', '.join(sitemap_urls)}")

    visited: set[str] = set()
    pages: list[str] = []
    for sitemap_url in sitemap_urls:
        parse_sitemap(session, sitemap_url, visited, pages)

    pages = list(dict.fromkeys(pages))

    if not pages:
        print(f"error: no pages found in sitemap(s) for {site_url}", file=sys.stderr)
        sys.exit(1)

    output_path = args.output or default_output_path(site_url)
    write_csv(pages, output_path)

    print(f"exported {len(pages)} pages to {output_path}")


if __name__ == "__main__":
    main()
