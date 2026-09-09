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
        import math
        import random
        from scrape_finn import (
            RESULTS_PER_PAGE,
            create_browser,
            fetch_rendered_page,
            _build_page_urls,
            _extract_listings_from_page,
            _extract_total_hits,
        )

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

            # Fetch page 1
            page1_url = _build_page_urls(search_url, 1)[0]
            _jobs[job_id]["message"] = "Loading search results (page 1)..."
            html = fetch_rendered_page(
                page, page1_url,
                wait_selector='a[href*="/mobility/item/"]',
                timeout=30000,
            )

            if not html:
                _jobs[job_id]["status"] = "error"
                _jobs[job_id]["message"] = "Failed to load the search page."
                browser.close()
                return

            # Determine total pages from "X treff"
            total_hits = _extract_total_hits(page)
            if total_hits:
                total_pages = math.ceil(total_hits / RESULTS_PER_PAGE)
            else:
                total_pages = 1

            # Extract listings from page 1
            _jobs[job_id]["message"] = "Extracting listing data..."
            page_listings = _extract_listings_from_page(page, html)
            all_listings.extend(page_listings)
            _jobs[job_id]["message"] = (
                f"Found {len(all_listings)} listings on page 1"
                f" ({total_hits or '?'} treff, {total_pages} pages)"
            )

            # Fetch remaining pages
            for page_num in range(2, total_pages + 1):
                page_url = _build_page_urls(search_url, page_num)[-1]
                _jobs[job_id]["message"] = f"Fetching page {page_num}/{total_pages}..."
                time.sleep(random.uniform(2.0, 4.0))
                page_html = fetch_rendered_page(
                    page, page_url,
                    wait_selector='a[href*="/mobility/item/"]',
                )
                if page_html:
                    page_listings = _extract_listings_from_page(page, page_html)
                    all_listings.extend(page_listings)
                if not page_listings:
                    break

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
