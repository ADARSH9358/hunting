"""Deterministic text helpers: normalization, experience & salary parsing, etc."""
from __future__ import annotations

import hashlib
import html
import re
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime, timezone

from bs4 import BeautifulSoup

# ---------------------------------------------------------------- html / text

def html_to_text(raw: str | None) -> str:
    if not raw:
        return ""
    if "<" not in raw and "&" in raw:
        raw = html.unescape(raw)
    if "<" in raw:
        soup = BeautifulSoup(raw, "lxml")
        for t in soup(["script", "style", "noscript"]):
            t.decompose()
        for a in soup.select('a[href^="mailto:"]'):  # keep recruiter addresses hidden behind links
            addr = a.get("href", "")[7:].split("?")[0].strip()
            if addr and addr not in a.get_text():
                a.append(f" ({addr})")
        for br in soup.find_all(["br", "p", "li", "div", "h1", "h2", "h3", "h4", "tr"]):
            br.append("\n")
        raw = soup.get_text(" ")
    raw = html.unescape(raw)
    raw = re.sub(r"[ \t\xa0]+", " ", raw)
    raw = re.sub(r"\n\s*\n+", "\n\n", raw)
    return raw.strip()


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", "ignore")).hexdigest()


def strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))


# ---------------------------------------------------------------- normalization

_COMPANY_SUFFIX = re.compile(
    r"\b(inc|incorporated|llc|l\.l\.c|ltd|limited|pvt|private|corp|corporation|co|gmbh|plc|"
    r"technologies|technology|tech|labs|software|solutions|systems|services|group|holdings|"
    r"india|global|ai)\b\.?",
    re.I,
)


def normalize_company(name: str | None) -> str:
    if not name:
        return ""
    s = strip_accents(name).lower()
    s = re.sub(r"\(.*?\)", " ", s)
    s = s.replace("&", " and ")
    base = re.sub(r"[^a-z0-9 ]+", " ", s)
    stripped = _COMPANY_SUFFIX.sub(" ", base)
    stripped = re.sub(r"\s+", " ", stripped).strip()
    return stripped or re.sub(r"\s+", " ", base).strip()


_TITLE_NOISE = re.compile(
    r"\b(urgent|hiring|immediate joiner|immediate|wfh|work from home|remote|hybrid|onsite|"
    r"m/f/d|f/m/d|m/w/d|full[- ]time|part[- ]time|contract)\b",
    re.I,
)
_TITLE_ABBR = {
    r"\bsr\b\.?": "senior",
    r"\bjr\b\.?": "junior",
    r"\bengg?\b\.?": "engineer",
    r"\bdev\b": "developer",
    r"\bswe\b": "software engineer",
    r"\bml\b": "machine learning",
    r"\bai/ml\b": "ai ml",
    r"\bmgr\b": "manager",
}


def normalize_title(title: str | None) -> str:
    if not title:
        return ""
    s = strip_accents(title).lower()
    s = re.sub(r"\(.*?\)|\[.*?\]", " ", s)
    s = s.split(" - ")[0] if len(s.split(" - ")[0]) > 6 else s
    for pat, rep in _TITLE_ABBR.items():
        s = re.sub(pat, rep, s)
    s = _TITLE_NOISE.sub(" ", s)
    s = re.sub(r"[^a-z0-9+#. ]+", " ", s)
    return re.sub(r"\s+", " ", s).strip(" .")


def normalize_location(loc: str | None) -> str:
    if not loc:
        return ""
    s = strip_accents(loc).lower()
    s = s.replace("bengaluru", "bangalore").replace("gurugram", "gurgaon").replace("bombay", "mumbai")
    s = re.sub(r"[^a-z0-9, ]+", " ", s)
    return re.sub(r"\s+", " ", s).strip(" ,")


# ---------------------------------------------------------------- work mode / type

def detect_work_mode(*texts: str | None, remote_flag: bool | None = None) -> str:
    joined = " ".join(t for t in texts if t).lower()
    if "hybrid" in joined:
        return "hybrid"
    if remote_flag is True or re.search(r"\b(remote|work from home|wfh|anywhere|distributed team)\b", joined):
        return "remote"
    if re.search(r"\b(on-?site|in[- ]office|work from office|wfo)\b", joined):
        return "onsite"
    if remote_flag is False:
        return "onsite"
    return "unknown"


