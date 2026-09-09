#!/usr/bin/env python3
"""
BYD Atto 3 finder for finn.no and rebil.no.

Scrapes both sites for BYD Atto 3 listings, filters on year and mileage,
fetches equipment lists from each detail page, scores them on how well
equipped they are, and posts a ranked shortlist to a Slack webhook.

Usage:
    python atto_finder.py [--output atto_listings.json] [--slack-webhook URL]
    python atto_finder.py --no-slack

Environment:
    SLACK_WEBHOOK_URL   Slack incoming webhook used when --slack-webhook is absent
"""

import argparse
import json
import math
import os
import random
import re
import sys
import time
import urllib.request

from scrape_finn import (
    RESULTS_PER_PAGE,
    _build_page_urls,
    _extract_listings_from_page,
    _extract_total_hits,
    create_browser,
    fetch_rendered_page,
)

SEARCH_URL = (
    "https://www.finn.no/mobility/search/car?"
    "fuel=4&q=BYD%20ATTO%203&registration_class=1"
    "&year_from=2023&year_to=2024&mileage_to=30000"
)

REBIL_URL = "https://app.rebil.no/?textSearch=BYD%20ATTO"

MIN_YEAR = 2023
MAX_YEAR = 2024
MAX_MILEAGE = 30000

OPENING_ROOF_PATTERNS = [
    r"soltak",
    r"skyvetak",
    r"[åa]pningsbar\w*\s*(panorama|tak|glasstak)",
    r"panorama\w*\s*tak[^|]{0,20}(kan [åa]pnes|[åa]pningsbar)",
]

FIXED_ROOF_PATTERNS = [r"panorama\w*\s*glasstak", r"fast\w*\s*glasstak"]

ELECTRIC_SEAT_PATTERNS = [
    r"elektri\w*[^|]{0,30}(f[øo]rersete|forsete|sete|seter)",
    r"(f[øo]rersete|forseter|seter)[^|]{0,30}elektri",
    r"el\.?\s*justerbar\w*\s*(sete|seter|f[øo]rersete)",
    r"\d+-?veis\w*\s*justerbar\w*\s*f[øo]rersete",
]

SCORED_EQUIPMENT = [
    ("Panorama soltak (kan åpnes)", 14, ["soltak", "skyvetak"]),
    ("Panorama glasstak (fast)", 4, ["panorama glasstak", "panoramaglasstak", "panoramatak"]),
    ("Varmepumpe", 10, ["varmepumpe"]),
    ("Skinnseter", 6, ["skinnseter", "skinninteriør", "seter, skinn"]),
    ("Setevarme foran", 6, ["setevarme", "seter, oppvarmede", "oppvarmede seter"]),
    ("Setevarme bak", 4, ["setevarme bak", "oppvarmede seter bak"]),
    ("Ventilerte seter", 5, ["ventilerte seter", "seter, ventilerte"]),
    ("Oppvarmet ratt", 5, ["oppvarmet ratt", "rattvarme"]),
    ("360-kamera", 6, ["360 grader", "360-kamera", "360 graders"]),
    ("Ryggekamera", 3, ["ryggekamera", "kamera, rygge"]),
    ("Head-up display", 5, ["head-up", "heads-up", "hud"]),
    ("Adaptiv cruise", 5, ["fartsholder, dynamisk", "adaptiv cruise", "cruisekontroll, adaptiv"]),
    ("Blindsone", 4, ["blindsone"]),
    ("Elektrisk bakluke", 5, ["elektrisk bakluke", "bakluke, elektrisk", "el. bakluke"]),
    ("Nøkkelløs", 3, ["nøkkelfri", "keyless", "nøkkelløs"]),
    ("Trådløs lading", 3, ["trådløs lading", "induktiv lading"]),
    ("Navigasjon", 3, ["navigasjon"]),
    ("Vehicle-to-load", 4, ["v2l", "vehicle to load", "strømuttak 220"]),
    ("Parkeringssensor foran+bak", 3, ["avstandsfølere foran og bak"]),
    ("Memory-seter", 2, ["memory", "minneseter", "seter med minne", "minne på førersete"]),
    ("Elektrisk passasjersete", 3, ["elektrisk justerbart passasjersete", "elektrisk passasjersete"]),
]

