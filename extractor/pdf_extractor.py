import os
import re
import sqlite3
from pathlib import Path

import pytesseract
from PIL import Image
import pdfplumber
import pypdfium2 as pdfium


# ─────────────────────────────────────────
# CONFIGURATION
# ─────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, '..', 'database', 'dgcine.db')
RAW_DATA_DIR = os.path.join(BASE_DIR, '..', 'data', 'raw')
TESSERACT_LANG = 'spa'
EXTRACTION_DEBUG = os.getenv('EXTRACTION_DEBUG', '0') == '1'

MONTHS = {
    'enero': '01', 'febrero': '02', 'marzo': '03',
    'abril': '04', 'mayo': '05', 'junio': '06',
    'julio': '07', 'agosto': '08', 'septiembre': '09',
    'octubre': '10', 'noviembre': '11', 'diciembre': '12'
}

DAY_WORDS = {
    'uno': 1, 'un': 1, 'primero': 1,
    'dos': 2,
    'tres': 3,
    'cuatro': 4,
    'cinco': 5,
    'seis': 6,
    'siete': 7,
    'ocho': 8,
    'nueve': 9,
    'diez': 10,
    'once': 11,
    'doce': 12,
    'trece': 13,
    'catorce': 14,
    'quince': 15,
    'dieciseis': 16, 'dieciséis': 16,
    'diecisiete': 17,
    'dieciocho': 18,
    'diecinueve': 19,
    'veinte': 20,
    'veintiuno': 21, 'veintiun': 21, 'veintiún': 21,
    'veintidos': 22, 'veintidós': 22,
    'veintitres': 23, 'veintitrés': 23,
    'veinticuatro': 24,
    'veinticinco': 25,
    'veintiseis': 26, 'veintiséis': 26,
    'veintisiete': 27,
    'veintiocho': 28,
    'veintinueve': 29,
    'treinta': 30,
    'treinta y uno': 31, 'treinta y un': 31,
}


# ─────────────────────────────────────────
# PDF TEXT EXTRACTION
# ─────────────────────────────────────────
def extract_text_pdfplumber(pdf_path: str) -> str | None:
    """Try extracting text directly with pdfplumber."""
    try:
        with pdfplumber.open(pdf_path) as pdf:
            text = ''
            for page in pdf.pages:
                page_text = page.extract_text()
                if page_text:
                    text += page_text + '\n'
            return text.strip() if text.strip() else None
    except Exception:
        return None


def extract_text_ocr(pdf_path: str) -> str | None:
    """Extract text using OCR via pypdfium2 + pytesseract."""
    try:
        pdf = pdfium.PdfDocument(pdf_path)
        text = ''
        for page in pdf:
            bitmap = page.render(scale=3)
            image = bitmap.to_pil()
            page_text = pytesseract.image_to_string(image, lang=TESSERACT_LANG)
            text += page_text + '\n'
        return text.strip() if text.strip() else None
    except Exception as e:
        print(f"OCR error on {pdf_path}: {e}")
        return None


def extract_text(pdf_path: str) -> str | None:
    """Extract text — try pdfplumber first, fall back to OCR."""
    text = extract_text_pdfplumber(pdf_path)
    if text and len(text) > 100:
        return text
    return extract_text_ocr(pdf_path)


# ─────────────────────────────────────────
# FIELD PARSERS
# ─────────────────────────────────────────
def normalize(text: str) -> str:
    """Normalize text for consistent parsing."""
    normalized = (
        text
        .replace('\n', ' ')
        .replace('\r', ' ')
        .replace('“', '"')
        .replace('”', '"')
        .replace('‘', "'")
        .replace('’', "'")
    )
    # Common OCR artifact in legal phrases: "alos" instead of "a los".
    normalized = re.sub(r'\balos\b', 'a los', normalized, flags=re.IGNORECASE)
    normalized = re.sub(r'\s+', ' ', normalized)
    return normalized.strip()


def debug_log(message: str) -> None:
    """Print debug messages only when extraction debug mode is enabled."""
    if EXTRACTION_DEBUG:
        print(message)


