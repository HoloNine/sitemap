# Sitemap Exporter

A command-line tool that finds a website's sitemap and saves every page URL in it to a CSV file.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Optional, only needed for `--browser`:

```bash
pip install playwright
python -m playwright install chromium
```

## Usage

```bash
python main.py <website> [-o output.csv] [--browser]
```

Examples:

```bash
# Basic: the output name comes from the domain, e.g. www_example_com_urls.csv
python main.py https://www.example.com

# "https://" is optional and gets added for you
python main.py example.com

# Choose your own output file
python main.py example.com -o example_pages.csv

# Fetch through a headless browser, for sites that block non-browser clients
python main.py example.com --browser
```

### When to use `--browser`

Some sites (often WordPress sites with a security plugin or firewall) drop connections from tools that don't look like a browser. When that happens, every request shows a `connection failed` warning and the run ends with `no sitemap found`. `--browser` loads the same URLs in headless Chromium through Playwright, which those filters usually let through. It's slower to start, so it's off by default. Use it only on sites you're allowed to crawl.

Run `python main.py --help` to see the built-in help.

## How it works

1. It reads `https://<site>/robots.txt` and looks for `Sitemap:` lines.
2. If there aren't any, it tries `/sitemap.xml`, `/sitemap_index.xml` and `/sitemap.xml.gz` in that order, and accepts the first one that is actually sitemap XML (not an HTML page).
3. It follows sitemap indexes into their child sitemaps and handles gzipped (`.gz`) sitemaps.
4. It removes duplicate URLs and writes a CSV with a single `url` column.

Requests time out after 10 seconds. Failed requests are retried up to 3 times for 429 and 5xx responses.

## Output

When it works, it prints something like:

```
found 1 sitemap(s): https://www.example.com/sitemap.xml
exported 312 pages to www_example_com_urls.csv
```

Example CSV:

```csv
url
https://www.example.com/
https://www.example.com/about/
```

## Errors

- It stops with exit code `1` if it can't find a sitemap or the sitemap contains no pages.
- A URL that fails to download prints a warning to stderr with the reason (for example `connection failed` or `HTTP 404`), and the run continues.
- A sitemap that fails to parse also prints a warning and the run continues.
