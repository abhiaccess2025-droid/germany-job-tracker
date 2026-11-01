# Germany-wide job discovery → your four-column Google Sheet

This is a **ready-to-deploy** supplemental collector for the existing ChatGPT Friday career-page task. The existing Google Sheet and its four columns stay unchanged. The collector's job filters and employer feed coverage are conservative: the sheet is a shortlist, not a complete German job database. The script does not apply to jobs or send your CV anywhere.

## What is live and what is not

- **Already live in ChatGPT:** your recurring Friday 23:30 Europe/Berlin task with all 65 named employers and Germany-wide location eligibility.
- **Not deployed automatically:** this GitHub Actions collector. Deploying it requires a GitHub repository, a Google Sheets service account, and (optionally) Adzuna credentials.
- **Coverage is partial, not every company in Germany:** 15 official employer-feed configurations are included (Ashby, Lever, Greenhouse, and Personio). Some feeds can fail or change, and not every one of the 65 employers has an API connection. You can add confirmed Greenhouse/Lever/Ashby/Personio job board identifiers. For broader searches across other companies, turn on Adzuna.
- **Job links:** the collector no longer appends Adzuna `details/` URLs to your Google Sheet, since they are not verified employer application links. Adzuna is used for Germany-wide discovery; employer-hosted ATS URLs are written to the Sheet. Relevant Adzuna leads lacking official URLs appear in run statistics but are not appended.
- **Language:** the script excludes obvious *explicit* German-language requirements and requires English-language job-description signals. It cannot guarantee that an English description means the working language is English.
- **Salary:** uses €50,000 gross fixed annual compensation as a discovery floor when a confirmed maximum is published below it; roles with undisclosed pay remain eligible. €75,000–€80,000+ remains the preferred negotiated earnings range for high-fit roles, not a hard search cutoff. Adzuna predicted salary ranges are not treated as confirmed facts.

## One-time setup

1. Create a **private GitHub repository** and upload all contents of this folder (including `.github/workflows/weekly-jobs.yml`).
2. In [Google Cloud Console](https://console.cloud.google.com/), create a Google Cloud project or choose an existing one. Enable **Google Sheets API**. Create a **service account** and generate a JSON key for it. Guard the key as a secret; do **not** paste it in ChatGPT or commit it to GitHub.
3. Open your existing [Google Sheet](https://docs.google.com/spreadsheets/d/1Pv1jG6vC9RO9jsdEOf3eivdCFHhyAcXWGCYo9MuTsRs/edit), click **Share**, and give the service account `client_email` **Editor** access. This is separate from the ChatGPT Google Drive connection.
4. In GitHub repository **Settings → Secrets and variables → Actions → New repository secret**, add `GOOGLE_SERVICE_ACCOUNT_JSON` with the complete JSON key as the secret value.
5. (Recommended for broad Germany-wide discovery.) Get API credentials at [Adzuna](https://developer.adzuna.com/) and add repository secrets `ADZUNA_APP_ID` and `ADZUNA_APP_KEY`.
6. Go to **Actions → Weekly Germany Job Tracker → Run workflow** for an initial test. Verify the new rows in the Sheet. The recurring run is Friday 23:30 in Berlin time, including DST adjustment.

Adzuna credentials enable broader Germany-wide discovery, but Adzuna links will not be appended unless they are direct employer job URLs. Google service-account JSON is required for unattended Sheet writes. Without Adzuna, the script checks the configured public ATS feeds. The 15 configured public feeds can be queried without Adzuna credentials.

## Adding an official career feed

Update `config.json` → `official_feeds`. **Do not guess** board IDs or scrape inaccessible pages.

```json
{"company": "Verified Company", "type": "ashby", "board": "VerifiedAshbyBoardName"}
{"company": "Verified Company", "type": "greenhouse", "board": "verified-greenhouse-token"}
{"company": "Verified Company", "type": "lever", "board": "verified-lever-site", "eu": true}
{"company": "Verified Company", "type": "personio", "board": "verified.jobs.personio.com"}
```

Company names in `employers` are a target list, **not evidence that an API exists** for each company. The ChatGPT recurring task continues to look for official postings across the full 65-company watchlist; this separate API collector works only with explicitly configured official feeds and its optional Adzuna search.

## Running locally

```bash
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
# A dry run fetches public job data, shows potential rows and does NOT modify your sheet:
python tracker.py
```

Do not leave credentials in `.env` files committed to GitHub. GitHub Action failures should be reviewed under the **Actions** tab. Some public feeds may be temporarily unavailable or rate-limited; failed sources are reported in the run log rather than silently treated as zero jobs.

## Current sheet

[Weekly Cologne Job Opportunities](https://docs.google.com/spreadsheets/d/1Pv1jG6vC9RO9jsdEOf3eivdCFHhyAcXWGCYo9MuTsRs/edit)

Existing columns are preserved **exactly**: Company | Job Title | Location | Job Link.