def build_match_snippet(text: str, match: re.Match, radius: int = 90) -> str:
    """Return a compact snippet around the regex match for traceability."""
    start, end = match.span()
    snippet_start = max(0, start - radius)
    snippet_end = min(len(text), end + radius)
    return text[snippet_start:snippet_end].strip()


def parse_amount_value(raw_amount: str) -> float | None:
    """Normalize OCR-affected numeric strings and parse to float."""
    if not raw_amount:
        return None

    cleaned = raw_amount.strip().replace(' ', '')
    # Remove trailing punctuation often added by OCR, e.g. "65,614,583.00." or "79,738,187.."
    cleaned = re.sub(r'[^\d]+$', '', cleaned)

    if not re.search(r'\d', cleaned):
        return None

    if ',' in cleaned and '.' in cleaned:
        # Determine decimal separator by the rightmost symbol.
        if cleaned.rfind(',') > cleaned.rfind('.'):
            # Example: 79.738.189,20 -> 79738189.20
            cleaned = cleaned.replace('.', '').replace(',', '.')
        else:
            # Example: 79,738,189.20 -> 79738189.20
            cleaned = cleaned.replace(',', '')
    elif ',' in cleaned:
        # If comma behaves as decimal separator (1-2 digits on the right), convert it.
        if re.match(r'^\d+,\d{1,2}$', cleaned):
            cleaned = cleaned.replace(',', '.')
        else:
            cleaned = cleaned.replace(',', '')

    try:
        value = float(cleaned)
    except ValueError:
        return None

    if value > 500_000_000:
        value = value / 100

    return value


def parse_day_token(day_token: str | None, day_paren: str | None) -> str | None:
    """Resolve day from OCR token using either numeric token, parenthesized number, or word."""
    if day_paren and day_paren.isdigit():
        return day_paren.zfill(2)

    if not day_token:
        return None

    clean_token = day_token.strip().lower()
    if clean_token.isdigit():
        return clean_token.zfill(2)

    day_num = DAY_WORDS.get(clean_token)
    if day_num:
        return str(day_num).zfill(2)

    return None


def parse_resolution_number(text: str) -> str | None:
    match = re.search(
        r'CIPAC[-\s](\d{4})[-\s](\d{1,3})',
        text, re.IGNORECASE
    )
    if match:
        year = match.group(1)
        num = match.group(2).zfill(3)
        return f"CIPAC-{year}-{num}"
    return None


def parse_incentive_article(text: str) -> str | None:
    """Extract incentive article from Referente field or resolution title."""
    # Primary: explicit article mention
    match = re.search(r'[Aa]rt[íi]culo\s*(34|39)', text)
    if match:
        return f"art_{match.group(1)}"

    # Fallback: resolution title indicates type
    if re.search(r'VALIDACI[ÓO]N\s+DE\s+GASTOS', text, re.IGNORECASE):
        return 'art_39'

    if re.search(r'VALIDACI[ÓO]N\s+DE\s+INVERSI[ÓO]N', text, re.IGNORECASE):
        return 'art_34'

    return None


def parse_investor_name(text: str) -> str | None:
    """Extract investor name using OCR-safe stop markers."""
    match = re.search(
        r'[Ss]olicitante\s*[:\-]?\s*(.+?)'
        r'(?=\s+R[\.\s]?N[\.\s:]|\s+[Pp]roductor\s+[Cc]inematogr[áa]fico|'
        r'\s+[Oo]bra\s+cinematogr[áa]fica|\s+[Pp]ermiso\s+[ÚUu]nico|'
        r'\s+[Cc]ertificado\s+[Pp]rovisional|\s+PRIMERO:|\s+SEGUNDO:|$)',
        text,
        re.IGNORECASE,
    )
    if match:
        name = match.group(1).strip()
        name = re.split(r'\s+R[\.\s]?N[\.\s:]+', name)[0].strip()
        return name
    return None


