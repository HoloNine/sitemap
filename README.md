# Sitemap Exporter

A command-line tool that finds a website's sitemap and saves every page URL in it to a CSV file.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Usage

```bash
python main.py <website> [-o output.csv]
```

Examples:

```bash
# Basic: the output name comes from the domain, e.g. www_example_com_urls.csv
python main.py https://www.example.com

# "https://" is optional and gets added for you
python main.py example.com

# Choose your own output file
python main.py example.com -o example_pages.csv
```

Run `python main.py --help` to see the built-in help.

## How it works

1. It reads `https://<site>/robots.txt` and looks for `Sitemap:` lines.
2. If there aren't any, it tries `/sitemap.xml`, `/sitemap_index.xml` and `/sitemap.xml.gz` in that order.
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
- A sitemap that fails to download or parse only prints a warning to stderr, and the run continues.
