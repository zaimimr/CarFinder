#!/usr/bin/env python3
"""
Finn.no Car Listing Scraper

Scrapes car listings from finn.no search results using a headless browser
(Playwright) to handle client-side rendering, then extracts listing data
from the rendered DOM.

Usage:
    python scrape_finn.py [--url URL] [--output FILE] [--detail]
    playwright install chromium   # first-time setup

The default URL searches for electric Volkswagen e-Golf, Hyundai IONIQ,
and Hyundai Kona listings (2019+, 90k-200k NOK, under 150k km).
"""

import argparse
import json
import random
import re
import sys
import time
from urllib.parse import urlencode, urlparse, parse_qs

DEFAULT_SEARCH_URL = (
    "https://www.finn.no/mobility/search/car?"
    "fuel=4&mileage_to=150000&price_from=90000&price_to=200000"
    "&registration_class=1"
    "&variant=1.817.1433&variant=1.772.2000393&variant=1.772.2000438"
    "&year_from=2019"
)


# ---------------------------------------------------------------------------
# Playwright-based fetching (handles JS-rendered pages)
# ---------------------------------------------------------------------------

def create_browser(playwright):
    """Launch a headless Chromium browser that looks like a real user."""
    browser = playwright.chromium.launch(headless=True)
    context = browser.new_context(
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/131.0.0.0 Safari/537.36"
        ),
        viewport={"width": 1920, "height": 1080},
        locale="nb-NO",
        timezone_id="Europe/Oslo",
        extra_http_headers={
            "Accept-Language": "nb-NO,nb;q=0.9,no;q=0.8,en-US;q=0.6,en;q=0.5",
            "DNT": "1",
        },
    )
    return browser, context


def fetch_rendered_page(page, url, wait_selector=None, timeout=30000):
    """Navigate to a URL, wait for JS to render, and return the full HTML."""
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=timeout)

        # Wait for the page to finish rendering dynamic content
        if wait_selector:
            try:
                page.wait_for_selector(wait_selector, timeout=15000)
            except Exception:
                print(f"    Selector '{wait_selector}' not found, waiting for network idle...")
                page.wait_for_load_state("networkidle", timeout=15000)
        else:
            page.wait_for_load_state("networkidle", timeout=15000)

        return page.content()
    except Exception as e:
        print(f"  Page load error: {e}")
        return None


# ---------------------------------------------------------------------------
# Parsing helpers (work on fully rendered HTML)
# ---------------------------------------------------------------------------

def extract_next_data(html):
    """Extract the __NEXT_DATA__ JSON from the HTML page."""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "lxml")
    script_tag = soup.find("script", id="__NEXT_DATA__")
    if script_tag and script_tag.string:
        try:
            return json.loads(script_tag.string)
        except json.JSONDecodeError:
            pass

    # Fallback: look for inline JSON in script tags
    for script in soup.find_all("script"):
        text = script.string or ""
        if '"docs"' in text:
            match = re.search(r'\{.*"docs"\s*:\s*\[.*\].*\}', text, re.DOTALL)
            if match:
                try:
                    return json.loads(match.group())
                except json.JSONDecodeError:
                    continue
    return None


def parse_listings_from_next_data(next_data):
    """Parse car listings from the __NEXT_DATA__ JSON structure."""
    listings = []
    try:
        page_props = next_data.get("props", {}).get("pageProps", {})
    except AttributeError:
        return listings

    docs = None
    for path in [
        lambda: page_props.get("search", {}).get("docs", []),
        lambda: page_props.get("docs", []),
        lambda: page_props.get("searchResult", {}).get("docs", []),
        lambda: page_props.get("data", {}).get("docs", []),
        lambda: page_props.get("initialData", {}).get("docs", []),
        lambda: page_props.get("searchData", {}).get("docs", []),
    ]:
        try:
            result = path()
            if result:
                docs = result
                break
        except (AttributeError, TypeError):
            continue

    if not docs:
        docs = _find_docs_recursive(next_data)

    if docs:
        for doc in docs:
            listing = extract_listing_fields(doc)
            if listing.get("id") or listing.get("title"):
                listings.append(listing)

    return listings