def parse_rnc(text: str, label: str = 'R.N.C') -> str | None:
    """Extract RNC — tolerant of OCR variants like RN:ES, R.N.C:, R.N.C::, RNC."""
    pattern = rf'{re.escape(label)}\.?\s*[:\-]{{1,2}}\s*([\d\-]+)'
    match = re.search(pattern, text, re.IGNORECASE)
    if match:
        return match.group(1).strip()

    # For base R.N.C label only — try OCR variants
    if label == 'R.N.C':
        match = re.search(r'R[\.\s]?N[\.\s:]+[A-Z]{0,2}\s*([\d\-]+)', text)
        if match:
            return match.group(1).strip()

    return None


def parse_film_title(text: str) -> str | None:
    """Extract film title — handles special quote characters."""
    match = re.search(
        r'[Oo]bra\s+cinematogr[áa]fica\s*[:\-]?\s*'
        r'[\"\u201c\u201d\u2018\u2019]'
        r'([^\"\u201c\u201d\u2018\u2019\n]+)'
        r'[\"\u201c\u201d\u2018\u2019]',
        text
    )
    if match:
        return match.group(1).strip().upper()
    return None


def parse_production_company(text: str) -> str | None:
    """Extract production company using OCR-safe stop markers."""
    match = re.search(
        r'[Pp]roductor\s+[Cc]inematogr[áa]fico\s*[:\-]?\s*(.+?)'
        r'(?=\s+R[\.\s]?N[\.\s:]|\s+[Pp]ermiso\s+[ÚUu]nico|'
        r'\s+[Cc]ertificado\s+[Pp]rovisional|\s+[Oo]bra\s+cinematogr[áa]fica|'
        r'\s+[Ss]olicitante\s*[:\-]?|\s+PRIMERO:|\s+SEGUNDO:|$)',
        text,
        re.IGNORECASE,
    )
    if match:
        company = match.group(1).strip()
        company = re.split(r'\s+R\.N\.C', company)[0].strip()
        return company
    return None


def parse_pur_number(text: str) -> str | None:
    match = re.search(
        r'[Pp]ermiso\s+[ÚUuÜü]{1,2}[Nn]ico\s+de\s+[Rr]odaje\s*[:\-]?\s*(\d+)',
        text
    )
    if match:
        return match.group(1).strip()
    return None


def parse_cpnd_number(text: str) -> str | None:
    """Extract CPND number — searches by acronym or full phrase."""
    # Try acronym first: CPND No. 534
    match = re.search(r'CPND\s*[Nn]o\.?\s*(\d+)', text)
    if match:
        return match.group(1).strip()

    # Fallback: full phrase
    match = re.search(
        r'[Cc]ertificado\s+[Pp]rovisional\s+de\s+[Nn]acionalidad\s+[Dd]ominicana'
        r'.{0,50}[Nn]o\.?\s*(\d+)',
        text, re.DOTALL
    )
    if match:
        return match.group(1).strip()

    return None


def parse_request_date(text: str) -> str | None:
    """Parse request date — handles Art. 34 and Art. 39 formats."""
    # Art. 34: "Solicitud de fecha 26 de noviembre del 2025"
    match = re.search(
        r'[Ss]olicitud\s+de\s+fecha\s+(\d{1,2})\s+de\s+'
        r'(enero|febrero|marzo|abril|mayo|junio|julio|agosto|'
        r'septiembre|octubre|noviembre|diciembre)\s+del?\s+(\d{4})',
        text, re.IGNORECASE
    )
    if match:
        day = match.group(1).zfill(2)
        month = MONTHS.get(match.group(2).lower(), '00')
        year = match.group(3)
        return f"{year}-{month}-{day}"

    # Art. 39: "Fecha de solicitud: 21 de mayo del 2026"
    match = re.search(
        r'[Ff]echa\s+de\s+solicitud\s*:\s*(\d{1,2})\s+de\s+'
        r'(enero|febrero|marzo|abril|mayo|junio|julio|agosto|'
        r'septiembre|octubre|noviembre|diciembre)\s+del?\s+(\d{4})',
        text, re.IGNORECASE
    )
    if match:
        day = match.group(1).zfill(2)
        month = MONTHS.get(match.group(2).lower(), '00')
        year = match.group(3)
        return f"{year}-{month}-{day}"

    return None


