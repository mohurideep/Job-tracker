from datetime import date, datetime, timedelta

DATE_FMT = "%Y-%m-%d"
STATUSES = ["Saved","Applied","OA","HR Screen","Interview","Onsite","Offer","Rejected","Ghosted","Withdrawn"]

def parse_date(s):
    s = (s or "").strip()
    if not s:
        return None
    try:
        return datetime.strptime(s, DATE_FMT).date()
    except ValueError:
        return None

def format_date(d):
    return d.strftime(DATE_FMT) if d else None

def validate_required(company: str, role: str):
    if not company.strip():
        return "Company is required."
    if not role.strip():
        return "Role is required."
    return None

def default_followup(applied: date, days: int):
    return applied + timedelta(days=int(days))

def compute_overdue(followup_date_str: str, status: str) -> bool:
    if status in ("Rejected", "Withdrawn"):
        return False
    fd = parse_date(followup_date_str)
    return bool(fd and fd < date.today())
