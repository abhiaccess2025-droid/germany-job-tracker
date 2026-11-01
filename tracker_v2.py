"""Bot 1: NRW-first job discovery into a scored 15-column Google Sheet.

The former 4-column Jobs tab is kept as an untouched archive. Adzuna is for
discovery and counts only: its indirect URLs are never presented as applications.
"""
import csv
import json
import os
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
import requests
import xml.etree.ElementTree as ET
from urllib.parse import quote
from tracker import (
    CONFIG, HTTP_TIMEOUT, Job, ashby_feed, greenhouse_feed, lever_feed,
    personio_feed, adzuna_search, suitable, verify_live_job_url,
    sheets_session, clean_url, norm, unique_key, broad_germany_location,
    germany_location, ROLE_WORDS, SENIOR_WORDS, JUNIOR_WORDS,
    german_required, ENGLISH_WORDS, ENGLISH_FUNCTION_WORDS, strip_html,
)
from job_scoring import HEADERS, make_row, score_job, geography, language_fit, work_style


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


AUDIT_HEADERS = [
    "Scanned At (Berlin)", "Source", "Company", "Job Title",
    "Location", "Work Style (inferred)", "Screening Result",
    "Reason / What to Check", "Source Link (UNVERIFIED)",
    "Salary Max € (if provided)"
]


def screening_rejection(job):
    """Explain the scanner's first-stage screening using its actual rules."""
    if not job.company or not job.title or not job.location or not job.url.startswith("https://"):
        return "Missing company, title, location or HTTPS job link"
    if not germany_location(job.location, job.country, trust_country_de=(job.source == "adzuna")):
        return "Not confirmed to be located in Germany"
    if not ROLE_WORDS.search(job.title):
        return "Role title outside configured marketing/media keywords"
    if JUNIOR_WORDS.search(job.title):
        return "Junior, intern, trainee or student role"
    if not SENIOR_WORDS.search(job.title):
        return "Title lacks manager/lead/senior/head/director keywords"
    description = strip_html(job.description)
    if german_required(job.title + "\n" + description):
        return "Explicit German-language requirement detected"
    if len(description) < 80:
        return "Short/incomplete job description for English screening"
    if len(ENGLISH_WORDS.findall(description)) < 1 and len(ENGLISH_FUNCTION_WORDS.findall(description)) < 6:
        return "Insufficient English-language signals in description"
    if job.salary_max_eur is not None and job.salary_max_eur < CONFIG["minimum_target_salary_eur"]:
        return "Confirmed salary maximum below €50,000"
    return "Other first-stage screening rule"


def audit_rows_for_scan(jobs, existing, proposed, verified, scanned_at):
    """One audit row per fetched API listing, including duplicates and exclusions.

    Audit links are raw source URLs. They are deliberately NOT verified applications.
    The full list is a snapshot of the latest scan, not an eligibility shortlist.
    """
    tracked_urls = {clean_url(r[11]) for r in existing if len(r) > 11 and r[11]}
    tracked_keys = {(norm(r[1]).strip(), norm(r[0]).strip(), norm(r[3]).strip())
                    for r in existing if len(r) > 3}
    proposed_urls = {clean_url(j.url) for j in proposed}
    verified_urls = {clean_url(j.url) for j in verified}
    counted_added = set()
    audit = []
    for j in jobs:
        location_ok = geography(j)
        scored = score_job(j) if location_ok is not None else None
        style = work_style(j, location_ok) if location_ok else "Not classified"
        if not suitable(j, trust_de=(j.source == "adzuna")):
            status = "Excluded"
            reason = screening_rejection(j)
        elif not location_ok:
            status = "Excluded"
            reason = "Outside preferred NRW cities; not verified Germany-remote"
        elif scored is None:
            status = "Excluded"
            reason = "Additional language requirement or German-dominant advert"
        elif j.source == "adzuna":
            status = "Unverified lead"
            reason = "Adzuna source link is NOT a confirmed employer application URL"
        else:
            url = clean_url(j.url)
            key = unique_key(j)
            if url in verified_urls and url not in counted_added:
                status = "Added this scan"
                reason = "Verified employer-hosted vacancy; added to Job Tracker"
                counted_added.add(url)
            elif url in tracked_urls or key in tracked_keys:
                status = "Already tracked"
                reason = "Already in the Job Tracker; not added again"
            elif url in proposed_urls and url not in verified_urls:
                status = "Link unverified"
                reason = "Employer-hosted job page did not pass live URL verification"
            else:
                status = "Duplicate / skipped"
                reason = "Duplicate source listing or weekly new-job cap"
        salary = j.salary_max_eur if j.salary_max_eur is not None else ""
        # RAW Sheets input and CSV quoting keep these public job texts as plain data.
        cells = [
            scanned_at, j.source or "unknown", j.company or "", j.title or "",
            j.location or "", style, status, reason, j.url or "", salary,
        ]
        # Avoid formula injection when CSVs are opened in spreadsheet software.
        audit.append(["'" + x if isinstance(x, str) and x[:1] in ("=", "+", "-", "@")
                      else x for x in cells])
    return audit