def detect_employment_type(*texts: str | None) -> str | None:
    j = " ".join(t for t in texts if t).lower()
    for pat, label in [
        (r"\bintern(ship)?\b", "Internship"),
        (r"\bpart[- ]time\b", "Part-time"),
        (r"\b(contract|contractor|freelance|c2h|contract to hire)\b", "Contract"),
        (r"\bfull[- ]?time|permanent\b", "Full-time"),
    ]:
        if re.search(pat, j):
            return label
    return None


# ---------------------------------------------------------------- experience requirement in JDs

@dataclass
class ExperienceReq:
    min_years: float | None
    max_years: float | None
    text: str | None


_NUM = r"(\d{1,2}(?:\.\d)?)"
_YRS = r"\s*(?:\+\s*)?(?:years?|yrs?)"


def parse_experience_requirement(*texts: str | None) -> ExperienceReq:
    """Extract an experience requirement like '3-5 years' or '5+ yrs' from title/JD."""
    joined = " ".join(t for t in texts if t)
    if not joined:
        return ExperienceReq(None, None, None)
    candidates: list[tuple[float, float | None, str]] = []
    for m in re.finditer(_NUM + r"\s*(?:-|–|—|to)\s*" + _NUM + _YRS, joined, re.I):
        lo, hi = float(m.group(1)), float(m.group(2))
        if lo <= hi <= 30:
            candidates.append((lo, hi, m.group(0)))
    for m in re.finditer(_NUM + r"\s*\+\s*(?:years?|yrs?)", joined, re.I):
        candidates.append((float(m.group(1)), None, m.group(0)))
    for m in re.finditer(r"(?:minimum|min\.?|at least|atleast)\s*(?:of\s*)?" + _NUM + _YRS, joined, re.I):
        candidates.append((float(m.group(1)), None, m.group(0)))
    for m in re.finditer(_NUM + _YRS + r"\s*(?:of\s+)?(?:\w+\s+){0,4}?(?:experience|exp\b)", joined, re.I):
        candidates.append((float(m.group(1)), None, m.group(0)))
    candidates = [c for c in candidates if c[0] <= 25]
    if candidates:
        # the first mention is usually the headline requirement
        lo, hi, txt = candidates[0]
        return ExperienceReq(lo, hi, txt.strip())
    low = joined.lower()
    if re.search(r"\b(fresher|freshers|entry[- ]level|new grad|graduate program|0 years)\b", low):
        return ExperienceReq(0, 1, "Entry level / Fresher")
    if re.search(r"\bintern(ship)?\b", normalize_title(texts[0] or "") if texts else ""):
        return ExperienceReq(0, 0, "Internship")
    title = (texts[0] or "").lower() if texts else ""
    if re.search(r"\b(principal|staff|director|head of|vp|architect)\b", title):
        return ExperienceReq(8, None, "Senior leadership title (inferred from title)")
    if re.search(r"\b(senior|sr\.?|lead)\b", title):
        return ExperienceReq(4, None, "Senior title (inferred from title)")
    if re.search(r"\b(junior|jr\.?|associate|graduate|trainee)\b", title):
        return ExperienceReq(0, 2, "Junior title (inferred from title)")
    return ExperienceReq(None, None, None)


# ---------------------------------------------------------------- resume date ranges

_MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], start=1)}
_MONTH_RE = r"(jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?"
_DATE_RE = rf"(?:{_MONTH_RE}\s*[,']?\s*(\d{{4}}|'\d{{2}})|(\d{{1,2}})\s*[/.-]\s*(\d{{4}})|(\d{{4}}))"
_PRESENT = r"(present|current|now|till date|to date|ongoing|today)"
RANGE_RE = re.compile(rf"{_DATE_RE}\s*(?:-|–|—|to|until)\s*(?:{_DATE_RE}|{_PRESENT})", re.I)


