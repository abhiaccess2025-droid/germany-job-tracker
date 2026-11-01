"""Germany-wide job collector for the user's existing four-column Google Sheet.

Queries explicitly configured official ATS feeds plus (if credentials exist)
Adzuna Germany. It does NOT scrape all 65 employers or guarantee exhaustive
market coverage; a separate ChatGPT scheduled task retains the 65-site watchlist.
"""
from __future__ import annotations

import html
import json
import os
import re
import sys
import time
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse, urlunparse, parse_qsl, urlencode
import xml.etree.ElementTree as ET

import requests

try:
    import google.auth.transport.requests
    from google.oauth2.service_account import Credentials
except ImportError:  # Allow filter-only unit tests without Google dependencies.
    Credentials = None

CONFIG = json.loads((Path(__file__).resolve().parent / "config.json").read_text(encoding="utf-8"))
HTTP_TIMEOUT = 18
HEADERS = {"User-Agent": "PersonalJobTracker/1.0 (read-only public vacancies)", "Accept": "application/json, application/xml, text/xml;q=0.7"}

# No assertions of language eligibility are made based on the language of the
# advertisement alone. This is a candidate filter, not a final eligibility check.
ROLE_WORDS = re.compile(r"\b(marketing|marketer|growth|acquisition|programmatic|paid\s*(?:media|search|social)|retail\s*media|media\s*(?:strategy|planning|manager|lead|director|buyer)|advertising|demand\s*generation|crm|customer\s*marketing|martech|marketing\s*technology|ecommerce|e-commerce|performance\s*media)\b", re.I)
SENIOR_WORDS = re.compile(r"\b(senior|sr\.?|lead|head|director|principal|vice president|vp|global|regional|manager|leiter|leitung)\b", re.I)
JUNIOR_WORDS = re.compile(r"\b(intern(?:ship)?|werkstudent|working student|trainee|ausbildung|apprentice|graduate program|junior|assistant|volunteer|student job)\b", re.I)
ENGLISH_WORDS = re.compile(r"\b(english|you will|your role|your responsibilities|requirements|what you bring|our team|work with|we are looking|your experience|you have|we offer)\b", re.I)
GERMAN_REQ = [
    re.compile(r"\b(fluent|professional|business[- ]fluent|native|advanced|excellent|strong|proficient|working|business level)\s+(?:written and spoken\s+)?german\b", re.I),
    re.compile(r"\b(?:german|deutsch)\s+(?:language\s+)?(?:fluency|proficiency|skills|knowledge|required|mandatory|at (?:least|minimum) [bc][12]|[bc][12])\b", re.I),
    re.compile(r"\b(?:flie(?:ss|ß)end\w*|verhandlungssicher\w*|sehr gute\w*|exzellente\w*|ausgezeichnete\w*)\s+deutschkenntnisse\b", re.I),
    re.compile(r"\bdeutschkenntnisse\s+(?:auf\s+)?(?:niveau\s+)?[bc][12]\b", re.I),
    re.compile(r"\b(?:german|deutsch)\s+(?:and\s+)?english\s+(?:is|are)\s+(?:required|mandatory|essential)\b", re.I),
]
GERMAN_NOT_REQUIRED = re.compile(r"\b(german\s+(?:is\s+)?(?:not\s+required|only\s+a\s+plus|nice\s+to\s+have|optional)|no\s+german\s+required|deutschkenntnisse\s+(?:von\s+vorteil|nicht\s+erforderlich))\b", re.I)
GERMANY_MARKERS = re.compile(r"\b(germany|deutschland|bundesweit|remote\s*[-–]\s*de|remote\s+germany|de\s*[-/]\s*remote)\b", re.I)
GERMAN_CITIES = [
    "Berlin", "Hamburg", "Munich", "München", "Frankfurt", "Frankfurt am Main", "Cologne", "Köln",
    "Düsseldorf", "Duesseldorf", "Dortmund", "Duisburg", "Essen", "Bonn", "Wuppertal", "Stuttgart", "Leipzig",
    "Dresden", "Hannover", "Hanover", "Bremen", "Nuremberg", "Nürnberg", "Bochum", "Bielefeld", "Münster",
    "Karlsruhe", "Mannheim", "Augsburg", "Wiesbaden", "Mainz", "Aachen", "Kiel", "Magdeburg", "Freiburg",
    "Krefeld", "Lübeck", "Erfurt", "Potsdam", "Rostock", "Kassel", "Hagen", "Saarbrücken", "Hamm",
    "Mülheim", "Muelheim", "Leverkusen", "Oberhausen", "Solingen", "Remscheid", "Paderborn", "Osnabrück",
    "Braunschweig", "Heidelberg", "Darmstadt", "Oldenburg", "Regensburg", "Würzburg", "Wuerzburg",
    "Ingolstadt", "Heilbronn", "Ulm", "Offenbach", "Fürth", "Fuerth", "Reutlingen", "Wolfsburg", "Göttingen",
    "Göttingen", "Neuss", "Neumünster", "Siegen", "Trier", "Aalen", "Ingolstadt", "Coburg", "Erlangen",
    "Pforzheim", "Rüsselsheim", "Ratingen", "Langenfeld", "Hilden", "Eschborn", "Bad Homburg", "Gütersloh"
]

