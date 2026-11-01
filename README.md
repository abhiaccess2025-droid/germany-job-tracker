# Bot 1 — NRW-first Weekly Job Scanner

Bot 1 scans configured public employer recruiting systems, filters and ranks jobs for a Germany-based senior digital/programmatic marketing professional, and adds verified direct employer-hosted vacancies to Google Sheets. It never applies or sends personal details.

## Schedule and run

- **Saturday 02:00 Europe/Berlin** (DST-aware GitHub Actions cron).
- Workflow: [Bot 1 - NRW Job Scanner](https://github.com/abhiaccess2025-droid/germany-job-tracker/actions)
- Run manually via Actions → Bot 1 - NRW Job Scanner → Run workflow.
- Workflow runs `python tracker_v2.py`, after running unit tests.
- Three existing GitHub repository secrets are reused: `GOOGLE_SERVICE_ACCOUNT_JSON`, `ADZUNA_APP_ID`, and `ADZUNA_APP_KEY`. Never paste secrets into code, README or chat.

## Google Sheets

[Existing Google spreadsheet](https://docs.google.com/spreadsheets/d/1Pv1jG6vC9RO9jsdEOf3eivdCFHhyAcXWGCYo9MuTsRs/edit).

- **Job Tracker**: the active 15-column sheet for Bot 1, with job title, company, employer type (inferred), location, work style, language fit, experience fit, priority, priority score, salary *estimate*, advertised salary, verified job link, application status, date found and notes.
- **Jobs**: preserved historical four-column archive. Older entries may be expired or indirect, so they are not automatically upgraded to the active tracker.
- Application status starts as `New`, and can be manually changed to `Review`, `Approved for documents`, `Applied`, `Rejected` or `Closed`. A future Bot 2 can consume `Approved for documents`.

## Location policy

Primary locations are Wuppertal, Bonn, Cologne/Köln, Düsseldorf, Essen and Duisburg. Nearby places such as Leverkusen, Neuss, Solingen, Remscheid, Bochum, Dortmund and Krefeld are also eligible. Positions explicitly workable remotely **from Germany** are eligible across all German cities. On-site or ordinary hybrid roles based only in distant German cities are excluded unless also genuinely Germany-remote.

`config.json` preserves regional preferences. The code in `job_scoring.py` currently implements the geographic matching.

## Salary and priority

- **€50,000 gross fixed per year** is the discovery floor when a credible confirmed salary cap is disclosed; unspecified salaries are allowed.
- Preferred higher-pay focus: €75k–€80k+, with €80k+ a high-priority signal.
- Estimated salary in the Sheet is an unverified *heuristic negotiation band*, **not** an advertised employer offer or independent market benchmark. Advertised salary is kept in a different column, and most openings will say `Not disclosed`.
- Priority score is an explainable rule-based estimate based on role fit, job level, NRW/remote location, language indication, work style and any confirmed salary maximum. It is not an AI assessment of the full CV.
- An English-language job advert does **not** prove that German is optional; ambiguous jobs are marked for confirmation. Roles explicitly demanding fluent/business German are filtered.

## Source quality and limits

There are currently 28 configured ATS employer feeds (Ashby, Lever, Greenhouse and Personio). They are **not** all 65 saved target employers or all vacancies across NRW.

Adzuna can suggest relevant opportunities, but its aggregator links are not direct employer applications. The scanner logs those as unverified leads and does not insert them automatically. For jobs collected from official ATS feeds, the scanner additionally checks the individual page for HTTP errors and obvious closed-job messaging before adding them. A valid response still cannot guarantee the role remains open all week.

The scanner does not yet recheck and remove every old row on each run. Historical records, estimated salary bands, work-style classification and language indications must be reviewed before applying. It never auto-applies.

## Next agent (not configured)

Bot 2 is planned separately for Saturday 06:00. It will generate role-specific CV and cover-letter PDFs only after the first bot succeeds and has provided suitable, verified job records. No document agent, Google Drive PDF export, or application submission is active yet.