EXCLUDE_EQUIPMENT = [("Hengerfeste", ["hengerfeste", "tilhengerfeste"])]


def _norm(text):
    return re.sub(r"\s+", " ", (text or "").lower()).strip()


def parse_year_and_mileage(listing):
    """Pull model year and odometer reading out of a search-result listing."""
    year = None
    mileage = None

    for label in listing.get("labels", []) or []:
        text = _norm(label)
        if year is None:
            match = re.search(r"\b(19|20)\d{2}\b", text)
            if match and "km" in text:
                year = int(match.group())
        if mileage is None:
            match = re.search(r"([\d\s ]+)\s*km\b", text)
            if match:
                digits = re.sub(r"[^\d]", "", match.group(1))
                if digits:
                    value = int(digits)
                    if value < 1_000_000:
                        mileage = value

    return year, mileage


def parse_price(listing):
    for label in listing.get("labels", []) or []:
        text = _norm(label)
        match = re.search(r"([\d\s ]{5,})\s*kr\b", text)
        if match:
            digits = re.sub(r"[^\d]", "", match.group(1))
            if digits and 20_000 < int(digits) < 2_000_000:
                return int(digits)
    return listing.get("price")


def _price_from_specs(specs):
    for key in ("Totalpris", "Pris eksl. omreg.", "Pris"):
        value = specs.get(key)
        if value:
            digits = re.sub(r"[^\d]", "", value.split("kr")[0])
            if digits and 20_000 < int(digits) < 2_000_000:
                return int(digits)
    return None


def parse_detail(html):
    """Extract the spec table, equipment list and seller info from a detail page."""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "lxml")
    specs = {}

    for dl in soup.find_all("dl"):
        for dt, dd in zip(dl.find_all("dt"), dl.find_all("dd")):
            key = dt.get_text(strip=True)
            value = dd.get_text(strip=True)
            if key and value:
                specs[key] = value

    equipment = []
    for ul in soup.find_all("ul"):
        items = [li.get_text(strip=True) for li in ul.find_all("li")]
        items = [i for i in items if i]
        if len(items) >= 8 and any(len(i) < 60 for i in items):
            if sum(1 for i in items if ":" in i or len(i.split()) <= 6) > len(items) / 2:
                equipment.extend(items)

    seen = set()
    equipment = [e for e in equipment if not (e in seen or seen.add(e))]

    description = ""
    for heading in soup.find_all(["h2", "h3"]):
        if _norm(heading.get_text()) == "beskrivelse":
            parent = heading.find_parent()
            if parent:
                description = parent.get_text(" ", strip=True)[:4000]
            break

    price = None
    for heading in soup.find_all(["h1", "h2", "h3"]):
        text = heading.get_text(strip=True)
        if re.fullmatch(r"[\d\s\u00a0]{5,}kr", text):
            digits = re.sub(r"[^\d]", "", text)
            if digits and 20_000 < int(digits) < 2_000_000:
                price = int(digits)
                break

    seller = ""
    for heading in soup.find_all(["h2", "h3"]):
        if "selger" in _norm(heading.get_text()):
            sibling = heading.find_next(["h2", "h3", "p", "span"])
            if sibling:
                seller = sibling.get_text(strip=True)[:120]
            break

    return {
        "specs": specs,
        "equipment": equipment,
        "description": description,
        "seller": seller,
        "price": price,
    }