def _find_docs_recursive(data, depth=0, max_depth=8):
    """Recursively search for an array of listing documents."""
    if depth > max_depth:
        return None

    if isinstance(data, dict):
        for key in ["docs", "items", "ads", "results", "listings"]:
            val = data.get(key)
            if isinstance(val, list) and len(val) > 0:
                first = val[0]
                if isinstance(first, dict) and any(
                    k in first
                    for k in ["id", "finnkode", "heading", "title", "price", "ad_id"]
                ):
                    return val

        for val in data.values():
            result = _find_docs_recursive(val, depth + 1, max_depth)
            if result:
                return result

    elif isinstance(data, list):
        for item in data:
            result = _find_docs_recursive(item, depth + 1, max_depth)
            if result:
                return result

    return None


def extract_listing_fields(doc):
    """Extract all useful fields from a listing document."""
    listing = {}

    for key in ["id", "ad_id", "finnkode", "code"]:
        if key in doc:
            listing["id"] = str(doc[key])
            break

    for key in ["heading", "title", "ad_title", "name"]:
        if key in doc:
            listing["title"] = doc[key]
            break

    price = doc.get("price", doc.get("main_price", doc.get("price_total")))
    if isinstance(price, dict):
        listing["price"] = price.get("amount", price.get("value"))
        listing["price_currency"] = price.get("currency_code", "NOK")
    elif price is not None:
        listing["price"] = price

    location = doc.get("location", doc.get("ad_location"))
    if isinstance(location, str):
        listing["location"] = location
    elif isinstance(location, dict):
        listing["location"] = location.get("name", location.get("city", ""))
    elif isinstance(location, list):
        listing["location"] = ", ".join(str(loc) for loc in location if loc)

    image = doc.get("image", doc.get("images", doc.get("main_image")))
    if isinstance(image, dict):
        listing["image_url"] = image.get("url", image.get("src", ""))
    elif isinstance(image, list) and image:
        first_img = image[0]
        if isinstance(first_img, dict):
            listing["image_url"] = first_img.get("url", first_img.get("src", ""))
        elif isinstance(first_img, str):
            listing["image_url"] = first_img
    elif isinstance(image, str):
        listing["image_url"] = image

    for key in ["canonical_url", "ad_link", "url", "link"]:
        if key in doc:
            url_val = doc[key]
            if url_val and not url_val.startswith("http"):
                url_val = f"https://www.finn.no{url_val}"
            listing["url"] = url_val
            break

    if "url" not in listing and "id" in listing:
        listing["url"] = f"https://www.finn.no/mobility/item/{listing['id']}"

    for key in ["timestamp", "published", "created", "ad_published"]:
        if key in doc:
            listing["published"] = doc[key]
            break

    labels = doc.get("labels", doc.get("key_info", doc.get("extras", [])))
    if isinstance(labels, list):
        listing["labels"] = labels

    listing["trade_type"] = doc.get("trade_type", doc.get("ad_type", ""))

    known_keys = {
        "year", "mileage", "fuel", "gearbox", "transmission",
        "body_type", "colour", "color", "seats", "doors",
        "engine_effect", "engine_volume", "wheel_drive",
        "co2_emission", "nox_emission", "weight",
        "registration_year", "first_registration",
        "make", "model", "variant",
    }
    for key in known_keys:
        if key in doc and doc[key] is not None:
            listing[key] = doc[key]

    captured_keys = set(listing.keys()) | {
        "image", "images", "main_image", "canonical_url", "ad_link",
        "link", "heading", "title", "ad_title", "name", "price",
        "main_price", "price_total", "location", "ad_location",
        "labels", "key_info", "extras", "timestamp", "published",
        "created", "ad_published", "trade_type", "ad_type",
        "id", "ad_id", "finnkode", "code",
    }
    extra_fields = {}
    for key, val in doc.items():
        if key not in captured_keys and val is not None:
            extra_fields[key] = val
    if extra_fields:
        listing["extra_fields"] = extra_fields

    return listing


