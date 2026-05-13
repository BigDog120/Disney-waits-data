#!/usr/bin/env python3
"""
Walking Wait Times — Disney Data Collector
Runs every hour via GitHub Actions.
Fetches live wait times from Queue-Times API and builds a daily JSON dataset.
"""

import json
import os
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone, date

# ── Parks ─────────────────────────────────────────────────────────────────────

PARKS = [
    {"id": 6, "name": "Magic Kingdom",     "emoji": "🏰"},
    {"id": 5, "name": "EPCOT",             "emoji": "🌍"},
    {"id": 7, "name": "Hollywood Studios", "emoji": "🎬"},
    {"id": 8, "name": "Animal Kingdom",    "emoji": "🦁"},
]

BASE_URL = "https://queue-times.com/parks/{}/queue_times.json"
DATA_DIR = "data"

# ── Fetch ─────────────────────────────────────────────────────────────────────

def fetch_park(park, retries=3, backoff=5):
    url = BASE_URL.format(park["id"])
    req = urllib.request.Request(
        url, headers={"User-Agent": "WalkingWaitTimes/1.0"}
    )
    last_err = None
    for attempt in range(1, retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read())
        except Exception as e:
            last_err = e
            if attempt < retries:
                wait = backoff * attempt
                print(f"    ↩ Attempt {attempt} failed ({e}), retrying in {wait}s…")
                time.sleep(wait)
    raise last_err


def extract_rides(raw, park):
    """Return a dict of ride_id → ride snapshot for open rides with wait > 0."""
    rides = {}
    for land in raw.get("lands", []):
        for ride in land.get("rides", []):
            if ride.get("is_open") and ride.get("wait_time", 0) > 0:
                rides[str(ride["id"])] = {
                    "id":         ride["id"],
                    "name":       ride["name"],
                    "park_name":  park["name"],
                    "park_emoji": park["emoji"],
                    "wait_time":  ride["wait_time"],
                }
    return rides

# ── Storage ───────────────────────────────────────────────────────────────────

def load_json(path):
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return None


def save_json(path, data):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def today_path():       return os.path.join(DATA_DIR, "today.json")
def yesterday_path():   return os.path.join(DATA_DIR, "yesterday.json")
def archive_path(d):    return os.path.join(DATA_DIR, f"{d}.json")

# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    today_str = date.today().isoformat()
    now_str   = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    print(f"=== Walking Wait Times Collector — {now_str} ===\n")

    # ── Load or create today's file ───────────────────────────────────────────
    existing = load_json(today_path())

    if existing and existing.get("date") != today_str:
        old_date = existing["date"]
        print(f"New day detected — archiving {old_date}...")
        save_json(archive_path(old_date), existing)
        save_json(yesterday_path(), existing)
        print(f"  Saved {old_date}.json  ({len(existing['rides'])} rides, "
              f"{existing['sample_count']} samples)\n")
        existing = None

    if existing is None:
        existing = {
            "date":         today_str,
            "sample_count": 0,
            "last_updated": now_str,
            "rides":        {},
        }

    # ── Fetch all parks ───────────────────────────────────────────────────────
    all_rides = {}
    any_success = False

    for park in PARKS:
        try:
            raw        = fetch_park(park)
            park_rides = extract_rides(raw, park)
            all_rides.update(park_rides)
            print(f"  {park['emoji']}  {park['name']}: {len(park_rides)} open rides")
            any_success = True
        except urllib.error.URLError as e:
            print(f"  ⚠️  {park['name']} fetch failed: {e}", file=sys.stderr)
        except Exception as e:
            print(f"  ⚠️  {park['name']} error: {e}", file=sys.stderr)

    if not any_success:
        print("\nAll park fetches failed — aborting.", file=sys.stderr)
        sys.exit(1)

    # ── Append new samples ────────────────────────────────────────────────────
    for ride_id, ride in all_rides.items():
        if ride_id not in existing["rides"]:
            existing["rides"][ride_id] = {
                "id":         ride["id"],
                "name":       ride["name"],
                "park_name":  ride["park_name"],
                "park_emoji": ride["park_emoji"],
                "wait_times": [],
            }
        existing["rides"][ride_id]["wait_times"].append(ride["wait_time"])

    # ── Update metadata ───────────────────────────────────────────────────────
    counts = [len(r["wait_times"]) for r in existing["rides"].values()]
    existing["sample_count"] = max(counts) if counts else 0
    existing["last_updated"] = now_str

    save_json(today_path(), existing)

    print(f"\n✓  Saved {len(existing['rides'])} rides "
          f"with up to {existing['sample_count']} samples each.")


if __name__ == "__main__":
    main()