def parse_resolution_date(text: str, debug: bool = False) -> str | None:
    """Parse resolution date — searches opening paragraph first."""
    def extract_date(text_chunk: str) -> str | None:
        # Handles: "el/a los quince (15) día/días del mes de enero ... (2026)"
        # Handles: "a los 15 (quince) días del mes de enero ... (2026)"
        match = re.search(
            r'(?:el|a\s+los?)\s+(\w+)\s*\((\d{1,2})\)\s+d[íi]as?\s+del\s+m\w{1,3}\s+de\s+'
            r'(enero|febrero|marzo|abril|mayo|junio|julio|agosto|'
            r'septiembre|octubre|noviembre|diciembre)'
            r'.{0,80}\((\d{4})\)',
            text_chunk, re.IGNORECASE | re.DOTALL
        )
        if match:
            day = match.group(2).zfill(2)
            month = MONTHS.get(match.group(3).lower(), '00')
            year = match.group(4)
            if debug:
                debug_log("[DEBUG][resolution_date] Pattern 1 matched successfully.")
                debug_log(f"[DEBUG][resolution_date] parsed='{year}-{month}-{day}'")
                debug_log(f"[DEBUG][resolution_date] snippet='{build_match_snippet(text_chunk, match)}'")
            return f"{year}-{month}-{day}"

        # Handles: "a los 15 (quince) días"
        match = re.search(
            r'(?:el|a\s+los?)\s+(\d{1,2})\s*\(\w+\)\s+d[íi]as?\s+del\s+m\w{1,3}\s+de\s+'
            r'(enero|febrero|marzo|abril|mayo|junio|julio|agosto|'
            r'septiembre|octubre|noviembre|diciembre)'
            r'.{0,80}\((\d{4})\)',
            text_chunk, re.IGNORECASE | re.DOTALL
        )
        if match:
            day = match.group(1).zfill(2)
            month = MONTHS.get(match.group(2).lower(), '00')
            year = match.group(3)
            if debug:
                debug_log("[DEBUG][resolution_date] Pattern 2 matched successfully.")
                debug_log(f"[DEBUG][resolution_date] parsed='{year}-{month}-{day}'")
                debug_log(f"[DEBUG][resolution_date] snippet='{build_match_snippet(text_chunk, match)}'")
            return f"{year}-{month}-{day}"

        return None

    # Primary — opening paragraph (first 1000 chars)
    result = extract_date(text[:1000])
    if result:
        return result

    # Fallback — full document
    result = extract_date(text)
    if debug and not result:
        debug_log('[DEBUG][resolution_date] No regex match found.')
    return result


def parse_amount_dop(text: str, keyword: str) -> float | None:
    """Parse DOP amount — handles OCR variants RD$, RDS$, RDS, RD$S."""
    pattern = rf'{re.escape(keyword)}.{{0,400}}R\s*D\s*[S$\.]{{0,2}}\s*([\d,\.]+)'
    match = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
    if match:
        val = parse_amount_value(match.group(1))
        return val
    return None