def parse_listings_from_rendered_html(html):
    """Parse listings from fully rendered HTML using BeautifulSoup."""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "lxml")
    listings = []

    # Try multiple selectors — finn.no changes these periodically
    ad_elements = (
        soup.find_all("article", attrs={"data-testid": True})
        or soup.find_all("a", class_=re.compile(r"ads__unit"))
        or soup.find_all("article", class_=re.compile(r"sf-search-ad|ads-ad"))
        or soup.find_all("div", class_=re.compile(r"ads__unit"))
    )

    # Broader fallback: any <a> linking to /mobility/item/
    if not ad_elements:
        ad_elements = soup.find_all("a", href=re.compile(r"/mobility/item/\d+"))

    for elem in ad_elements:
        listing = {}

        # Get link and ID
        link = elem if elem.name == "a" else elem.find("a", href=True)
        if link and link.get("href"):
            href = link["href"]
            if not href.startswith("http"):
                href = f"https://www.finn.no{href}"
            listing["url"] = href
            id_match = re.search(r"/(\d+)(?:\?|$)", href)
            if id_match:
                listing["id"] = id_match.group(1)

        # Get title
        title_elem = elem.find(["h2", "h3", "h4"])
        if title_elem:
            listing["title"] = title_elem.get_text(strip=True)

        # Get price
        price_elem = elem.find(string=re.compile(r"[\d\s]+kr"))
        if price_elem:
            price_text = price_elem.strip()
            price_digits = re.sub(r"[^\d]", "", price_text)
            if price_digits:
                listing["price"] = int(price_digits)

        # Get image
        img = elem.find("img")
        if img:
            listing["image_url"] = img.get("src", img.get("data-src", ""))

        # Get metadata labels (year, km, fuel, etc.)
        labels = []
        for span in elem.find_all(["span", "p", "dd"]):
            text = span.get_text(strip=True)
            if text and len(text) < 100:
                labels.append(text)
        if labels:
            listing["labels"] = labels

        # Get location
        location_elem = elem.find(string=re.compile(r"^\s*[A-ZÆØÅ]"))
        if location_elem:
            listing["location"] = location_elem.strip()

        if listing.get("id") or listing.get("title"):
            listings.append(listing)

    return listings


def extract_listings_via_js(page):
    """Try to extract listing data directly from the page's JS runtime."""
    try:
        # Some SPAs store data in window.__DATA__ or similar globals
        data = page.evaluate("""() => {
            // Try common data stores
            const candidates = [
                window.__NEXT_DATA__,
                window.__DATA__,
                window.__INITIAL_STATE__,
                window.__APP_STATE__,
                window.__PRELOADED_STATE__,
            ];
            for (const c of candidates) {
                if (c) return JSON.parse(JSON.stringify(c));
            }
            return null;
        }""")
        if data:
            return data
    except Exception:
        pass
    return None


# ---------------------------------------------------------------------------
# Main scraper
# ---------------------------------------------------------------------------

