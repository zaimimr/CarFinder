#!/usr/bin/env python3
"""
Finn.no Car Listing Scraper

Scrapes car listings from finn.no search results and saves detailed data
for each item. Supports pagination and extracts data from both the
embedded Next.js JSON and individual listing pages.

Usage:
    python scrape_finn.py [--url URL] [--output FILE] [--detail]

The default URL searches for electric Volkswagen e-Golf, Hyundai IONIQ,
and Hyundai Kona listings (2019+, 90k-200k NOK, under 150k km).
"""

import argparse
import json
import re
import sys
import time
from urllib.parse import urlencode, urlparse, parse_qs, urljoin

import requests
from bs4 import BeautifulSoup

DEFAULT_SEARCH_URL = (
    "https://www.finn.no/mobility/search/car?"
    "fuel=4&mileage_to=150000&price_from=90000&price_to=200000"
    "&registration_class=1"
    "&variant=1.817.1433&variant=1.772.2000393&variant=1.772.2000438"
    "&year_from=2019"
)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "nb-NO,nb;q=0.9,no;q=0.8,nn;q=0.7,en-US;q=0.6,en;q=0.5",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "DNT": "1",
}


def create_session():
    """Create a requests session that bypasses environment proxies."""
    session = requests.Session()
    session.trust_env = False  # Ignore proxy environment variables
    session.headers.update(HEADERS)
    return session


def fetch_page(session, url, retries=3, delay=2):
    """Fetch a page with retry logic."""
    for attempt in range(retries):
        try:
            response = session.get(url, timeout=30)
            response.raise_for_status()
            return response.text
        except requests.RequestException as e:
            print(f"  Attempt {attempt + 1}/{retries} failed: {e}")
            if attempt < retries - 1:
                time.sleep(delay * (attempt + 1))
    return None


def extract_next_data(html):
    """Extract the __NEXT_DATA__ JSON from the HTML page."""
    soup = BeautifulSoup(html, "lxml")
    script_tag = soup.find("script", id="__NEXT_DATA__")
    if script_tag and script_tag.string:
        try:
            return json.loads(script_tag.string)
        except json.JSONDecodeError:
            pass

    # Fallback: look for inline JSON in script tags
    for script in soup.find_all("script"):
        if script.string and '"docs"' in (script.string or ""):
            match = re.search(r'\{.*"docs"\s*:\s*\[.*\].*\}', script.string, re.DOTALL)
            if match:
                try:
                    return json.loads(match.group())
                except json.JSONDecodeError:
                    continue
    return None


def parse_listings_from_next_data(next_data):
    """Parse car listings from the __NEXT_DATA__ JSON structure."""
    listings = []

    # Navigate the Next.js data structure to find listings
    # The structure varies but typically lives under props.pageProps
    try:
        page_props = next_data.get("props", {}).get("pageProps", {})
    except AttributeError:
        return listings

    # Try common paths where listing data might be
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
        # Deep search for anything that looks like listings
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
        # Check if this dict has a "docs" key with a list value
        for key in ["docs", "items", "ads", "results", "listings"]:
            val = data.get(key)
            if isinstance(val, list) and len(val) > 0:
                # Check if items look like car listings
                first = val[0]
                if isinstance(first, dict) and any(
                    k in first
                    for k in ["id", "finnkode", "heading", "title", "price", "ad_id"]
                ):
                    return val

        # Recurse into dict values
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

    # ID / finnkode
    for key in ["id", "ad_id", "finnkode", "code"]:
        if key in doc:
            listing["id"] = str(doc[key])
            break

    # Title / heading
    for key in ["heading", "title", "ad_title", "name"]:
        if key in doc:
            listing["title"] = doc[key]
            break

    # Price
    price = doc.get("price", doc.get("main_price", doc.get("price_total")))
    if isinstance(price, dict):
        listing["price"] = price.get("amount", price.get("value"))
        listing["price_currency"] = price.get("currency_code", "NOK")
    elif price is not None:
        listing["price"] = price

    # Location
    location = doc.get("location", doc.get("ad_location"))
    if isinstance(location, str):
        listing["location"] = location
    elif isinstance(location, dict):
        listing["location"] = location.get("name", location.get("city", ""))
    elif isinstance(location, list):
        listing["location"] = ", ".join(str(l) for l in location if l)

    # Image
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

    # URL / link
    for key in ["canonical_url", "ad_link", "url", "link"]:
        if key in doc:
            url_val = doc[key]
            if url_val and not url_val.startswith("http"):
                url_val = f"https://www.finn.no{url_val}"
            listing["url"] = url_val
            break

    if "url" not in listing and "id" in listing:
        listing["url"] = f"https://www.finn.no/mobility/item/{listing['id']}"

    # Timestamp
    for key in ["timestamp", "published", "created", "ad_published"]:
        if key in doc:
            listing["published"] = doc[key]
            break

    # Labels / key info (year, mileage, fuel, etc.)
    labels = doc.get("labels", doc.get("key_info", doc.get("extras", [])))
    if isinstance(labels, list):
        listing["labels"] = labels

    # Trade type
    listing["trade_type"] = doc.get("trade_type", doc.get("ad_type", ""))

    # Extract any remaining flat key-value pairs that might be useful
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

    # Capture all remaining fields under "extras"
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


