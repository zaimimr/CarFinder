#!/usr/bin/env python3
"""
Flask web app for scraping finn.no car listings.

Run:
    python app.py
    # Open http://localhost:5000
"""

import json
import os
import threading
import time
import uuid

from flask import Flask, jsonify, render_template, request, send_file

app = Flask(__name__)

# In-memory store for scrape jobs (job_id -> status dict)
_jobs = {}


def _run_scrape(job_id, search_url, fetch_details):
    """Run the scraper in a background thread."""
    _jobs[job_id]["status"] = "running"
    _jobs[job_id]["message"] = "Launching headless browser..."

    try:
        from playwright.sync_api import sync_playwright
        from scrape_finn import (
            create_browser,
            extract_listings_via_js,
            extract_next_data,
            fetch_rendered_page,
            parse_listings_from_next_data,
            parse_listings_from_rendered_html,
            _get_pagination_urls_from_page,
        )
        import random
        import re

        all_listings = []

        with sync_playwright() as pw:
            browser, context = create_browser(pw)
            page = context.new_page()

            # Warm up
            _jobs[job_id]["message"] = "Warming up session..."
            try:
                page.goto("https://www.finn.no/", wait_until="domcontentloaded", timeout=20000)
                page.wait_for_load_state("networkidle", timeout=10000)
            except Exception:
                pass
            time.sleep(random.uniform(1.0, 2.0))

            # Accept cookies
            try:
                accept_btn = page.query_selector(
                    'button:has-text("Godta"), button:has-text("Accept"), '
                    'button:has-text("OK"), button[id*="accept"]'
                )
                if accept_btn:
                    accept_btn.click()
                    time.sleep(1)
            except Exception:
                pass

            # Load search page
            _jobs[job_id]["message"] = "Loading search results..."
            html = fetch_rendered_page(
                page, search_url,
                wait_selector='a[href*="/mobility/item/"]',
                timeout=30000,
            )

            if not html:
                _jobs[job_id]["status"] = "error"
                _jobs[job_id]["message"] = "Failed to load the search page."
                browser.close()
                return

            # Strategy 1: JS runtime
            _jobs[job_id]["message"] = "Extracting listing data..."
            js_data = extract_listings_via_js(page)
            if js_data:
                listings = parse_listings_from_next_data(js_data)
                if listings:
                    all_listings.extend(listings)

            # Strategy 2: __NEXT_DATA__
            if not all_listings:
                next_data = extract_next_data(html)
                if next_data:
                    listings = parse_listings_from_next_data(next_data)
                    if listings:
                        all_listings.extend(listings)

            # Strategy 3: Rendered HTML
            if not all_listings:
                listings = parse_listings_from_rendered_html(html)
                all_listings.extend(listings)

            # Strategy 4: Direct DOM
            if not all_listings:
                try:
                    dom_listings = page.evaluate("""() => {
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
                    if dom_listings:
                        all_listings.extend(dom_listings)
                except Exception:
                    pass

            _jobs[job_id]["message"] = f"Found {len(all_listings)} listings on page 1"

            # Pagination
            pagination_urls = _get_pagination_urls_from_page(page, search_url, html)
            if pagination_urls:
                for i, page_url in enumerate(pagination_urls, start=2):
                    _jobs[job_id]["message"] = f"Fetching page {i}/{len(pagination_urls) + 1}..."
                    time.sleep(random.uniform(2.0, 4.0))
                    page_html = fetch_rendered_page(
                        page, page_url,
                        wait_selector='a[href*="/mobility/item/"]',
                    )
                    if page_html:
                        page_listings = parse_listings_from_rendered_html(page_html)
                        if not page_listings:
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
                                        if (item.id || item.title) items.push(item);
                                    }
                                    return items;
                                }""")
                            except Exception:
                                page_listings = []
                        all_listings.extend(page_listings)

            # Fetch details if requested
            if fetch_details and all_listings:
                from scrape_finn import _parse_detail_page
                for i, listing in enumerate(all_listings):
                    url = listing.get("url")
                    if url:
                        _jobs[job_id]["message"] = f"Fetching details {i + 1}/{len(all_listings)}..."
                        time.sleep(random.uniform(1.5, 3.0))
                        detail_html = fetch_rendered_page(page, url)
                        if detail_html:
                            detail = _parse_detail_page(detail_html)
                            if detail:
                                listing["detail"] = detail

            browser.close()

        # Deduplicate
        seen_ids = set()
        unique = []
        for listing in all_listings:
            lid = listing.get("id", listing.get("url", ""))
            if lid and lid not in seen_ids:
                seen_ids.add(lid)
                unique.append(listing)
            elif not lid:
                unique.append(listing)

        # Save to file
        output = {
            "search_url": search_url,
            "scraped_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "total_listings": len(unique),
            "listings": unique,
        }
        with open("listings.json", "w", encoding="utf-8") as f:
            json.dump(output, f, ensure_ascii=False, indent=2)

        _jobs[job_id]["status"] = "done"
        _jobs[job_id]["message"] = f"Done! Found {len(unique)} listings."
        _jobs[job_id]["result"] = output

    except Exception as e:
        _jobs[job_id]["status"] = "error"
        _jobs[job_id]["message"] = f"Error: {e}"


# ---- Routes ----

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/scrape", methods=["POST"])
def start_scrape():
    data = request.get_json(force=True)
    search_url = data.get("url", "").strip()
    if not search_url:
        return jsonify({"error": "No URL provided"}), 400
    fetch_details = data.get("details", False)

    job_id = uuid.uuid4().hex[:12]
    _jobs[job_id] = {"status": "queued", "message": "Starting...", "result": None}

    thread = threading.Thread(target=_run_scrape, args=(job_id, search_url, fetch_details))
    thread.daemon = True
    thread.start()

    return jsonify({"job_id": job_id})


@app.route("/api/status/<job_id>")
def job_status(job_id):
    job = _jobs.get(job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404
    return jsonify({
        "status": job["status"],
        "message": job["message"],
        "result": job["result"],
    })


@app.route("/api/listings")
def get_listings():
    """Return the most recent listings.json if it exists."""
    path = os.path.join(os.path.dirname(__file__), "listings.json")
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return jsonify(json.load(f))
    return jsonify({"listings": []})


@app.route("/api/export/<fmt>")
def export(fmt):
    """Export listings as JSON or CSV."""
    path = os.path.join(os.path.dirname(__file__), "listings.json")
    if not os.path.exists(path):
        return jsonify({"error": "No data to export"}), 404

    if fmt == "json":
        return send_file(path, mimetype="application/json", as_attachment=True,
                         download_name="finn_listings.json")

    if fmt == "csv":
        import csv
        import io
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        listings = data.get("listings", [])
        if not listings:
            return jsonify({"error": "No listings"}), 404

        # Collect all keys
        keys = []
        seen = set()
        for item in listings:
            for k in item:
                if k not in seen and k != "detail":
                    keys.append(k)
                    seen.add(k)

        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=keys, extrasaction="ignore")
        writer.writeheader()
        for item in listings:
            row = {}
            for k in keys:
                v = item.get(k, "")
                if isinstance(v, (list, dict)):
                    v = json.dumps(v, ensure_ascii=False)
                row[k] = v
            writer.writerow(row)

        resp = app.make_response(buf.getvalue())
        resp.headers["Content-Type"] = "text/csv; charset=utf-8"
        resp.headers["Content-Disposition"] = "attachment; filename=finn_listings.csv"
        return resp

    return jsonify({"error": "Unknown format"}), 400


if __name__ == "__main__":
    app.run(debug=True, port=5000)
