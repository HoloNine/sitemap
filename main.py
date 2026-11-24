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


def stderr_log(message: str) -> None:
    print(f"warning: {message}", file=sys.stderr)


class FetchError(Exception):
    """A URL could not be fetched; the message says why."""


class HttpFetcher:
    """Fetches URLs with plain HTTP requests."""

    def __init__(self) -> None:
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENT, "Accept": "*/*"})
        retry = Retry(
            total=3,
            backoff_factor=1,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=("GET", "HEAD"),
        )
        adapter = HTTPAdapter(max_retries=retry)
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)

    def fetch(self, url: str) -> bytes:
        try:
            resp = self.session.get(url, timeout=TIMEOUT)
        except requests.ConnectionError as exc:
            raise FetchError(f"connection failed ({type(exc).__name__})") from exc
        except requests.RequestException as exc:
            raise FetchError(str(exc)) from exc
        if not resp.ok:
            raise FetchError(f"HTTP {resp.status_code}")
        return resp.content

    def __enter__(self) -> "HttpFetcher":
        return self

    def __exit__(self, *exc) -> None:
        self.session.close()


class PlaywrightMissing(Exception):
    """--browser was requested but Playwright isn't installed."""


class NoSitemapError(Exception):
    """No sitemap could be found for the site."""


class BrowserFetcher:
    """Fetches URLs through a headless Chromium browser (Playwright).

    Useful for sites that reject non-browser clients.
    """

    def __enter__(self) -> "BrowserFetcher":
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            raise PlaywrightMissing(
                "browser mode needs Playwright: "
                "pip install playwright && python -m playwright install chromium"
            ) from None
        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch()
        self._context = self._browser.new_context()
        self._page = self._context.new_page()
        return self

    def __exit__(self, *exc) -> None:
        self._browser.close()
        self._pw.stop()

    def fetch(self, url: str) -> bytes:
        from playwright.sync_api import Error as PlaywrightError

        try:
            resp = self._page.goto(url, timeout=TIMEOUT * 3 * 1000)
        except PlaywrightError:
            # Navigation fails for downloads (e.g. .gz files); fall back to the
            # context's request API, which shares the browser's cookies.
            try:
                resp = self._context.request.get(url, timeout=TIMEOUT * 3 * 1000)
            except PlaywrightError as exc:
                raise FetchError(str(exc).splitlines()[0]) from exc
        if resp is None:
            raise FetchError("no response")
        if not resp.ok:
            raise FetchError(f"HTTP {resp.status}")
        return resp.body()


def normalize_site_url(url: str) -> str:
    if not urlparse(url).scheme:
        url = f"https://{url}"
    parsed = urlparse(url)
    return f"{parsed.scheme}://{parsed.netloc}"


def find_sitemap_urls(fetcher, site_url: str, log=stderr_log) -> list[str]:
    robots_url = urljoin(site_url + "/", "robots.txt")
    try:
        text = fetcher.fetch(robots_url).decode("utf-8", errors="replace")
        sitemaps = [
            line.split(":", 1)[1].strip()
            for line in text.splitlines()
            if line.lower().startswith("sitemap:")
        ]
        if sitemaps:
            return sitemaps
    except FetchError as exc:
        log(f"{robots_url}: {exc}")

    for path in COMMON_SITEMAP_PATHS:
        candidate = urljoin(site_url, path)
        try:
            content = decompress_if_gzip(candidate, fetcher.fetch(candidate))
        except FetchError as exc:
            log(f"{candidate}: {exc}")
            continue
        except OSError:
            continue
        if b"<urlset" in content or b"<sitemapindex" in content:
            return [candidate]

    return []


def decompress_if_gzip(url: str, content: bytes) -> bytes:
    # Check the gzip magic bytes rather than the ".gz" suffix: some clients
    # (browsers in particular) already decompress the body for us.
    if content[:2] == b"\x1f\x8b":
        content = gzip.decompress(content)
    return content


def parse_sitemap(
    fetcher, url: str, visited: set[str], pages: list[str], log=stderr_log
) -> None:
    if url in visited:
        return
    visited.add(url)

    try:
        content = decompress_if_gzip(url, fetcher.fetch(url))
    except (FetchError, OSError) as exc:
        log(f"failed to fetch {url}: {exc}")
        return

    try:
        root = etree.fromstring(content)
    except etree.XMLSyntaxError:
        log(f"failed to parse {url}")
        return

    tag = etree.QName(root.tag).localname

    if tag == "sitemapindex":
        for loc in root.findall(f"{{{SITEMAP_NS}}}sitemap/{{{SITEMAP_NS}}}loc"):
            if loc.text:
                parse_sitemap(fetcher, loc.text.strip(), visited, pages, log)
    elif tag == "urlset":
        for loc in root.findall(f"{{{SITEMAP_NS}}}url/{{{SITEMAP_NS}}}loc"):
            if loc.text:
                pages.append(loc.text.strip())


def collect_pages(
    site_url: str, use_browser: bool = False, log=stderr_log
) -> tuple[list[str], list[str]]:
    """Find the site's sitemaps and return (sitemap_urls, unique page URLs).

    Raises NoSitemapError if no sitemap is found, and PlaywrightMissing if
    browser mode is requested without Playwright installed.
    """
    fetcher_cls = BrowserFetcher if use_browser else HttpFetcher
    with fetcher_cls() as fetcher:
        sitemap_urls = find_sitemap_urls(fetcher, site_url, log)
        if not sitemap_urls:
            raise NoSitemapError(f"no sitemap found for {site_url}")
        visited: set[str] = set()
        pages: list[str] = []
        for sitemap_url in sitemap_urls:
            parse_sitemap(fetcher, sitemap_url, visited, pages, log)
    return sitemap_urls, list(dict.fromkeys(pages))


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
    parser.add_argument(
        "--browser",
        action="store_true",
        help="Fetch through a headless browser (Playwright), for sites that "
        "block plain HTTP clients",
    )
    args = parser.parse_args()

    site_url = normalize_site_url(args.url)

    try:
        sitemap_urls, pages = collect_pages(site_url, args.browser)
    except PlaywrightMissing as exc:
        sys.exit(f"error: {exc}")
    except NoSitemapError as exc:
        print(f"error: {exc}", file=sys.stderr)
        if not args.browser:
            print("hint: if the site blocks bots, try --browser", file=sys.stderr)
        sys.exit(1)

    print(f"found {len(sitemap_urls)} sitemap(s): {', '.join(sitemap_urls)}")

    if not pages:
        print(f"error: no pages found in sitemap(s) for {site_url}", file=sys.stderr)
        sys.exit(1)

    output_path = args.output or default_output_path(site_url)
    write_csv(pages, output_path)

    print(f"exported {len(pages)} pages to {output_path}")


if __name__ == "__main__":
    main()