def parse_total_budget_approved(text: str, debug: bool = False) -> float | None:
    """Parse approved budget from CPND approval paragraph."""
    patterns = [
        r'aprob[óo0]\s+un\s+presupuesto\s+total.{0,220}?R\s*D\s*[S$\.]{0,2}\s*([\d,\.]+)',
        r'presupuesto\s+a\s+aplicar\s+al\s+incentivo.{0,260}?R\s*D\s*[S$\.]{0,2}\s*([\d,\.]+)',
        r'aprob[óo0].{0,120}?presupuesto.{0,260}?R\s*D\s*[S$\.]{0,2}\s*([\d,\.]+)',
        r'aprob[óo0].{0,100}?presu\w*.{0,260}?R\s*D\s*[S$\.]{0,2}\s*([\d,\.]+)',
        r'presupuesto\s+total.{0,220}?R\s*D\s*[S$\.]{0,2}\s*([\d,\.]+)',
        r'aprob[óo0].{0,100}?pre.{0,30}?total.{0,200}?R\s*D\s*[S$\.]{0,2}\s*([\d,\.]+)',
        r'presupuesto\s+aprobado\s+ascendente.{0,100}?R\s*D\s*[S$\.]{0,2}\s*([\d,\.]+)',
    ]

    for idx, pattern in enumerate(patterns, start=1):
        match = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
        if not match:
            continue
        val = parse_amount_value(match.group(1))
        if val is None:
            if debug:
                debug_log(f"[DEBUG][total_budget_approved] Pattern {idx} matched but amount parse failed: '{match.group(1)}'")
            continue
        if debug:
            debug_log(f'[DEBUG][total_budget_approved] Pattern {idx} matched successfully.')
            debug_log(f"[DEBUG][total_budget_approved] parsed='{val}'")
            debug_log(f"[DEBUG][total_budget_approved] snippet='{build_match_snippet(text, match)}'")
        return val

    if debug:
        debug_log('[DEBUG][total_budget_approved] No regex match found.')

    return None


def parse_total_budget_executed(text: str, debug: bool = False) -> float | None:
    """Parse total executed budget."""
    patterns = [
        r'ejecuci[oó]n\s+total\s+del\s+presupuesto.{0,260}?R\s*D\s*[S$\.]{0,2}\s*([\d,\.]+)',
        r'asciende\s+a\s+la\s+suma\s+de\s+R\s*D\s*[S$\.]{0,2}\s*([\d,\.]+)',
        r'inversi[oó]n\s+realizada.{0,260}?R\s*D\s*[S$\.]{0,2}\s*([\d,\.]+)',
        r'gastos\s+ejecutados.{0,200}?R\s*D\s*[S$\.]{0,2}\s*([\d,\.]+)',
    ]

    for idx, pattern in enumerate(patterns, start=1):
        match = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
        if not match:
            continue
        val = parse_amount_value(match.group(1))
        if val is None:
            if debug:
                debug_log(f"[DEBUG][total_budget_executed] Pattern {idx} matched but amount parse failed: '{match.group(1)}'")
            continue
        if debug:
            debug_log(f'[DEBUG][total_budget_executed] Pattern {idx} matched successfully.')
            debug_log(f"[DEBUG][total_budget_executed] parsed='{val}'")
            debug_log(f"[DEBUG][total_budget_executed] snippet='{build_match_snippet(text, match)}'")
        return val

    if debug:
        debug_log('[DEBUG][total_budget_executed] No regex match found.')

    return None


def build_extraction_quality(
    resolution_number: str | None,
    year: str | None,
    incentive_article: str | None,
    investor_name: str | None,
    investor_rnc: str | None,
    resolution_date: str | None,
    request_date: str | None,
    film_title: str | None,
    production_company: str | None,
    producer_rnc: str | None,
    pur_number: str | None,
    cpnd_number: str | None,
    validated_amount_dop: float | None,
    tax_credit_dop: float | None,
    total_budget_approved: float | None,
) -> tuple[float, bool, list[str]]:
    """Compute a lightweight confidence score and review reasons."""
    score = 1.0
    reasons: list[str] = []

    if not resolution_number:
        score -= 0.10
        reasons.append('missing_resolution_number')

    if not year:
        score -= 0.05
        reasons.append('missing_year')

    if not incentive_article:
        score -= 0.10
        reasons.append('missing_incentive_article')

    if not resolution_date:
        score -= 0.10
        reasons.append('missing_resolution_date')

    if not request_date:
        score -= 0.10
        reasons.append('missing_request_date')

    if not film_title:
        score -= 0.10
        reasons.append('missing_film_title')

    if not production_company:
        score -= 0.10
        reasons.append('missing_production_company')

    if not producer_rnc:
        score -= 0.10
        reasons.append('missing_producer_rnc')

    if not pur_number:
        score -= 0.10
        reasons.append('missing_pur_number')

    if incentive_article == 'art_34' and not cpnd_number:
        score -= 0.10
        reasons.append('missing_cpnd_number')

    if incentive_article == 'art_34' and not investor_name:
        score -= 0.10
        reasons.append('missing_investor_name')

    if incentive_article == 'art_34' and not investor_rnc:
        score -= 0.10
        reasons.append('missing_investor_rnc')

    if validated_amount_dop is None:
        score -= 0.10
        reasons.append('missing_validated_amount_dop')

    if tax_credit_dop is None:
        score -= 0.10
        reasons.append('missing_tax_credit_dop')

    if total_budget_approved is None:
        score -= 0.10
        reasons.append('missing_total_budget_approved')

    score = max(0.0, round(score, 2))
    needs_review = len(reasons) > 0
    return score, needs_review, reasons