def _to_date(mon: str | None, yr: str | None, num_mon: str | None, num_yr: str | None, bare_yr: str | None,
             end: bool) -> date | None:
    try:
        if mon and yr:
            y = int(yr.replace("'", "20")) if yr.startswith("'") else int(yr)
            return date(y, _MONTHS[mon[:3].lower()], 1)
        if num_mon and num_yr:
            m = int(num_mon)
            if 1 <= m <= 12:
                return date(int(num_yr), m, 1)
        if bare_yr:
            return date(int(bare_yr), 12 if end else 1, 1)
    except (ValueError, KeyError):
        return None
    return None


@dataclass
class DateRange:
    start: date
    end: date
    raw: str
    is_present: bool

    @property
    def months(self) -> int:
        return max(0, (self.end.year - self.start.year) * 12 + self.end.month - self.start.month + 1)


def find_date_ranges(text: str, today: date | None = None) -> list[DateRange]:
    today = today or datetime.now(timezone.utc).date()
    out: list[DateRange] = []
    for m in RANGE_RE.finditer(text or ""):
        g = m.groups()
        start = _to_date(g[0], g[1], g[2], g[3], g[4], end=False)
        is_present = bool(g[10])
        end = date(today.year, today.month, 1) if is_present else _to_date(g[5], g[6], g[7], g[8], g[9], end=True)
        if start and end and start <= end and 1970 < start.year <= today.year + 1 and end <= date(today.year + 1, 12, 1):
            if end > date(today.year, today.month, 1):
                end = date(today.year, today.month, 1)
            out.append(DateRange(start, end, m.group(0), is_present))
    return out


def merge_months(ranges: list[DateRange]) -> int:
    """Total months covered by ranges, counting overlaps once."""
    if not ranges:
        return 0
    spans = sorted((r.start.year * 12 + r.start.month, r.end.year * 12 + r.end.month) for r in ranges)
    total, cur_s, cur_e = 0, spans[0][0], spans[0][1]
    for s, e in spans[1:]:
        if s <= cur_e + 1:
            cur_e = max(cur_e, e)
        else:
            total += cur_e - cur_s + 1
            cur_s, cur_e = s, e
    return total + cur_e - cur_s + 1


def parse_date_string(s: str | None) -> date | None:
    """Parse 'Jan 2022', '01/2022', '2022', 'Present' (-> today)."""
    if not s:
        return None
    s = s.strip()
    if re.fullmatch(_PRESENT, s, re.I):
        t = datetime.now(timezone.utc).date()
        return date(t.year, t.month, 1)
    m = re.fullmatch(_DATE_RE, s, re.I)
    if not m:
        m2 = re.match(r"(\d{4})-(\d{2})(?:-\d{2})?$", s)
        if m2:
            return date(int(m2.group(1)), int(m2.group(2)), 1)
        return None
    g = m.groups()
    return _to_date(g[0], g[1], g[2], g[3], g[4], end=False)


def experience_level(professional_months: int, internship_months: int) -> str:
    if professional_months >= 120:
        return "Principal / Staff"
    if professional_months >= 72:
        return "Senior"
    if professional_months >= 36:
        return "Mid-Level"
    if professional_months >= 12:
        return "Early Career"
    if professional_months > 0 or internship_months >= 6:
        return "Early Career"
    if internship_months > 0:
        return "Entry Level (with internships)"
    return "Entry Level"


# ---------------------------------------------------------------- education

EDU_LEVELS = [
    ("phd", 5, r"\b(ph\.?\s?d|doctorate|doctor of philosophy)\b"),
    ("masters", 4, r"\b(m\.?\s?tech|m\.?\s?e\.?\b|m\.?\s?sc|mca|mba|m\.?\s?s\.?\b|master'?s?|ms in|msc|pgdm|post ?graduate)\b"),
    ("bachelors", 3, r"\b(b\.?\s?tech|b\.?\s?e\.?\b|b\.?\s?sc|bca|bba|b\.?\s?com|bachelor'?s?|b\.?\s?s\.?\b|undergraduate|degree in computer|graduate degree)\b"),
    ("diploma", 2, r"\b(diploma|associate degree)\b"),
    ("high_school", 1, r"\b(high school|12th|hsc|higher secondary)\b"),
]