def score_listing(detail):
    """Score a listing on equipment. Returns (score, matched, missing, flags)."""
    haystack = _norm(
        " | ".join(detail.get("equipment", []))
        + " | "
        + " ".join(f"{k} {v}" for k, v in detail.get("specs", {}).items())
        + " | "
        + detail.get("description", "")
    )

    matched = []
    missing = []
    score = 0
    for name, weight, keywords in SCORED_EQUIPMENT:
        if any(kw in haystack for kw in keywords):
            matched.append(name)
            score += weight
        else:
            missing.append(name)

    flags = []
    for name, keywords in EXCLUDE_EQUIPMENT:
        if any(kw in haystack for kw in keywords):
            flags.append(name)

    has_electric_seat = any(
        re.search(pattern, haystack) for pattern in ELECTRIC_SEAT_PATTERNS
    )
    has_opening_roof = any(
        re.search(pattern, haystack) for pattern in OPENING_ROOF_PATTERNS
    )
    has_fixed_roof = any(
        re.search(pattern, haystack) for pattern in FIXED_ROOF_PATTERNS
    )

    return (
        score,
        matched,
        missing,
        flags,
        has_electric_seat,
        has_opening_roof,
        has_fixed_roof,
    )


def scrape_candidates():
    """Scrape the finn.no search results and return raw listings."""
    from playwright.sync_api import sync_playwright

    listings = []
    with sync_playwright() as pw:
        browser, context = create_browser(pw)
        page = context.new_page()

        try:
            page.goto("https://www.finn.no/", wait_until="domcontentloaded", timeout=20000)
            page.wait_for_load_state("networkidle", timeout=10000)
        except Exception:
            pass
        time.sleep(random.uniform(1.0, 2.5))

        first_url = _build_page_urls(SEARCH_URL, 1)[0]
        html = fetch_rendered_page(
            page, first_url, wait_selector='a[href*="/mobility/item/"]', timeout=30000
        )
        if not html:
            browser.close()
            raise RuntimeError("Could not load finn.no search results")

        total_hits = _extract_total_hits(page)
        total_pages = math.ceil(total_hits / RESULTS_PER_PAGE) if total_hits else 1
        listings.extend(_extract_listings_from_page(page, html))

        for page_num in range(2, total_pages + 1):
            time.sleep(random.uniform(2.0, 4.0))
            url = _build_page_urls(SEARCH_URL, page_num)[-1]
            html = fetch_rendered_page(
                page, url, wait_selector='a[href*="/mobility/item/"]', timeout=30000
            )
            if not html:
                continue
            listings.extend(_extract_listings_from_page(page, html))

        # Filter to Atto 3 and pre-filter on year/mileage before hitting detail pages
        candidates = []
        seen = set()
        for listing in listings:
            title = _norm(listing.get("title"))
            if "atto" not in title:
                continue
            lid = listing.get("id")
            if not lid or lid in seen:
                continue
            seen.add(lid)

            year, mileage = parse_year_and_mileage(listing)
            if year is None or not MIN_YEAR <= year <= MAX_YEAR:
                continue
            if mileage is None or mileage > MAX_MILEAGE:
                continue

            listing["year"] = year
            listing["mileage"] = mileage
            listing["price"] = parse_price(listing)
            listing["source"] = "finn"
            candidates.append(listing)

        print(f"{len(candidates)} candidates pass year>={MIN_YEAR} and km<={MAX_MILEAGE}")

        for i, listing in enumerate(candidates, 1):
            print(f"  [{i}/{len(candidates)}] detail: {listing['url']}")
            time.sleep(random.uniform(1.5, 3.5))
            detail_html = fetch_rendered_page(page, listing["url"], timeout=30000)
            if not detail_html:
                listing["detail"] = {}
                continue
            listing["detail"] = parse_detail(detail_html)
            if not listing.get("price"):
                listing["price"] = listing["detail"].get("price") or _price_from_specs(
                    listing["detail"].get("specs", {})
                )

        browser.close()

    return candidates