def scrape_finn(search_url, fetch_details=False, output_file="listings.json"):
    """Main scraper function using Playwright headless browser."""
    from playwright.sync_api import sync_playwright

    all_listings = []

    print(f"Fetching search results from:\n  {search_url}\n")

    with sync_playwright() as pw:
        browser, context = create_browser(pw)
        page = context.new_page()

        # Warm up: visit the homepage first
        print("Warming up session (visiting homepage)...")
        try:
            page.goto("https://www.finn.no/", wait_until="domcontentloaded", timeout=20000)
            page.wait_for_load_state("networkidle", timeout=10000)
            print(f"  Homepage loaded ({len(page.content())} bytes)")
        except Exception as e:
            print(f"  Homepage warmup failed: {e}, continuing...")
        time.sleep(random.uniform(1.0, 3.0))

        # Accept cookies/consent if a dialog appears
        try:
            accept_btn = page.query_selector(
                'button:has-text("Godta"), button:has-text("Accept"), '
                'button:has-text("OK"), button[id*="accept"], '
                'button[data-testid*="accept"]'
            )
            if accept_btn:
                accept_btn.click()
                print("  Accepted cookie consent")
                time.sleep(1)
        except Exception:
            pass

        # Fetch the search page
        print("Loading search results...")
        html = fetch_rendered_page(
            page, search_url,
            wait_selector='a[href*="/mobility/item/"]',
            timeout=30000,
        )

        if not html:
            print("ERROR: Failed to load the search page.")
            browser.close()
            sys.exit(1)

        # Save raw HTML for debugging
        with open("raw_page.html", "w", encoding="utf-8") as f:
            f.write(html)
        print(f"Saved raw HTML ({len(html)} bytes) to raw_page.html")

        # Debug info
        from bs4 import BeautifulSoup
        soup_debug = BeautifulSoup(html, "lxml")
        title_tag = soup_debug.find("title")
        print(f"Page title: {title_tag.get_text(strip=True) if title_tag else '(none)'}")
        script_count = len(soup_debug.find_all("script"))
        print(f"Script tags: {script_count}")
        link_count = len(soup_debug.find_all("a", href=re.compile(r"/mobility/item/")))
        print(f"Listing links found: {link_count}")

        # Strategy 1: Try extracting data from JS runtime
        js_data = extract_listings_via_js(page)
        if js_data:
            print("Found data in JS runtime")
            with open("raw_next_data.json", "w", encoding="utf-8") as f:
                json.dump(js_data, f, ensure_ascii=False, indent=2)
            print("  Saved JS data to raw_next_data.json")
            listings = parse_listings_from_next_data(js_data)
            if listings:
                print(f"  Extracted {len(listings)} listings from JS data")
                all_listings.extend(listings)

        # Strategy 2: Try __NEXT_DATA__ in the HTML
        if not all_listings:
            next_data = extract_next_data(html)
            if next_data:
                print("Found __NEXT_DATA__ in HTML")
                with open("raw_next_data.json", "w", encoding="utf-8") as f:
                    json.dump(next_data, f, ensure_ascii=False, indent=2)
                listings = parse_listings_from_next_data(next_data)
                if listings:
                    print(f"  Extracted {len(listings)} listings")
                    all_listings.extend(listings)
                else:
                    print("  __NEXT_DATA__ found but no listings parsed")
                    try:
                        pp = next_data.get("props", {}).get("pageProps", {})
                        print(f"    pageProps keys: {list(pp.keys())[:20]}")
                    except Exception:
                        pass

        # Strategy 3: Parse the rendered HTML DOM
        if not all_listings:
            print("Parsing rendered HTML...")
            listings = parse_listings_from_rendered_html(html)
            print(f"  Extracted {len(listings)} listings from HTML")
            all_listings.extend(listings)

        # Strategy 4: Use Playwright to scrape directly from DOM
        if not all_listings:
            print("Trying direct DOM extraction via Playwright...")
            try:
                dom_listings = page.evaluate("""() => {
                    const items = [];
                    // Find all links to listing pages
                    const links = document.querySelectorAll('a[href*="/mobility/item/"]');
                    for (const link of links) {
                        const item = {};
                        const href = link.getAttribute('href');
                        item.url = href.startsWith('http') ? href : 'https://www.finn.no' + href;
                        const idMatch = href.match(/\\/([0-9]+)/);
                        if (idMatch) item.id = idMatch[1];

                        // Get text content from the link's container
                        const container = link.closest('article') || link;
                        const title = container.querySelector('h2, h3, h4');
                        if (title) item.title = title.textContent.trim();

                        // Look for price text
                        const allText = container.textContent;
                        const priceMatch = allText.match(/([\\d\\s]+)\\s*kr/);
                        if (priceMatch) {
                            item.price = parseInt(priceMatch[1].replace(/\\s/g, ''));
                        }

                        // Get image
                        const img = container.querySelector('img');
                        if (img) item.image_url = img.src || img.dataset.src || '';

                        // Collect label text
                        const spans = container.querySelectorAll('span, p');
                        const labels = [];
                        for (const s of spans) {
                            const t = s.textContent.trim();
                            if (t && t.length < 100) labels.push(t);
                        }
                        if (labels.length) item.labels = labels;

                        if (item.id || item.title) items.push(item);
                    }
                    return items;
                }""")
                if dom_listings:
                    print(f"  Extracted {len(dom_listings)} listings via DOM")
                    all_listings.extend(dom_listings)
            except Exception as e:
                print(f"  DOM extraction failed: {e}")

        if not all_listings:
            # Final debug dump
            print("\n  DEBUG: Page structure analysis:")
            for tag in ["article", "a", "div", "section"]:
                elems = soup_debug.find_all(tag)
                if elems:
                    classes = set()
                    for e in elems:
                        for c in (e.get("class") or []):
                            classes.add(c)
                    top_classes = sorted(classes)[:15]
                    print(f"    <{tag}>: {len(elems)} elements, classes: {top_classes}")
            listing_links = [
                a["href"] for a in soup_debug.find_all("a", href=True)
                if "/item/" in a["href"] or "/mobility/" in a["href"]
            ]
            if listing_links:
                print(f"    Found {len(listing_links)} mobility/item links:")
                for link in listing_links[:10]:
                    print(f"      {link}")

        # Handle pagination
        pagination_urls = _get_pagination_urls_from_page(page, search_url, html)
        if pagination_urls:
            print(f"\nFound {len(pagination_urls)} additional pages")
            for i, page_url in enumerate(pagination_urls, start=2):
                print(f"  Fetching page {i}...")
                time.sleep(random.uniform(2.0, 5.0))
                page_html = fetch_rendered_page(
                    page, page_url,
                    wait_selector='a[href*="/mobility/item/"]',
                )
                if page_html:
                    page_listings = parse_listings_from_rendered_html(page_html)
                    if not page_listings:
                        # Try DOM extraction
                        try:
                            page_listings = page.evaluate("""() => {
                                const items = [];
                                const links = document.querySelectorAll('a[href*="/mobility/item/"]');
                                for (const link of links) {
                                    const item = {};
                                    const href = link.getAttribute('href');
                                    item.url = href.startsWith('http') ? href : 'https://www.finn.no' + href;
                                    const idMatch = href.match(/\\/([0-9]+)/);
                                    if (idMatch) item.id = idMatch[1];
                                    const container = link.closest('article') || link;
                                    const title = container.querySelector('h2, h3, h4');
                                    if (title) item.title = title.textContent.trim();
                                    const allText = container.textContent;
                                    const priceMatch = allText.match(/([\\d\\s]+)\\s*kr/);
                                    if (priceMatch) item.price = parseInt(priceMatch[1].replace(/\\s/g, ''));
                                    const img = container.querySelector('img');
                                    if (img) item.image_url = img.src || '';
                                    if (item.id || item.title) items.push(item);
                                }
                                return items;
                            }""")
                        except Exception:
                            page_listings = []
                    print(f"    Got {len(page_listings)} listings")
                    all_listings.extend(page_listings)

        # Optionally fetch detailed data for each listing
        if fetch_details and all_listings:
            print("\nFetching detailed data for each listing...")
            for i, listing in enumerate(all_listings):
                url = listing.get("url")
                if url:
                    print(f"  [{i + 1}/{len(all_listings)}] {listing.get('title', url)}")
                    time.sleep(random.uniform(1.5, 4.0))
                    detail_html = fetch_rendered_page(page, url)
                    if detail_html:
                        detail = _parse_detail_page(detail_html)
                        if detail:
                            listing["detail"] = detail

        browser.close()

    # Deduplicate by ID
    seen_ids = set()
    unique_listings = []
    for listing in all_listings:
        lid = listing.get("id", listing.get("url", ""))
        if lid and lid not in seen_ids:
            seen_ids.add(lid)
            unique_listings.append(listing)
        elif not lid:
            unique_listings.append(listing)
    all_listings = unique_listings

    print(f"\nTotal unique listings: {len(all_listings)}")

    # Save results
    output = {
        "search_url": search_url,
        "scraped_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "total_listings": len(all_listings),
        "search_params": {
            "fuel": "electric (4)",
            "mileage_to": 150000,
            "price_from": 90000,
            "price_to": 200000,
            "registration_class": 1,
            "year_from": 2019,
            "variants": [
                {"code": "1.817.1433", "make": "Volkswagen", "model": "e-Golf"},
                {"code": "1.772.2000393", "make": "Hyundai", "model": "IONIQ"},
                {"code": "1.772.2000438", "make": "Hyundai", "model": "Kona"},
            ],
        },
        "listings": all_listings,
    }

    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"\nResults saved to {output_file}")
    print(f"Total items: {len(all_listings)}")

    if all_listings:
        print("\n--- Sample listing ---")
        sample = all_listings[0]
        for key, val in sample.items():
            if key != "detail":
                print(f"  {key}: {val}")

    return output


