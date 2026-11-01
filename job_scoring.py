"""Explainable, conservative scoring for NRW-first marketing job discovery.

Salary suggestions are heuristic negotiating ranges, NOT verified market rates.
All automatic suitability decisions must remain reviewable by the user.
"""
from __future__ import annotations

import re
import unicodedata
from datetime import datetime
from zoneinfo import ZoneInfo

HEADERS = [
    "Job Title", "Company", "Employer Type", "City / Location",
    "Work Style", "Language Fit", "Experience Fit", "Priority",
    "Priority Score", "Salary Estimate (€ gross/year)",
    "Advertised Salary (€ gross/year)", "Job Link", "Application Status",
    "Date Found", "Notes"
]

PRIMARY = ["Wuppertal", "Bonn", "Cologne", "Köln", "Düsseldorf", "Duesseldorf", "Essen", "Duisburg"]
NEARBY = ["Leverkusen", "Solingen", "Remscheid", "Neuss", "Ratingen", "Hilden",
          "Langenfeld", "Mülheim", "Muelheim", "Oberhausen", "Bochum",
          "Dortmund", "Krefeld", "Hagen", "Aachen", "Monheim", "Bergisch Gladbach"]

REMOTE_DE = re.compile(
    r"\b(remote\s*(?:[-–/]\s*)?(?:in\s+|from\s+)?(?:germany|deutschland|de)\b"
    r"|(?:germany|deutschland)[-\s]*(?:based\s+)?remote\b"
    r"|work remotely (?:from |anywhere in )?(?:germany|deutschland)\b"
    r"|remote[-\s]*first[^.]{0,90}(?:germany|deutschland)\b"
    r"|(?:deutschlandweit|bundesweit)\s*(?:remote|homeoffice)\b)",re.I)
ENGLISH_REQUIRED = re.compile(
    r"(?:english\s+(?:is\s+)?(?:our\s+)?(?:working|company|primary)\s+language"
    r"|(?:working|company)\s+language\s+(?:is\s+)?english"
    r"|german\s+(?:is\s+)?(?:not\s+required|optional|only a plus)"
    r"|no\s+german\s+(?:language\s+)?required)",re.I)
OTHER_LANGUAGE = re.compile(r"\b(?:russian|turkish|french|spanish|polish|dutch|italian|arabic|japanese|chinese)\s*[- ]?speaking\b", re.I)
STRONG_FIT = re.compile(
    r"\b(programmatic|paid\s*(?:media|search|social)|performance\s*marketing"
    r"|digital\s*advertising|retail\s*media|media\s*(?:buyer|buying|planning|strategy)"
    r"|digital\s*media|growth\s*marketing|customer\s*acquisition|acquisition\s*marketing)\b", re.I)
GOOD_FIT = re.compile(
    r"\b(growth|marketing|martech|marketing\s*technology|crm|lifecycle"
    r"|demand\s*generation|e.?commerce|analytics|brand|customer\s*marketing)\b", re.I)
SENIOR = re.compile(r"\b(head|director|vice president|vp|principal)\b",re.I)
LEAD = re.compile(r"\b(senior|sr\.?|lead|team lead|global|regional)\b",re.I)
CONSULTING_NAMES = {"tte strategy", "a11", "accenture", "deloitte", "pwc", "bcg", "wpp media", "omnicom media"}

def normalize(s: str) -> str:
    return "".join(ch for ch in unicodedata.normalize("NFKD", (s or "").casefold())
                   if not unicodedata.combining(ch)).replace("ß","ss")

def matches_city(text: str, names: list[str]) -> bool:
    t = normalize(text)
    return any(re.search(r"(?<!\w)" + re.escape(normalize(n)) + r"(?!\w)", t)
               for n in names)

def geography(job):
    """Return geographic fit, never assume an office-city hybrid is Germany-remote."""
    loc=job.location or ""
    desc=job.description or ""
    if job.country and normalize(job.country) not in {"germany","deutschland","de","deu","ger"}:
        return None
    if REMOTE_DE.search(loc) or REMOTE_DE.search(desc[:14000]):
        return "Germany remote"
    if matches_city(loc, PRIMARY):
        return "NRW preferred"
    if matches_city(loc, NEARBY):
        return "NRW nearby"
    return None

def work_style(job, geog):
    loc=(job.location or "").lower()
    description=(job.description or "").lower()
    if geog=="Germany remote":
        return "Remote Germany"
    if "hybrid" in loc or re.search(r"\bhybrid\b",description):
        return "Hybrid (confirm days)"
    if any(word in loc for word in ["on-site","onsite","on site"]):
        return "On-site"
    if "on-site" in description or "on site" in description:
        return "On-site (confirm)"
    return "Not specified"