def scrape_rebil():
    """Scrape rebil.no's own inventory for Atto 3 listings."""
    from playwright.sync_api import sync_playwright

    results = []
    with sync_playwright() as pw:
        browser, context = create_browser(pw)
        page = context.new_page()
        try:
            page.goto(REBIL_URL, wait_until="networkidle", timeout=60000)
            page.wait_for_timeout(4000)
            cards = page.eval_on_selector_all(
                'a[href*="/cars/"]',
                "els => els.map(e => ({href: e.href, text: e.innerText}))",
            )
        except Exception as exc:
            print(f"rebil.no scrape failed: {exc}")
            cards = []
        browser.close()

    for card in cards:
        text = card.get("text", "")
        if "atto" not in _norm(text):
            continue
        lines = [l.strip() for l in text.split("\n") if l.strip()]
        title = next((l for l in lines if "atto" in l.lower()), "BYD Atto 3")

        year = None
        mileage = None
        meta = next((l for l in lines if "km" in l and "•" in l), "")
        year_match = re.search(r"\b(20\d{2})\b", meta)
        if year_match:
            year = int(year_match.group(1))
        km_match = re.search(r"([\d\s ]+)\s*km", meta)
        if km_match:
            digits = re.sub(r"[^\d]", "", km_match.group(1))
            if digits:
                mileage = int(digits)

        price = None
        price_match = re.search(r"([\d\s ]{5,}),-", text)
        if price_match:
            digits = re.sub(r"[^\d]", "", price_match.group(1))
            if digits:
                price = int(digits)

        equipment_line = lines[-1] if lines else ""
        equipment = [e.strip() for e in equipment_line.split(",") if e.strip()]

        if year is None or not MIN_YEAR <= year <= MAX_YEAR:
            continue
        if mileage is None or mileage > MAX_MILEAGE:
            continue

        results.append(
            {
                "source": "rebil",
                "id": "rebil-" + card["href"].rstrip("/").split("/")[-1],
                "url": card["href"],
                "title": title,
                "year": year,
                "mileage": mileage,
                "price": price,
                "detail": {
                    "specs": {},
                    "equipment": equipment,
                    "description": text,
                    "seller": "Rebil",
                },
            }
        )

    print(f"rebil.no: {len(results)} Atto 3 candidates")
    return results


def rank(candidates):
    ranked = []
    for listing in candidates:
        detail = listing.get("detail") or {}
        (
            score,
            matched,
            missing,
            flags,
            electric_seat,
            opening_roof,
            fixed_roof,
        ) = score_listing(detail)

        specs = detail.get("specs", {})
        listing["equipment_score"] = score
        listing["equipment_matched"] = matched
        listing["equipment_missing"] = missing
        listing["flags"] = flags
        listing["has_electric_seat"] = electric_seat
        listing["has_opening_roof"] = opening_roof
        listing["roof"] = (
            "Panorama soltak (kan åpnes)"
            if opening_roof
            else "Panorama glasstak (fast)"
            if fixed_roof
            else "Ingen glasstak oppgitt"
        )
        listing["meets_must_haves"] = electric_seat and opening_roof
        listing["battery"] = specs.get("Batterikapasitet", "")
        listing["range_wltp"] = next(
            (v for k, v in specs.items() if k.startswith("Rekkevidde")), ""
        )
        listing["dealer_or_private"] = detail.get("seller", "")
        listing["price_excl_omreg"] = specs.get("Pris eksl. omreg.", "")
        listing["is_lease_takeover"] = any(
            "leasing" in k.lower() or "leasingavtale" in k.lower() for k in specs
        )
        if listing["is_lease_takeover"]:
            listing["flags"] = listing["flags"] + ["Leasingovertakelse"]
        ranked.append(listing)

    ranked.sort(
        key=lambda x: (
            x.get("is_lease_takeover", False),
            not x["meets_must_haves"],
            not x["has_electric_seat"],
            -x["equipment_score"],
            x.get("price") or 10**9,
        )
    )
    return ranked