def _get_pagination_urls_from_page(page, base_url, html):
    """Extract pagination URLs from the rendered page."""
    urls = set()

    # Try to get pagination links from the DOM
    try:
        links = page.evaluate("""() => {
            const links = [];
            document.querySelectorAll('a[href*="page="]').forEach(a => {
                links.push(a.href);
            });
            return links;
        }""")
        for link in links:
            urls.add(link)
    except Exception:
        pass

    # Also check __NEXT_DATA__ for pagination info
    next_data = extract_next_data(html)
    if next_data:
        try:
            page_props = next_data.get("props", {}).get("pageProps", {})
            for key in ["search", "searchResult", "data", "initialData"]:
                section = page_props.get(key, {})
                if isinstance(section, dict):
                    total_pages = section.get("total_pages", section.get("pageCount", 0))
                    if total_pages > 1:
                        parsed = urlparse(base_url)
                        params = parse_qs(parsed.query)
                        for pg in range(2, total_pages + 1):
                            params["page"] = [str(pg)]
                            new_query = urlencode(params, doseq=True)
                            urls.add(f"{parsed.scheme}://{parsed.netloc}{parsed.path}?{new_query}")
                        break
        except Exception:
            pass

    return sorted(urls)


def _parse_detail_page(html):
    """Parse a detail page for key-value car specs."""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "lxml")
    detail = {}

    for dl in soup.find_all("dl"):
        dts = dl.find_all("dt")
        dds = dl.find_all("dd")
        for dt, dd in zip(dts, dds):
            key = dt.get_text(strip=True)
            value = dd.get_text(strip=True)
            if key and value:
                detail[key] = value

    for table in soup.find_all("table"):
        for row in table.find_all("tr"):
            cells = row.find_all(["th", "td"])
            if len(cells) == 2:
                key = cells[0].get_text(strip=True)
                value = cells[1].get_text(strip=True)
                if key and value:
                    detail[key] = value

    return detail


def main():
    parser = argparse.ArgumentParser(
        description="Scrape car listings from finn.no"
    )
    parser.add_argument(
        "--url",
        default=DEFAULT_SEARCH_URL,
        help="Finn.no search URL to scrape",
    )
    parser.add_argument(
        "--output", "-o",
        default="listings.json",
        help="Output JSON file path (default: listings.json)",
    )
    parser.add_argument(
        "--detail", "-d",
        action="store_true",
        help="Also fetch detailed data from each individual listing page",
    )
    args = parser.parse_args()

    scrape_finn(args.url, fetch_details=args.detail, output_file=args.output)


if __name__ == "__main__":
    main()