def norm(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", s.casefold()) if not unicodedata.combining(c)).replace("ß", "ss")

def strip_html(s: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", " ", s or ""))

def clean_url(url: str) -> str:
    p = urlparse(url.strip())
    kept = [(k,v) for k,v in parse_qsl(p.query) if k.lower() not in {"utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content", "gh_src", "source", "ref"}]
    return urlunparse((p.scheme.lower(), p.netloc.lower(), p.path.rstrip("/"), "", urlencode(kept), ""))

@dataclass(frozen=True)
class Job:
    company: str
    title: str
    location: str
    url: str
    description: str = ""
    country: str = ""
    salary_max_eur: float | None = None
    source: str = ""

    def row(self):
        return [self.company, self.title, self.location, self.url]

def german_required(text: str) -> bool:
    # Detect explicit German requirements. Exempt when German is clearly optional.
    if GERMAN_NOT_REQUIRED.search(text):
        # Only remove narrow optional phrases; another requirement may remain.
        text = GERMAN_NOT_REQUIRED.sub("", text)
    return any(p.search(text) for p in GERMAN_REQ)

def germany_location(location: str, country: str = "", trust_country_de: bool = False) -> bool:
    if country and norm(country).strip() not in {"de", "deu", "ger", "germany", "deutschland"}:
        return False
    if trust_country_de or (country and norm(country).strip() in {"de", "deu", "ger", "germany", "deutschland"}):
        return True
    s = norm(location)
    if GERMANY_MARKERS.search(s) or " deutschland" in s or re.search(r"(?:,|\s)de(?:$|,|\s|\))", s):
        return True
    return any(re.search(r"(?<!\w)" + re.escape(norm(x)) + r"(?!\w)", s) for x in GERMAN_CITIES)

def suitable(job: Job, trust_de=False) -> bool:
    if not job.url.startswith("https://") or not job.company or not job.title or not job.location:
        return False
    if not germany_location(job.location, job.country, trust_country_de=trust_de):
        return False
    if not ROLE_WORDS.search(job.title) or JUNIOR_WORDS.search(job.title):
        return False
    if not SENIOR_WORDS.search(job.title):
        return False
    desc = strip_html(job.description)
    if german_required(job.title + "\n" + desc):
        return False
    # English description or explicit English required; no German is NOT
    # sufficient proof of an English-speaking team, so user must confirm.
    if len(desc) < 120 or len(ENGLISH_WORDS.findall(desc)) < 2:
        return False
    if job.salary_max_eur is not None and job.salary_max_eur < CONFIG["minimum_target_salary_eur"]:
        return False
    return True

def get_json(session: requests.Session, url: str, params: dict | None = None) -> Any:
    r = session.get(url, params=params, timeout=HTTP_TIMEOUT, headers=HEADERS)
    r.raise_for_status()
    return r.json()

def get_xml(session: requests.Session, url: str, params: dict | None = None) -> ET.Element:
    r = session.get(url, params=params, timeout=HTTP_TIMEOUT, headers={"User-Agent": HEADERS["User-Agent"]})
    r.raise_for_status()
    if len(r.content) > 6_000_000:
        raise ValueError("XML response unexpectedly large")
    return ET.fromstring(r.content)

def ashby_feed(session, feed):
    root = get_json(session, f"https://api.ashbyhq.com/posting-api/job-board/{feed['board']}", {"includeCompensation":"true"})
    jobs = []
    for x in root.get("jobs", []):
        if x.get("isListed") is False:
            continue
        address = (x.get("address") or {}).get("postalAddress") or {}
        country = address.get("addressCountry") or ""
        loc = x.get("location") or address.get("addressLocality") or ""
        all_locs = [loc] + [j.get("location", "") for j in x.get("secondaryLocations", [])]
        loc = " / ".join(j for j in all_locs if j)
        compensation = x.get("compensation") or {}
        euro = [v.get("maxValue") for v in compensation.get("summaryComponents", []) if v.get("currencyCode")=="EUR" and v.get("compensationType")=="Salary" and v.get("interval")=="1 YEAR" and isinstance(v.get("maxValue"),(float,int))]
        jobs.append(Job(feed["company"], x.get("title", ""), loc, x.get("jobUrl", ""), x.get("descriptionPlain") or x.get("descriptionHtml") or "",country, max(euro) if euro else None,"ashby"))
    return jobs

def greenhouse_feed(session, feed):
    root=get_json(session, f"https://boards-api.greenhouse.io/v1/boards/{feed['board']}/jobs", {"content":"true"})
    return [Job(feed['company'], x.get('title',''), (x.get('location') or {}).get('name',''), x.get('absolute_url',''), x.get('content',''), '', None, 'greenhouse') for x in root.get('jobs',[])]

def lever_feed(session, feed):
    base = "https://api.eu.lever.co" if feed.get("eu", False) else "https://api.lever.co"
    out=[]; offset=0
    while offset < 1000:
        batch=get_json(session, f"{base}/v0/postings/{feed['board']}", {"mode":"json", "limit":100,"skip":offset})
        for x in batch:
            out.append(Job(feed['company'],x.get('text',''),(x.get('categories') or {}).get('location',''),x.get('hostedUrl',''),x.get('descriptionPlain',''),'',None,'lever'))
        if len(batch)<100: break
        offset += 100
    return out

def personio_feed(session, feed):
    host=feed['board']
    if not re.fullmatch(r"[a-zA-Z0-9-]+\.jobs\.personio\.(?:com|de)", host):
        raise ValueError('Invalid Personio host')
    root=get_xml(session,f"https://{host}/xml",{"language":"en"})
    out=[]
    for p in root.findall('.//position'):
        title=p.findtext('name') or ''
        office=p.findtext('office') or ''
        identifier=p.findtext('id') or ''
        desc=' '.join((el.text or '') for el in p.findall('.//jobDescriptions//value'))
        if not identifier.isdigit(): continue
        out.append(Job(feed['company'],title,office,f"https://{host}/job/{identifier}?language=en",desc,'',None,'personio'))
    return out

def adzuna_search(session):
    app_id,app_key = os.environ.get('ADZUNA_APP_ID'),os.environ.get('ADZUNA_APP_KEY')
    if not app_id or not app_key:
        print('Adzuna disabled: ADZUNA_APP_ID / ADZUNA_APP_KEY not configured', file=sys.stderr)
        return []
    out=[]
    cfg=CONFIG['adzuna']
    for phrase in cfg['queries']:
        for page in range(1,cfg['pages_per_query']+1):
            try:
                data=get_json(session, f"https://api.adzuna.com/v1/api/jobs/{cfg['country']}/search/{page}",{
                    'app_id':app_id,'app_key':app_key,'what':phrase,
                    'results_per_page':cfg['results_per_page'],'content-type':'application/json'})
                for x in data.get('results',[]):
                    title=x.get('title',''); company=(x.get('company') or {}).get('display_name') or ''
                    loc=(x.get('location') or {}).get('display_name') or 'Germany'
                    link=x.get('redirect_url') or ''
                    desc=x.get('description') or ''
                    # Adzuna often links through its own posting/redirect service;
                    # these links are job-specific, but not always direct employer URLs.
                    mx=x.get('salary_max')
                    salary=mx if isinstance(mx,(float,int)) and mx>0 and not x.get('salary_is_predicted') else None
                    out.append(Job(company,title,loc,link,desc,'DE',salary,'adzuna'))
            except (requests.RequestException,ValueError) as e:
                print(f'Adzuna failed query={phrase!r} page={page}: {e}',file=sys.stderr)
            time.sleep(0.1)
    return out

def unique_key(job: Job):
    return (norm(job.company).strip(), norm(job.title).strip(), norm(job.location).strip())

def deduplicate(jobs: list[Job], existing_rows: list[list[str]], max_new: int):
    seen_urls={clean_url(r[3]) for r in existing_rows if len(r)>3 and r[3]}
    seen_keys={(norm(r[0]).strip(),norm(r[1]).strip(),norm(r[2]).strip()) for r in existing_rows if len(r)>2}
    new=[]
    for j in jobs:
        url=clean_url(j.url); key=unique_key(j)
        if url in seen_urls or key in seen_keys: continue
        new.append(j);seen_urls.add(url);seen_keys.add(key)
        if len(new)>=max_new: break
    return new

def sheets_session():
    if Credentials is None:
        raise RuntimeError('Please install google-auth')
    raw=os.environ.get('GOOGLE_SERVICE_ACCOUNT_JSON')
    if not raw:
        raise RuntimeError('GOOGLE_SERVICE_ACCOUNT_JSON missing: cannot update Google Sheet')
    info=json.loads(raw)
    cred=Credentials.from_service_account_info(info, scopes=['https://www.googleapis.com/auth/spreadsheets'])
    cred.refresh(google.auth.transport.requests.Request())
    session=requests.Session()
    session.headers.update({'Authorization':f'Bearer {cred.token}'})
    return session

def read_sheet(session, config):
    id=config['spreadsheet_id']; tab=config['sheet_tab']
    res=session.get(f'https://sheets.googleapis.com/v4/spreadsheets/{id}/values/{tab}%21A%3AD',timeout=HTTP_TIMEOUT)
    res.raise_for_status()
    values=res.json().get('values',[])
    if not values or values[0][:4]!=['Company','Job Title','Location','Job Link']:
        raise RuntimeError('Sheet header mismatch: stopping to avoid corrupting the sheet')
    return values[1:]

def append_sheet(session, config, new_jobs):
    if not new_jobs: return 0
    id=config['spreadsheet_id']; tab=config['sheet_tab']
    res=session.post(f'https://sheets.googleapis.com/v4/spreadsheets/{id}/values/{tab}%21A%3AD:append',
        params={'valueInputOption':'RAW','insertDataOption':'INSERT_ROWS'},
        json={'majorDimension':'ROWS','values':[j.row() for j in new_jobs]},timeout=HTTP_TIMEOUT)
    res.raise_for_status()
    return len(new_jobs)

def main():
    session=requests.Session()
    feeds=CONFIG['official_feeds']
    jobs=[]; checked=[]; failed=[]
    implementations={'ashby':ashby_feed,'greenhouse':greenhouse_feed,'lever':lever_feed,'personio':personio_feed}
    for f in feeds:
        try:
            fetched=implementations[f['type']](session,f)
            jobs.extend(fetched)
            checked.append(f"{f['company']}: {len(fetched)} visible")
        except (requests.RequestException,ET.ParseError,ValueError,KeyError,TypeError) as exc:
            failed.append(f"{f['company']}: {type(exc).__name__}")
    jobs.extend(adzuna_search(session))
    filtered=[]
    for j in jobs:
        if suitable(j,trust_de=(j.source=='adzuna')):
            filtered.append(j)
    # Prefer official sources over aggregate sources when the same role is seen twice.
    filtered.sort(key=lambda j:(j.source=='adzuna',j.company.lower(),j.title.lower()))
    existing=[]; sheet=None
    if os.environ.get('GOOGLE_SERVICE_ACCOUNT_JSON'):
        sheet=sheets_session()
        existing=read_sheet(sheet,CONFIG)
    new=deduplicate(filtered,existing,CONFIG['max_new_jobs_per_run'])
    summary={'official_feeds_checked':checked,'official_feeds_failed':failed,
             'source_jobs_seen':len(jobs),'jobs_passing_filters':len(filtered),
             'new_jobs_selected':len(new),'existing_sheet_rows':len(existing)}
    if sheet:
        summary['rows_appended']=append_sheet(sheet,CONFIG,new)
    else:
        summary['rows_appended']=0
        summary['warning']='DRY RUN ONLY: Google credentials missing, no Sheet writes made'
    print(json.dumps(summary,ensure_ascii=False,indent=2))
    for j in new[:25]: print('\t'.join(j.row()))
    if failed and not checked and not os.environ.get('ADZUNA_APP_ID'):
        raise RuntimeError('All public feeds failed and Adzuna is not enabled')

if __name__=='__main__':
    main()
