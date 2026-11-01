"""Bot 1: NRW-first job discovery into a scored 15-column Google Sheet.

The former 4-column Jobs tab is kept as an untouched archive. Adzuna is for
discovery and counts only: its indirect URLs are never presented as applications.
"""
import json
import os
import requests
import xml.etree.ElementTree as ET
from urllib.parse import quote
from tracker import (
    CONFIG, HTTP_TIMEOUT, Job, ashby_feed, greenhouse_feed, lever_feed,
    personio_feed, adzuna_search, suitable, verify_live_job_url,
    sheets_session, clean_url, norm, unique_key, broad_germany_location,
)
from job_scoring import HEADERS, make_row, score_job


def read_tracker_sheet(session):
    spreadsheet_id = CONFIG["spreadsheet_id"]
    quoted_range = quote(CONFIG["sheet_tab"] + "!A:O", safe="")
    response = session.get(
        f"https://sheets.googleapis.com/v4/spreadsheets/{spreadsheet_id}/values/{quoted_range}",
        timeout=HTTP_TIMEOUT,
    )
    response.raise_for_status()
    values = response.json().get("values", [])
    if not values or values[0] != HEADERS:
        raise RuntimeError("Job Tracker header mismatch: refusing to overwrite anything")
    return values[1:]


def dedup_scored_jobs(jobs, existing, cap):
    """Deduplicate URLs and company/title/location without losing separate cities."""
    seen_links = {clean_url(r[11]) for r in existing if len(r) >= 12 and r[11]}
    seen_keys = {(norm(r[1]).strip(), norm(r[0]).strip(), norm(r[3]).strip())
                 for r in existing if len(r) >= 4}
    locations = {}
    for row in existing:
        if len(row) >= 4:
            k = (norm(row[1]).strip(), norm(row[0]).strip())
            locations.setdefault(k, set()).add(norm(row[3]).strip())
    selected = []
    for job in jobs:
        link = clean_url(job.url)
        key = unique_key(job)
        previous_places = locations.get(key[:2], set())
        broad_duplicate = bool(previous_places) and (
            broad_germany_location(job.location)
            or any(broad_germany_location(p) for p in previous_places))
        if link in seen_links or key in seen_keys or broad_duplicate:
            continue
        selected.append(job)
        seen_links.add(link)
        seen_keys.add(key)
        locations.setdefault(key[:2], set()).add(key[2])
        if len(selected) >= cap:
            break
    return selected


def append_tracker_sheet(session, rows):
    if not rows:
        return 0
    spreadsheet_id = CONFIG["spreadsheet_id"]
    quoted_range = quote(CONFIG["sheet_tab"] + "!A:O", safe="")
    response = session.post(
        f"https://sheets.googleapis.com/v4/spreadsheets/{spreadsheet_id}/values/{quoted_range}:append",
        params={"valueInputOption": "RAW", "insertDataOption": "INSERT_ROWS"},
        json={"majorDimension": "ROWS", "values": rows},
        timeout=HTTP_TIMEOUT,
    )
    response.raise_for_status()
    return len(rows)


def main():
    session = requests.Session()
    collectors = {
        "ashby": ashby_feed,
        "lever": lever_feed,
        "greenhouse": greenhouse_feed,
        "personio": personio_feed,
    }
    jobs, checked, failures = [], [], []
    for feed in CONFIG["official_feeds"]:
        try:
            found = collectors[feed["type"]](session, feed)
            jobs.extend(found)
            checked.append(f"{feed['company']}: {len(found)} visible")
        except (requests.RequestException, ET.ParseError, ValueError,
                KeyError, TypeError) as exc:
            failures.append(f"{feed['company']}: {type(exc).__name__}")

    # Adzuna provides useful discovery signals, not verified direct application
    # links. Report qualified leads separately until employer URLs are resolved.
    adzuna_jobs = adzuna_search(session)
    jobs.extend(adzuna_jobs)
    accepted, adzuna_leads = [], 0
    geography_rejected = 0
    for job in jobs:
        if not suitable(job, trust_de=(job.source == "adzuna")):
            continue
        result = score_job(job)
        if result is None:
            geography_rejected += 1
            continue
        if job.source == "adzuna":
            adzuna_leads += 1
            continue
        accepted.append(job)

    accepted.sort(key=lambda job: (
        -(score_job(job) or {"score": 0})["score"],
        job.company.lower(), job.title.lower(),
    ))

    existing, google = [], None
    if os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON"):
        google = sheets_session()
        existing = read_tracker_sheet(google)

    proposed = dedup_scored_jobs(accepted, existing, CONFIG["max_new_jobs_per_run"])
    verified = [job for job in proposed if verify_live_job_url(session, job)]
    new_rows = [make_row(job) for job in verified]
    new_rows = [row for row in new_rows if row is not None]
    appended = append_tracker_sheet(google, new_rows) if google else 0

    report = {
        "sheet_tab": CONFIG["sheet_tab"],
        "feeds_checked": checked,
        "feeds_failed": failures,
        "all_source_listings_seen": len(jobs),
        "nrw_or_germany_remote_ats_candidates": len(accepted),
        "adzuna_leads_not_appended": adzuna_leads,
        "geography_or_extra_language_rejections": geography_rejected,
        "existing_tracker_rows": len(existing),
        "new_verified_matches": len(new_rows),
        "job_links_rejected": len(proposed)-len(verified),
        "rows_appended": appended,
    }
    if not google:
        report["warning"] = "Dry run only: Sheets credential missing"
    print(json.dumps(report, ensure_ascii=False, indent=2))
    for row in new_rows[:25]:
        print(" | ".join(str(x) for x in (row[0], row[1], row[3], row[7], row[11])))
    if not checked:
        raise RuntimeError("No official employer feed succeeded; scanner cannot establish coverage")


if __name__ == "__main__":
    main()