def parse_listings_from_html(html):
    """Fallback: parse listings directly from HTML using BeautifulSoup."""
    soup = BeautifulSoup(html, "lxml")
    listings = []

    # Try various known selectors for finn.no search results
    ad_elements = (
        soup.find_all("article", attrs={"data-testid": True})
        or soup.find_all("a", class_=re.compile(r"ads__unit"))
        or soup.find_all("article", class_=re.compile(r"sf-search-ad|ads-ad"))
        or soup.find_all("div", class_=re.compile(r"ads__unit"))
    )

    for elem in ad_elements:
        listing = {}

        # Get link and ID
        link = elem if elem.name == "a" else elem.find("a", href=True)
        if link and link.get("href"):
            href = link["href"]
            if not href.startswith("http"):
                href = f"https://www.finn.no{href}"
            listing["url"] = href
            # Extract finnkode from URL
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


def get_pagination_urls(html, base_url):
    """Extract pagination URLs from the search results page."""
    soup = BeautifulSoup(html, "lxml")
    urls = set()

    # Look for pagination links
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "page=" in href:
            if not href.startswith("http"):
                href = urljoin(base_url, href)
            urls.add(href)

    # Also check __NEXT_DATA__ for pagination info
    next_data = extract_next_data(html)
    if next_data:
        page_props = next_data.get("props", {}).get("pageProps", {})
        # Look for pagination metadata
        for key in ["search", "searchResult", "data", "initialData"]:
            section = page_props.get(key, {})
            if isinstance(section, dict):
                total_pages = section.get("total_pages", section.get("pageCount", 0))
                total_count = section.get("total_count", section.get("totalCount", 0))
                if total_pages > 1:
                    parsed = urlparse(base_url)
                    params = parse_qs(parsed.query)
                    for page in range(2, total_pages + 1):
                        params["page"] = [str(page)]
                        new_query = urlencode(params, doseq=True)
                        urls.add(f"{parsed.scheme}://{parsed.netloc}{parsed.path}?{new_query}")
                    break

    return sorted(urls)


def fetch_listing_detail(session, url):
    """Fetch an individual listing page for more detailed data."""
    html = fetch_page(session, url)
    if not html:
        return {}

    detail = {}

    # Try __NEXT_DATA__ first
    next_data = extract_next_data(html)
    if next_data:
        page_props = next_data.get("props", {}).get("pageProps", {})
        # The ad detail is often at the top level of pageProps
        ad = page_props.get("ad", page_props.get("item", page_props))
        if isinstance(ad, dict):
            detail = {k: v for k, v in ad.items() if v is not None}

    # Also parse from HTML for key-value pairs
    soup = BeautifulSoup(html, "lxml")

    # Look for specification tables / definition lists
    for dl in soup.find_all("dl"):
        dts = dl.find_all("dt")
        dds = dl.find_all("dd")
        for dt, dd in zip(dts, dds):
            key = dt.get_text(strip=True)
            value = dd.get_text(strip=True)
            if key and value:
                detail[key] = value

    # Look for key-value pairs in structured elements
    for table in soup.find_all("table"):
        for row in table.find_all("tr"):
            cells = row.find_all(["th", "td"])
            if len(cells) == 2:
                key = cells[0].get_text(strip=True)
                value = cells[1].get_text(strip=True)
                if key and value:
                    detail[key] = value

    return detail


def scrape_finn(search_url, fetch_details=False, output_file="listings.json"):
    """Main scraper function."""
    session = create_session()
    all_listings = []

    print(f"Fetching search results from:\n  {search_url}\n")

    # Fetch first page
    html = fetch_page(session, search_url)
    if not html:
        print("ERROR: Failed to fetch the search page.")
        print("Make sure you have internet access and finn.no is reachable.")
        sys.exit(1)

    # Try __NEXT_DATA__ extraction first
    next_data = extract_next_data(html)
    if next_data:
        print("Found embedded JSON data (__NEXT_DATA__)")
        listings = parse_listings_from_next_data(next_data)
        if listings:
            print(f"  Extracted {len(listings)} listings from page 1")
            all_listings.extend(listings)

            # Save the raw next_data for reference
            with open("raw_next_data.json", "w", encoding="utf-8") as f:
                json.dump(next_data, f, ensure_ascii=False, indent=2)
            print("  Saved raw JSON data to raw_next_data.json")

    # Fallback to HTML parsing
    if not all_listings:
        print("Falling back to HTML parsing...")
        listings = parse_listings_from_html(html)
        print(f"  Extracted {len(listings)} listings from HTML")
        all_listings.extend(listings)

    # Handle pagination
    pagination_urls = get_pagination_urls(html, search_url)
    if pagination_urls:
        print(f"\nFound {len(pagination_urls)} additional pages")
        for i, page_url in enumerate(pagination_urls, start=2):
            print(f"  Fetching page {i}...")
            time.sleep(1.5)  # Be polite
            page_html = fetch_page(session, page_url)
            if page_html:
                if next_data:
                    page_next_data = extract_next_data(page_html)
                    if page_next_data:
                        page_listings = parse_listings_from_next_data(page_next_data)
                    else:
                        page_listings = parse_listings_from_html(page_html)
                else:
                    page_listings = parse_listings_from_html(page_html)
                print(f"    Got {len(page_listings)} listings")
                all_listings.extend(page_listings)

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

    # Optionally fetch detailed data for each listing
    if fetch_details and all_listings:
        print("\nFetching detailed data for each listing...")
        for i, listing in enumerate(all_listings):
            url = listing.get("url")
            if url:
                print(f"  [{i + 1}/{len(all_listings)}] {listing.get('title', url)}")
                time.sleep(1)  # Be polite
                detail = fetch_listing_detail(session, url)
                if detail:
                    listing["detail"] = detail

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

    # Print summary
    if all_listings:
        print("\n--- Sample listing ---")
        sample = all_listings[0]
        for key, val in sample.items():
            if key != "detail":
                print(f"  {key}: {val}")

    return output


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