# ─────────────────────────────────────────
# MAIN EXTRACTOR
# ─────────────────────────────────────────
def extract_cipac_fields(text: str, source_file: str) -> dict:
    """Extract all structured fields from CIPAC resolution text."""
    text_norm = normalize(text)

    resolution_number = parse_resolution_number(text_norm)
    year = resolution_number.split('-')[1] if resolution_number else None
    incentive_article = parse_incentive_article(text_norm)
    film_title = parse_film_title(text_norm)
    pur_number = parse_pur_number(text_norm)
    cpnd_number = parse_cpnd_number(text_norm)
    request_date = parse_request_date(text_norm)

    investor = parse_investor_name(text_norm)
    production_company = parse_production_company(text_norm)
    producer_rnc = parse_rnc(text_norm, 'R.N.C. Productor')

    if incentive_article == 'art_39':
        if not production_company:
            production_company = investor
            producer_rnc = parse_rnc(text_norm, 'R.N.C')
        investor = None
        investor_rnc = None
    else:
        investor_rnc = parse_rnc(text_norm, 'R.N.C')

    resolution_date = parse_resolution_date(text_norm)
    total_budget_approved = parse_total_budget_approved(text_norm)
    total_budget_executed = parse_total_budget_executed(text_norm)

    validated_amount_dop = parse_amount_dop(text_norm, 'PRIMERO: VALIDAR')
    tax_credit_dop = parse_amount_dop(text_norm, 'SEGUNDO: AUTORIZAR')

    # Art. 34 fallback: tax_credit = validated_amount (they are always equal)
    if tax_credit_dop is None and incentive_article == 'art_34' and validated_amount_dop:
        tax_credit_dop = validated_amount_dop

    confidence, needs_review, review_reasons = build_extraction_quality(
        resolution_number=resolution_number,
        year=year,
        incentive_article=incentive_article,
        investor_name=investor,
        investor_rnc=investor_rnc,
        resolution_date=resolution_date,
        request_date=request_date,
        film_title=film_title,
        production_company=production_company,
        producer_rnc=producer_rnc,
        pur_number=pur_number,
        cpnd_number=cpnd_number,
        validated_amount_dop=validated_amount_dop,
        tax_credit_dop=tax_credit_dop,
        total_budget_approved=total_budget_approved,
    )

    return {
        'resolution_number':      resolution_number,
        'year':                   year,
        'incentive_article':      incentive_article,
        'investor_name':          investor,
        'investor_rnc':           investor_rnc,
        'film_title':             film_title,
        'production_company':     production_company,
        'producer_rnc':           producer_rnc,
        'pur_number':             pur_number,
        'cpnd_number':            cpnd_number,
        'resolution_date':        resolution_date,
        'request_date':           request_date,
        'validated_amount_dop':   validated_amount_dop,
        'tax_credit_dop':         tax_credit_dop,
        'total_budget_approved':  total_budget_approved,
        'total_budget_executed':  total_budget_executed,
        'extraction_confidence':  confidence,
        'needs_review':           needs_review,
        'review_reasons':         ';'.join(review_reasons) if review_reasons else None,
        'manually_reviewed':      False,
        'manual_note':            None,
        'source_file':            os.path.basename(source_file),
    }