def format_slack(ranked, previous_ids=None):
    previous_ids = previous_ids or set()
    qualified = [
        x for x in ranked if x["meets_must_haves"] and not x.get("is_lease_takeover")
    ]
    top = qualified[:5] if qualified else ranked[:5]

    lines = [
        f"*BYD Atto 3 daily scan* – {len(ranked)} match {MIN_YEAR}-{MAX_YEAR} / under "
        f"{MAX_MILEAGE:,} km".replace(",", " "),
        f"{len(qualified)} meet both must-haves "
        f"(electric driver's seat + opening panoramic roof).",
        "",
    ]

    for i, car in enumerate(top, 1):
        price = car.get("price")
        price_text = f"{price:,} kr".replace(",", " ") if price else "price n/a"
        new_tag = " :new:" if car["id"] not in previous_ids else ""
        if car.get("is_lease_takeover"):
            new_tag += " _(leasingovertakelse)_"
        lines.append(
            f"*{i}. {car.get('title')}* – {price_text}{new_tag}\n"
            f"   {car.get('year')} · {car.get('mileage'):,} km".replace(",", " ")
            + f" · spec score {car['equipment_score']}\n"
            f"   Roof: {car['roof']}\n"
            f"   Has: {', '.join(car['equipment_matched'][:8]) or 'n/a'}\n"
            f"   [{car.get('source', 'finn')}] {car.get('url')}"
        )

    near = [x for x in ranked if x not in top][:4]
    if near:
        lines.append("\n_Near misses:_")
        for car in near:
            price = car.get("price")
            price_text = f"{price:,} kr".replace(",", " ") if price else "price n/a"
            gap = []
            if not car["has_opening_roof"]:
                gap.append("no opening roof")
            if not car["has_electric_seat"]:
                gap.append("no electric seat")
            if car.get("is_lease_takeover"):
                gap.append("lease takeover")
            lines.append(
                f"• {car.get('year')} · {car.get('mileage'):,} km".replace(",", " ")
                + f" · {price_text} · {', '.join(gap) or 'ok'} · {car.get('url')}"
            )

    new_ids = [x["id"] for x in ranked if x["id"] not in previous_ids]
    if previous_ids and new_ids:
        lines.append(f"\n{len(new_ids)} new listing(s) since last run.")

    return "\n".join(lines)


def post_slack(webhook_url, text):
    payload = json.dumps({"text": text}).encode("utf-8")
    req = urllib.request.Request(
        webhook_url, data=payload, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=20) as response:
        return response.status


def load_previous_ids(path):
    try:
        with open(path, encoding="utf-8") as f:
            return {x["id"] for x in json.load(f).get("listings", []) if x.get("id")}
    except (OSError, ValueError, KeyError):
        return set()


def main():
    parser = argparse.ArgumentParser(description="Find and rank BYD Atto 3 listings")
    parser.add_argument("--output", "-o", default="atto_listings.json")
    parser.add_argument("--slack-webhook", default=os.environ.get("SLACK_WEBHOOK_URL"))
    parser.add_argument("--no-slack", action="store_true")
    args = parser.parse_args()

    previous_ids = load_previous_ids(args.output)

    candidates = scrape_candidates() + scrape_rebil()
    ranked = rank(candidates)

    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(
            {
                "search_url": SEARCH_URL,
                "scraped_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "filters": {
                "min_year": MIN_YEAR,
                "max_year": MAX_YEAR,
                "max_mileage": MAX_MILEAGE,
            },
                "total_listings": len(ranked),
                "listings": ranked,
            },
            f,
            ensure_ascii=False,
            indent=2,
        )
    print(f"Saved {len(ranked)} ranked listings to {args.output}")

    message = format_slack(ranked, previous_ids)
    print("\n" + message)

    if not args.no_slack:
        if not args.slack_webhook:
            print("\nNo Slack webhook configured, skipping post", file=sys.stderr)
        else:
            status = post_slack(args.slack_webhook, message)
            print(f"\nPosted to Slack (HTTP {status})")


if __name__ == "__main__":
    main()