def education_rank(level: str | None) -> int:
    for name, rank, _ in EDU_LEVELS:
        if name == level:
            return rank
    return 0


def detect_education_level(text: str) -> str | None:
    for name, _, pat in EDU_LEVELS:
        if re.search(pat, text or "", re.I):
            return name
    return None


def required_education(text: str) -> str | None:
    """Education required by a JD (only when explicitly phrased as a requirement)."""
    t = (text or "").lower()
    m = re.search(r"(degree|bachelor|master|phd|ph\.d|b\.tech|b\.e\.|m\.tech|mca|bca|graduate)[^.\n]{0,80}", t)
    if not m:
        return None
    window = t[max(0, m.start() - 80): m.end()]
    for name, _, pat in EDU_LEVELS:
        if re.search(pat, window, re.I):
            return name
    if "degree" in window:
        return "bachelors"
    return None


# ---------------------------------------------------------------- salary

@dataclass
class Salary:
    min: float | None
    max: float | None
    currency: str | None
    period: str | None
    text: str | None


def format_salary(mn: float | None, mx: float | None, cur: str | None, period: str | None) -> str | None:
    if mn is None and mx is None:
        return None
    def f(v: float) -> str:
        if cur == "INR" and v >= 100000:
            return f"{v / 100000:.1f} LPA".replace(".0 ", " ")
        if v >= 1000:
            return f"{v / 1000:.0f}k"
        return f"{v:.0f}"
    sym = {"USD": "$", "EUR": "€", "GBP": "£", "INR": "₹"}.get(cur or "", (cur + " ") if cur else "")
    rng = f(mn) if mx is None or mn == mx else (f"{f(mn)} – {f(mx)}" if mn is not None else f(mx))
    per = f" / {period}" if period and period not in ("year",) and cur != "INR" else ""
    return f"{sym}{rng}{per}"


def parse_salary_text(text: str | None) -> Salary:
    """Only parse explicit salary statements (never infer)."""
    if not text:
        return Salary(None, None, None, None, None)
    t = text
    m = re.search(r"(\d+(?:\.\d+)?)\s*(?:-|–|to)\s*(\d+(?:\.\d+)?)\s*(lpa|lakhs? per annum|lakhs?)\b", t, re.I)
    if m:
        lo, hi = float(m.group(1)) * 1e5, float(m.group(2)) * 1e5
        return Salary(lo, hi, "INR", "year", m.group(0))
    m = re.search(r"([$€£₹])\s?(\d[\d,]*(?:\.\d+)?)\s*(k)?\s*(?:-|–|to)\s*[$€£₹]?\s?(\d[\d,]*(?:\.\d+)?)\s*(k)?", t, re.I)
    if m:
        cur = {"$": "USD", "€": "EUR", "£": "GBP", "₹": "INR"}[m.group(1)]
        lo = float(m.group(2).replace(",", "")) * (1000 if m.group(3) else 1)
        hi = float(m.group(4).replace(",", "")) * (1000 if m.group(5) or m.group(3) else 1)
        if lo > 0 and hi >= lo:
            period = "hour" if hi < 500 else "year"
            return Salary(lo, hi, cur, period, m.group(0))
    return Salary(None, None, None, None, None)


# ---------------------------------------------------------------- misc

def parse_datetime(value) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, (int, float)):
        v = float(value)
        if v > 1e12:
            v /= 1000
        try:
            return datetime.fromtimestamp(v, tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    s = str(value).strip()
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        pass
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%a, %d %b %Y %H:%M:%S %z", "%d %b %Y", "%B %d, %Y"):
        try:
            dt = datetime.strptime(s, fmt)
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def shingles(text: str, k: int = 5) -> set[str]:
    words = re.findall(r"[a-z0-9]+", (text or "").lower())
    if len(words) < k:
        return {" ".join(words)} if words else set()
    return {" ".join(words[i:i + k]) for i in range(0, len(words) - k + 1)}


def jaccard(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)