GERMAN_TEXT_WORDS = re.compile(
    r"\\b(?:du|dein|deine|deinen|deinem|deiner|dich|dir|uns|unsere|wir|mit|und|für|bei|sowie|"
    r"deutsch|deutsche|deutschen|kenntnisse|kannst|bringst|erfahrung|bieten|dabei|"
    r"stellen|verständnis|über|übernimmst|entwickelst|verantwortung|bist)\\b", re.I)
ENGLISH_TEXT_WORDS = re.compile(
    r"\\b(?:you|your|we|our|with|and|the|for|will|are|have|skills|experience|"
    r"responsibilities|role|team|work|marketing|customer|business)\\b", re.I)
GERMAN_LANGUAGE_MANDATORY = re.compile(
    r"(?:fließend\\w*|fliessend\\w*|sehr gute\\w*|verhandlungssicher\\w*)"
    r"[^.]{0,55}deutsch(?:kenntnisse|-\\s*und\\s*englischkenntnisse)"
    r"|(?:kommunikation|kommunizieren)[^.]{0,65}auf\\s+deutsch"
    r"|deutsch\\s+(?:und|&)\\s+englisch[^.]{0,65}(?:wort|schrift|beherrschst)", re.I)

def language_fit(job):
    full=(job.title or "")+"\\n"+(job.description or "")
    if OTHER_LANGUAGE.search(job.title or ""):
        return None
    if GERMAN_LANGUAGE_MANDATORY.search(full):
        return None
    german_count=len(GERMAN_TEXT_WORDS.findall(full))
    english_count=len(ENGLISH_TEXT_WORDS.findall(full))
    if german_count>=14 and german_count>english_count*1.6 and not ENGLISH_REQUIRED.search(full):
        # An English company boilerplate followed by a German job advertisement
        # is not evidence that the role is suitable for an English-only applicant.
        return None
    if ENGLISH_REQUIRED.search(full):
        return "English-first indicated"
    return "English ad; confirm German"

def experience_fit(job):
    t=job.title or ""
    if STRONG_FIT.search(t):
        return "Strong - digital/media/growth"
    if GOOD_FIT.search(t):
        return "Adjacent - marketing/growth"
    return "Stretch - check requirements"

def salary_estimate(job):
    """Broad negotiation range only, not a market benchmark or salary fact."""
    title=job.title or ""
    if SENIOR.search(title):
        return "€85k–110k (heuristic)"
    if LEAD.search(title):
        return "€75k–95k (heuristic)"
    return "€60k–80k (heuristic)"

def employer_type(job):
    name=normalize(job.company).strip()
    if name in CONSULTING_NAMES or "agency" in name or "consulting" in name:
        return "Agency / consulting (likely)"
    if job.source in {"ashby","lever","greenhouse","personio"}:
        return "In-house / brand (likely)"
    return "Unconfirmed"

def score_job(job, preference=None):
    geo=geography(job)
    lang=language_fit(job)
    if not geo or not lang:
        return None
    experience=experience_fit(job)
    style=work_style(job,geo)
    score=20 if geo=="NRW preferred" else (17 if geo=="NRW nearby" else 19)
    score+=32 if experience.startswith("Strong") else (24 if experience.startswith("Adjacent") else 12)
    score+=15 if lang.startswith("English-first") else 9
    score+=15 if SENIOR.search(job.title) else (12 if LEAD.search(job.title) else 8)
    score+=10 if style.startswith("Remote") else (8 if style.startswith("Hybrid") else 5)
    mx=job.salary_max_eur
    score+=8 if mx is not None and mx>=80000 else (5 if mx is not None and mx>=50000 else 4)
    score=min(100,score)
    level="P1 - High" if score>=82 else ("P2 - Good" if score>=69 else "P3 - Review")
    notes=["Confirm language, work arrangement and exact compensation before applying"]
    if geo=="Germany remote":
        notes.append("Check permitted residence and required office visits")
    if "Not specified" in style:
        notes.append("Work style not published")
    if job.salary_max_eur is None:
        notes.append("Salary estimate is a negotiation heuristic, not advertised pay")
    return {"geo":geo,"language":lang,"experience":experience,"style":style,
            "score":score,"priority":level,"notes":"; ".join(notes)}

def make_row(job, now=None):
    result=score_job(job)
    if result is None:
        return None
    advertised=("Up to €{:,.0f} (source max; verify)".format(job.salary_max_eur)
                if job.salary_max_eur is not None else "Not disclosed")
    when=(now or datetime.now(ZoneInfo("Europe/Berlin"))).strftime("%Y-%m-%d")
    return [job.title,job.company,employer_type(job),job.location,result["style"],
            result["language"],result["experience"],result["priority"],result["score"],
            salary_estimate(job),advertised,job.url,"New",when,result["notes"]]