def process_pdf(pdf_path: str) -> dict | None:
    """Process a single CIPAC PDF and return extracted fields."""
    print(f"Processing: {os.path.basename(pdf_path)}")

    text = extract_text(pdf_path)
    if not text:
        print(f"  Could not extract text from {pdf_path}")
        return None

    fields = extract_cipac_fields(text, pdf_path)
    return fields


def process_all_pdfs(year_filter: list[str] | None = None) -> list[dict]:
    """Process all CIPAC PDFs in the raw data directory."""
    results = []
    cipac_dir = os.path.join(RAW_DATA_DIR, 'cipac')

    if not os.path.exists(cipac_dir):
        print(f"Directory not found: {cipac_dir}")
        return results

    for year_dir in sorted(Path(cipac_dir).iterdir()):
        if not year_dir.is_dir():
            continue

        year = year_dir.name
        if year_filter and year not in year_filter:
            continue

        pdfs = list(year_dir.glob('*.pdf'))
        print(f"\nYear {year}: {len(pdfs)} PDFs")

        for pdf_path in sorted(pdfs):
            fields = process_pdf(str(pdf_path))
            if fields:
                results.append(fields)

    return results


def print_review_summary(results: list[dict]) -> None:
    """Print extraction quality summary for quick auditing."""
    total = len(results)
    review_items = [r for r in results if r.get('needs_review')]

    print(f"\nExtraction quality summary:")
    print(f"  Total processed: {total}")
    print(f"  Needs review:    {len(review_items)}")

    if not review_items:
        print("  Review list:     none")
        return

    print("  Review list:")
    for item in review_items:
        source = item.get('source_file', 'unknown_file')
        reasons = item.get('review_reasons') or 'unspecified_reason'
        confidence = item.get('extraction_confidence')
        print(f"    - {source} | confidence={confidence} | reasons={reasons}")


# ─────────────────────────────────────────
# DATABASE INSERTION
# ─────────────────────────────────────────
def insert_cipac_resolution(conn: sqlite3.Connection, fields: dict) -> bool:
    """Insert extracted fields into cipac_resolutions table."""
    try:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT OR IGNORE INTO cipac_resolutions (
                resolution_number,
                movie_id,
                pur_number,
                cpnd_number,
                incentive_article,
                investor_name,
                investor_rnc,
                local_company,
                producer_rnc,
                foreign_producer,
                film_title,
                request_date,
                resolution_date,
                validated_expenses_dop,
                tax_credit_dop,
                total_budget_approved,
                total_budget_executed,
                extraction_confidence,
                needs_review,
                review_reasons,
                manually_reviewed,
                manual_note,
                source_file
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            fields.get('resolution_number'),
            None,
            fields.get('pur_number'),
            fields.get('cpnd_number'),
            fields.get('incentive_article'),
            fields.get('investor_name'),
            fields.get('investor_rnc'),
            fields.get('production_company'),
            fields.get('producer_rnc'),
            None,
            fields.get('film_title'),
            fields.get('request_date'),
            fields.get('resolution_date'),
            fields.get('validated_amount_dop'),
            fields.get('tax_credit_dop'),
            fields.get('total_budget_approved'),
            fields.get('total_budget_executed'),
            fields.get('extraction_confidence'),
            1 if fields.get('needs_review') else 0,
            fields.get('review_reasons'),
            1 if fields.get('manually_reviewed') else 0,
            fields.get('manual_note'),
            fields.get('source_file'),
        ))
        conn.commit()
        return True
    except Exception as e:
        print(f"DB insert error: {e}")
        return False


# ─────────────────────────────────────────
# ENTRY POINT
# ─────────────────────────────────────────
if __name__ == "__main__":
    results = process_all_pdfs()
    print_review_summary(results)

    print(f"\nTotal PDFs processed: {len(results)}")
    print("\nSample extracted fields:")
    for r in results[:2]:
        print()
        for k, v in r.items():
            print(f"  {k:<25} {v}")