"""Streamlit web UI for the sitemap exporter.

Run with:  streamlit run app.py
"""

import csv
import io

import streamlit as st

from main import (
    NoSitemapError,
    PlaywrightMissing,
    collect_pages,
    default_output_path,
    normalize_site_url,
)

st.set_page_config(page_title="Sitemap Exporter", page_icon="🗺️", layout="wide")


@st.cache_data(ttl=600, show_spinner=False)
def cached_collect(site_url: str, use_browser: bool):
    """Run the exporter and cache results for 10 minutes per (site, mode).

    Returns (sitemap_urls, pages, warnings, error); error is a message when no
    sitemap was found, so the warnings explaining why can still be shown.
    """
    warnings: list[str] = []
    try:
        sitemap_urls, pages = collect_pages(site_url, use_browser, log=warnings.append)
    except NoSitemapError as exc:
        return [], [], warnings, str(exc)
    return sitemap_urls, pages, warnings, None


def to_csv_bytes(pages: list[str]) -> bytes:
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["url"])
    writer.writerows([p] for p in pages)
    return buf.getvalue().encode("utf-8")


st.title("Sitemap Exporter")
st.caption("Find a website's sitemap and export every page URL to CSV.")

with st.form("export"):
    url = st.text_input("Website", placeholder="example.com")
    use_browser = st.checkbox(
        "Use headless browser",
        help="Fetch through Chromium (Playwright). Use this for sites that "
        "block non-browser clients — only on sites you're allowed to crawl.",
    )
    submitted = st.form_submit_button("Find pages", type="primary")

if submitted:
    if not url.strip():
        st.warning("Enter a website first.")
        st.stop()

    site_url = normalize_site_url(url.strip())
    try:
        with st.spinner(f"Reading sitemaps for {site_url}…"):
            sitemap_urls, pages, warnings, error = cached_collect(site_url, use_browser)
    except PlaywrightMissing as exc:
        st.error(str(exc))
        st.stop()

    if error:
        st.session_state.pop("result", None)
        st.error(error.capitalize() + ".")
        for w in warnings:
            st.text(w)
        if not use_browser:
            st.info("If the site blocks bots, tick **Use headless browser** and try again.")
        st.stop()

    st.session_state["result"] = (site_url, sitemap_urls, pages, warnings)

if "result" in st.session_state:
    site_url, sitemap_urls, pages, warnings = st.session_state["result"]

    if warnings:
        with st.expander(f"{len(warnings)} warning(s)"):
            for w in warnings:
                st.text(w)

    if not pages:
        st.error(f"No pages found in the sitemap(s) for {site_url}.")
        st.stop()

    c1, c2 = st.columns(2)
    c1.metric("Pages", f"{len(pages):,}")
    c2.metric("Sitemaps", len(sitemap_urls))
    with st.expander("Sitemap sources"):
        for s in sitemap_urls:
            st.markdown(f"- {s}")

    query = st.text_input("Filter URLs", placeholder="e.g. /blog/")
    shown = [p for p in pages if query.lower() in p.lower()] if query else pages

    st.download_button(
        f"Download CSV ({len(shown):,} URLs)",
        data=to_csv_bytes(shown),
        file_name=default_output_path(site_url),
        mime="text/csv",
        type="primary",
    )
    st.dataframe(
        {"url": shown},
        column_config={"url": st.column_config.LinkColumn("URL")},
        width="stretch",
        hide_index=True,
        height=500,
    )