def save_audit_csv(rows):
    with Path("scan_audit.csv").open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.writer(handle)
        writer.writerow(AUDIT_HEADERS)
        writer.writerows(rows)


def publish_audit_snapshot(session, rows):
    """Replace Scan Audit *data* only, retaining its header and formatting.

    The latest run is browseable in Google Sheets; prior scans are downloadable
    as GitHub workflow artifacts (30-day retention).
    """
    spreadsheet_id = CONFIG["spreadsheet_id"]
    base = f"https://sheets.googleapis.com/v4/spreadsheets/{spreadsheet_id}"
    header_range = quote("Scan Audit!A1:J1", safe="")
    response = session.get(f"{base}/values/{header_range}", timeout=HTTP_TIMEOUT)
    response.raise_for_status()
    actual = response.json().get("values", [])
    if not actual or actual[0] != AUDIT_HEADERS:
        raise RuntimeError("Scan Audit header mismatch; refusing to overwrite audit")

    # Increase the sheet's grid if a scan contains more than 7,999 rows.
    if len(rows) + 1 > 8000:
        response = session.get(base, params={"fields": "sheets(properties(sheetId,title,gridProperties(rowCount)))"},
                               timeout=HTTP_TIMEOUT)
        response.raise_for_status()
        matches = [x["properties"] for x in response.json().get("sheets", [])
                   if x.get("properties", {}).get("title") == "Scan Audit"]
        if not matches:
            raise RuntimeError("Scan Audit sheet missing")
        prop = matches[0]
        if prop["gridProperties"]["rowCount"] < len(rows) + 1:
            grow = {"requests": [{"updateSheetProperties": {
                "properties": {"sheetId": prop["sheetId"],
                               "gridProperties": {"rowCount": len(rows) + 500}},
                "fields": "gridProperties.rowCount"}}]}
            resp = session.post(f"{base}:batchUpdate", json=grow, timeout=HTTP_TIMEOUT)
            resp.raise_for_status()

    clear_range = quote("Scan Audit!A2:J", safe="")
    response = session.post(f"{base}/values/{clear_range}:clear", json={}, timeout=HTTP_TIMEOUT)
    response.raise_for_status()
    for i in range(0, len(rows), 400):
        chunk = rows[i:i + 400]
        first = i + 2
        last = first + len(chunk) - 1
        target = quote(f"Scan Audit!A{first}:J{last}", safe="")
        resp = session.put(f"{base}/values/{target}",
                           params={"valueInputOption": "RAW"},
                           json={"majorDimension": "ROWS", "values": chunk},
                           timeout=HTTP_TIMEOUT)
        resp.raise_for_status()
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
    timestamp = datetime.now(ZoneInfo("Europe/Berlin")).strftime("%Y-%m-%d %H:%M:%S")
    audit_rows = audit_rows_for_scan(jobs, existing, proposed, verified, timestamp)
    save_audit_csv(audit_rows)
    audit_written = publish_audit_snapshot(google, audit_rows) if google else 0

    report = {
        "scan_audit_rows": len(audit_rows),
        "audit_sheet_rows_written": audit_written,
        "audit_csv_file": "scan_audit.csv",
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
