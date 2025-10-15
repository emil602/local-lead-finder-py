import csv
import io
import os
import time
from dataclasses import dataclass, asdict
from typing import List

import requests
from dotenv import load_dotenv
from flask import Flask, render_template, request, jsonify, make_response

load_dotenv()

API_KEY = os.getenv("GOOGLE_PLACES_API_KEY")
SECRET_KEY = os.getenv("FLASK_SECRET_KEY", "dev-secret")

app = Flask(__name__)
app.secret_key = SECRET_KEY


@dataclass
class Lead:
    name: str
    address: str
    rating: float | None
    reviewCount: int | None
    phone: str | None
    website: str | None
    placeId: str
    lat: float | None
    lng: float | None


def google_text_search_once(query: str, pagetoken: str | None = None):
    """Call Places Text Search once. Return (place_ids, next_page_token)."""
    url = "https://maps.googleapis.com/maps/api/place/textsearch/json"
    params = {"key": API_KEY}
    if pagetoken:
        params["pagetoken"] = pagetoken
    else:
        params["query"] = query

    r = requests.get(url, params=params, timeout=30)
    data = r.json()

    place_ids = [it.get("place_id") for it in data.get("results", []) if it.get("place_id")]
    next_token = data.get("next_page_token")
    return place_ids, next_token


def google_place_details(place_id: str) -> Lead | None:
    url = "https://maps.googleapis.com/maps/api/place/details/json"
    fields = ",".join(
        [
            "name",
            "formatted_address",
            "international_phone_number",
            "website",
            "rating",
            "user_ratings_total",
            "geometry",
            "place_id",
        ]
    )
    params = {"place_id": place_id, "fields": fields, "key": API_KEY}
    r = requests.get(url, params=params, timeout=30)
    dj = r.json()
    p = dj.get("result")
    if not p:
        return None

    return Lead(
        name=p.get("name", ""),
        address=p.get("formatted_address", ""),
        rating=p.get("rating"),
        reviewCount=p.get("user_ratings_total"),
        phone=p.get("international_phone_number"),
        website=p.get("website"),
        placeId=p.get("place_id", ""),
        lat=(p.get("geometry") or {}).get("location", {}).get("lat"),
        lng=(p.get("geometry") or {}).get("location", {}).get("lng"),
    )


@app.get("/")
def index():
    html = render_template("index.html")
    return make_response(html, 200, {"Content-Type": "text/html; charset=utf-8"})


@app.post("/api/search")
def api_search():
    data = request.get_json(silent=True) or {}
    category = (data.get("category") or "").strip()
    location = (data.get("location") or "").strip()
    page_token = (data.get("pageToken") or "").strip() or None

    if (not category or not location) and not page_token:
        return jsonify({"error": "category and location are required"}), 400

    query = f"{category} in {location}"

    try:
        place_ids, next_token = google_text_search_once(query, page_token)

        leads: List[Lead] = []
        for pid in place_ids:
            lead = google_place_details(pid)
            if lead:
                leads.append(lead)
            time.sleep(0.08)

        return jsonify({
            "leads": [asdict(l) for l in leads],
            "nextPageToken": next_token or ""
        })
    except requests.HTTPError as e:
        return jsonify({"error": f"HTTP error: {e}"}), 502
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.post("/api/export")
def api_export_csv():
    data = request.get_json(silent=True) or {}
    leads = data.get("leads")
    if not isinstance(leads, list):
        return jsonify({"error": "No leads provided"}), 400

    headers = [
        "Name",
        "Address",
        "Rating",
        "Review Count",
        "Phone",
        "Website",
        "Place ID",
        "Latitude",
        "Longitude",
    ]

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(headers)

    for l in leads:
        writer.writerow(
            [
                l.get("name", "") or "",
                l.get("address", "") or "",
                l.get("rating", "") or "",
                l.get("reviewCount", "") or "",
                l.get("phone", "") or "",
                l.get("website", "") or "",
                l.get("placeId", "") or "",
                l.get("lat", "") or "",
                l.get("lng", "") or "",
            ]
        )

    csv_bytes = buf.getvalue().encode("utf-8")
    resp = make_response(csv_bytes)
    resp.headers["Content-Type"] = "text/csv; charset=utf-8"
    resp.headers["Content-Disposition"] = 'attachment; filename="leads.csv"'
    return resp


if __name__ == "__main__":
    if not API_KEY:
        raise SystemExit(
            "Missing GOOGLE_PLACES_API_KEY. Set it in .env (GOOGLE_PLACES_API_KEY=...)."
        )
    port = int(os.getenv("PORT", "5000"))
    app.run(host="0.0.0.0", port=port, debug=True)
