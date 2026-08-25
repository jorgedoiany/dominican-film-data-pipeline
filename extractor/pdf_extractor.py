import os
import re
import sqlite3
import json
from pathlib import Path

import pytesseract
from PIL import Image
import pdfplumber
import pypdfium2 as pdfium

from dotenv import load_dotenv
load_dotenv()


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


def extract_text_azure(pdf_path: str) -> str | None:
    """Extract text using Azure OpenAI GPT-4o-mini Vision as fallback."""
    import base64
    from openai import AzureOpenAI

    api_key = os.getenv('AZURE_OPENAI_KEY')
    endpoint = os.getenv('AZURE_OPENAI_ENDPOINT')
    deployment = os.getenv('AZURE_OPENAI_DEPLOYMENT', 'gpt-4o-mini')

    if not api_key or not endpoint:
        return None

    try:
        client = AzureOpenAI(
            api_key=api_key,
            azure_endpoint=endpoint,
            api_version='2024-02-01'
        )

        pdf = pdfium.PdfDocument(pdf_path)
        all_text = []

        for page in pdf:
            bitmap = page.render(scale=2)
            image = bitmap.to_pil()

            # Convert image to base64
            import io
            buffer = io.BytesIO()
            image.save(buffer, format='PNG')
            image_b64 = base64.b64encode(buffer.getvalue()).decode('utf-8')

            response = client.chat.completions.create(
                model=deployment,
                messages=[
                    {
                        'role': 'user',
                        'content': [
                            {
                                'type': 'text',
                                'text': 'Extrae todo el texto de esta imagen de un documento legal dominicano. Devuelve solo el texto, sin comentarios adicionales.'
                            },
                            {
                                'type': 'image_url',
                                'image_url': {
                                    'url': f'data:image/png;base64,{image_b64}'
                                }
                            }
                        ]
                    }
                ],
                max_tokens=2000
            )
            all_text.append(response.choices[0].message.content)

        return '\n'.join(all_text)

    except Exception as e:
        print(f"Azure OCR error on {pdf_path}: {e}")
        return None


def extract_text(pdf_path: str, force_azure: bool = False) -> str | None:
    """Extract text — try pdfplumber first, fall back to OCR, then Azure."""
    if not force_azure:
        text = extract_text_pdfplumber(pdf_path)
        if text and len(text) > 100 and 'CIPAC' in text:
            return text

        text = extract_text_ocr(pdf_path)
        if text and len(text) > 100 and 'CIPAC' in text:
            return text

    return extract_text_azure(pdf_path)


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
    # Remove trailing punctuation often added by OCR
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
            # Also handles OCR dots as thousand separators: 2,000.000.00
            dot_count = cleaned.count('.')
            if dot_count > 1:
                # Multiple dots = thousand separators: 2,000.000.00 -> 2000000.00
                parts = cleaned.rsplit('.', 1)
                cleaned = parts[0].replace(',', '').replace('.', '') + '.' + parts[1]
            else:
                cleaned = cleaned.replace(',', '')
    elif ',' in cleaned:
        if re.match(r'^\d+,\d{1,2}$', cleaned):
            cleaned = cleaned.replace(',', '.')
        else:
            cleaned = cleaned.replace(',', '')
    elif '.' in cleaned:
        # Only dots: could be thousand separators
        # Example: 500.000.00 -> 500000.00
        dot_count = cleaned.count('.')
        if dot_count > 1:
            parts = cleaned.rsplit('.', 1)
            cleaned = parts[0].replace('.', '') + '.' + parts[1]

    try:
        value = float(cleaned)
    except ValueError:
        return None

    # Only divide by 100 if value seems unreasonably large (> 10 billion)
    # This handles OCR errors where decimal point is missing
    if value > 10_000_000_000:
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
    def extract_from_inversion_phrase(source_text: str) -> str | None:
        """Fallback for templates that embed investor name in a legal sentence."""
        match = re.search(
            r'en\s+este\s+sentido,\s+la\s+inversi[oó]n\s+realizada\s+por\s+'
            r'(?:la\s+sociedad\s+)?(.+?)'
            r'(?=,\s*(?:se\s+encuentra|no\s+se\s+encuentra))',
            source_text,
            re.IGNORECASE,
        )
        if not match:
            match = re.search(
                r'inversi[oó]n\s+realizada\s+por\s+(?:la\s+sociedad\s+)?(.+?)'
                r'(?=,\s*(?:se\s+encuentra|no\s+se\s+encuentra))',
                source_text,
                re.IGNORECASE,
            )
        if match:
            return match.group(1).strip()
        return None

    def extract_from_primero(source_text: str) -> str | None:
        """Fallback: extract investor name from PRIMERO: VALIDAR paragraph."""
        match = re.search(
            r'PRIMERO\s*:?\s*VALIDAR\s+la\s+inversi[oó]n\s+realizada\s+y\s+ejecutada\s+por\s+la\s+sociedad\s+(.+?)'
            r'(?=,|\s+en\s+la\s+producci[oó]n)',
            source_text,
            re.IGNORECASE,
        )
        if match:
            return match.group(1).strip().upper()
        return None

    def extract_from_detalle(source_text: str) -> str | None:
        """Fallback: extract investor name from 'Detalle de inversión de' phrase."""
        match = re.search(
            r'[Dd]etalle\s+de\s+inversi[oó]n\s+de\s+(.+?)\s+y\s+copia',
            source_text,
            re.IGNORECASE,
        )
        if match:
            name = match.group(1).strip().upper()
            # Remove trailing list numbers like "9."
            name = re.sub(r'\s+\d+\.$', '', name).strip()
            return name
        return None

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
        name = re.split(r'\s+R[\.\s]?N[\.\s:C]+', name, flags=re.IGNORECASE)[0].strip()

        if re.search(r'^para\s+la\s+aplicaci[oó]n\s+del\s+incentivo', name, re.IGNORECASE):
            fallback_name = extract_from_inversion_phrase(text)
            if fallback_name:
                return fallback_name

        return name

    fallback_name = extract_from_inversion_phrase(text)
    if fallback_name:
        return fallback_name

    fallback_name = extract_from_primero(text)
    if fallback_name:
        return fallback_name

    fallback_name = extract_from_detalle(text)
    if fallback_name:
        return fallback_name

    return None


def validate_rnc(rnc: str) -> bool:
    """Validate Dominican RNC format: X-XX-XXXXX-X (9 digits total, correct hyphen pattern)."""
    digits = re.sub(r'[^\d]', '', rnc)
    if len(digits) != 9:
        return False
    # Also validate hyphen pattern: X-XX-XXXXX-X
    if not re.match(r'^\d{1}-\d{2}-\d{5}-\d{1}$', rnc):
        return False
    return True


def parse_rnc(text: str, label: str = 'R.N.C', exclude_rnc: str | None = None) -> str | None:
    """Extract RNC — tolerant of OCR variants like RN:ES, R.N.C:, R.N.C::, RNC.

    Args:
        text: Normalized document text.
        label: RNC label to search for.
        exclude_rnc: RNC value to exclude (e.g. investor RNC when parsing producer RNC).
    """
    from collections import Counter

    def is_valid(rnc: str) -> bool:
        if not validate_rnc(rnc):
            return False
        if exclude_rnc and rnc == exclude_rnc:
            return False
        return True

    pattern = rf'{re.escape(label)}\.?\s*[:\-]{{1,2}}\s*([\d\-]+)'
    match = re.search(pattern, text, re.IGNORECASE)
    if match:
        rnc = match.group(1).strip()
        if is_valid(rnc):
            return rnc

    # For base R.N.C label only — try OCR variants
    if label == 'R.N.C':
        match = re.search(r'R[\.\s]?N[\.\s:]+[A-Z]{0,2}\s*([\d\-]+)', text)
        if match:
            rnc = match.group(1).strip()
            if is_valid(rnc):
                return rnc

        # Plain RNC: format
        match = re.search(r'\bRNC\s*[:\-]\s*([\d\-]+)', text, re.IGNORECASE)
        if match:
            rnc = match.group(1).strip()
            if is_valid(rnc):
                return rnc

    # For R.N.C. Productor — fallback to most frequent valid RNC in document
    # Producer RNC appears twice (header + Considerando), investor RNC appears once
    if label == 'R.N.C. Productor':
        matches = re.findall(r'\b(\d{1}-\d{2}-\d{5}-\d{1})\b', text)
        valid_matches = [m for m in matches if is_valid(m)]
        if valid_matches:
            counter = Counter(valid_matches)
            return counter.most_common(1)[0][0]

    return None


def parse_film_title(text: str) -> str | None:
    """Extract film title — handles cinematografica and audiovisual labels."""
    match = re.search(
        r'[Oo]bra\s+(?:cinematogr[áa]fica|audiovisual)\s*[:\-]?\s*'
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
        r'[Pp]roductor[a]?\s+[Cc]inematogr[áa]fico[a]?\s*[:\-]?\s*(.+?)'
        r'(?=\s+R[\.\s]?N[\.\s:C]+|\s+[Pp]ermiso\s+[ÚUu]nico|'
        r'\s+[Cc]ertificado\s+[Pp]rovisional|\s+[Oo]bra\s+cinematogr[áa]fica|'
        r'\s+[Ss]olicitante\s*[:\-]?|\s+PRIMERO:|\s+SEGUNDO:|$)',
        text,
        re.IGNORECASE,
    )
    if not match:
        # Fallback: "Productor: NOMBRE Permiso" — limit to short capture
        match = re.search(
            r'[Pp]roductor[a]?\s*:\s*(.{3,80}?)'
            r'(?=\s+[Pp]ermiso\s+[ÚUu]nico|\s+R[\.\s]?N[\.\s:C]+|\s+[Ff]echa)',
            text,
            re.IGNORECASE,
        )
    if match:
        company = match.group(1).strip()
        company = re.split(r'\s+R[\.\s]?N[\.\s:C]+', company, flags=re.IGNORECASE)[0].strip()
        # Reject if result looks like an RNC
        if re.match(r'^\d[\d\-]+$', company):
            return None
        return company
    return None


def parse_pur_number(text: str) -> str | None:
    # Standard format: "Permiso Único de Rodaje: 045"
    match = re.search(
        r'[Pp][eé]rmiso\s+[ÚUu]{1,2}[Nn]ico\s+de\s+[Rr]odaje\s*[:\-]?\s*(\d+)',
        text
    )
    if match:
        return match.group(1).strip()

    # Fallback: search by PUR acronym followed by number
    matches = re.findall(r'\bPUR\s+(\d+)', text)
    if matches:
        from collections import Counter
        counter = Counter(matches)
        return counter.most_common(1)[0][0]

    return None


def parse_cpnd_number(text: str) -> str | None:
    """Extract CPND number — handles multiple formats."""
    # Format: CPND No. 534 or No. CPND 522
    match = re.search(r'CPND\s*[Nn]o\.?\s*(\d+)', text)
    if match:
        return match.group(1).strip()

    # Format: CPND 522 or CPND-522
    match = re.search(r'CPND[\s\-]+(\d+)', text)
    if match:
        return match.group(1).strip()

    # Format: No. CPND 522
    match = re.search(r'[Nn]o\.?\s+CPND\s+(\d+)', text)
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
    """Parse request date — handles Art. 34, Art. 39 and Considerando formats."""
    # Art. 34 primary: "Solicitud de fecha 07 de noviembre del 2017"
    match = re.search(
        r'[Ss]olicitud\s+de\s+fecha\s+([O0-9]{1,2})\s+de\s+'
        r'(enero|febrero|marzo|abril|mayo|junio|julio|agosto|'
        r'septiembre|octubre|noviembre|diciembre)\s+(?:del?\s+)?(\d{4})',
        text, re.IGNORECASE
    )
    if match:
        day = match.group(1).replace('O', '0').zfill(2)
        month = MONTHS.get(match.group(2).lower(), '00')
        year = match.group(3)
        return f"{year}-{month}-{day}"

    # Art. 34 variant: "Solicitud de fecha veintitrés (23) de diciembre del dos mil diecisiete (2017)"
    match = re.search(
        r'[Ss]olicitud\s+de\s+fecha\s+\w+\s*\(([O0-9]{1,2})\)\s+de\s+'
        r'(enero|febrero|marzo|abril|mayo|junio|julio|agosto|'
        r'septiembre|octubre|noviembre|diciembre)\s+del?\s+.{0,40}\((\d{4})\)',
        text, re.IGNORECASE
    )
    if match:
        day = match.group(1).replace('O', '0').zfill(2)
        month = MONTHS.get(match.group(2).lower(), '00')
        year = match.group(3)
        return f"{year}-{month}-{day}"

    # Art. 34 variant: "Solicitud de fecha veintitrés (23) de diciembre 2019"
    match = re.search(
        r'[Ss]olicitud\s+de\s+fecha\s+\w+\s*\(([O0-9]{1,2})\)\s+de\s+'
        r'(enero|febrero|marzo|abril|mayo|junio|julio|agosto|'
        r'septiembre|octubre|noviembre|diciembre)\s+(?:del?\s+)?(\d{4})',
        text, re.IGNORECASE
    )
    if match:
        day = match.group(1).replace('O', '0').zfill(2)
        month = MONTHS.get(match.group(2).lower(), '00')
        year = match.group(3)
        return f"{year}-{month}-{day}"

    # Art. 39: "Fecha de solicitud: 21 de mayo del 2026"
    match = re.search(
        r'[Ff]echa\s+de\s+solicitud\s*:\s*([O0-9]{1,2})\s+de\s+'
        r'(enero|febrero|marzo|abril|mayo|junio|julio|agosto|'
        r'septiembre|octubre|noviembre|diciembre)\s+del?\s+(\d{4})',
        text, re.IGNORECASE
    )
    if match:
        day = match.group(1).replace('O', '0').zfill(2)
        month = MONTHS.get(match.group(2).lower(), '00')
        year = match.group(3)
        return f"{year}-{month}-{day}"

    # Fallback: search in Considerando paragraph
    match = re.search(
        r'[Cc]onsiderando.{0,50}?en\s+fecha\s+(\w+)\s*\(([O0-9]{1,2})\)\s+del\s+m\w{1,3}\s+de\s+'
        r'(enero|febrero|marzo|abril|mayo|junio|julio|agosto|'
        r'septiembre|octubre|noviembre|diciembre)\s+del\s+a[ñn]o.{0,30}\((\d{4})\).{0,300}'
        r'solicitud',
        text, re.IGNORECASE | re.DOTALL
    )
    if match:
        day = match.group(2).replace('O', '0').zfill(2)
        month = MONTHS.get(match.group(3).lower(), '00')
        year = match.group(4)
        return f"{year}-{month}-{day}"

    return None


def parse_resolution_type(text: str) -> str:
    """Determine if resolution approves or rejects the investment."""
    if re.search(r'PRIMERO\s*:\s*[Ee]ste\s+Consejo\s+rechaza', text):
        return 'rejected'
    if re.search(r'PRIMERO\s*:\s*RECHAZAR', text, re.IGNORECASE):
        return 'rejected'
    return 'approved'


def parse_resolution_date(text: str, debug: bool = False) -> str | None:
    """Parse resolution date — searches opening paragraph first."""
    def extract_date(text_chunk: str) -> str | None:
        # Handles: "el/a los/al quince (15) día/días del mes de enero ... (2026)"
        # Handles: "a los 15 (quince) días del mes de enero ... (2026)"
        match = re.search(
            r'(?:el|a\s+lo[sa]?|al|a)\s+([\w\s]+?)\s*\((\d{1,2})\)\s*(?:d[íi]as?\s+)?del\s+m\w{1,3}\s+de\s+'
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
            r'(?:el|a\s+lo[sa]?|al|a)\s+(\d{1,2})\s*\(\w+\)\s+d[íi]as?\s+del\s+m\w{1,3}\s+de\s+'
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

    def extract_date_from_considerando(text_chunk: str) -> str | None:
        """Fallback: search in DGCINE presentation paragraph."""
        match = re.search(
            r'[Cc]onsiderando.{0,100}?'
            r'(?:en\s+fecha|el\s+d[íi]a)\s+(\w+)\s*\((\d{1,2})\)\s+del\s+m\w{1,3}\s+de\s+'
            r'(enero|febrero|marzo|abril|mayo|junio|julio|agosto|'
            r'septiembre|octubre|noviembre|diciembre)'
            r'.{0,50}\((\d{4})\).{0,200}'
            r'(?:art[íi]culo\s+(?:13[79]|170)|present[oó]).{0,100}(?:CIPAC|Consejo)',
            text_chunk, re.IGNORECASE | re.DOTALL
        )
        if match:
            day = match.group(2).zfill(2)
            month = MONTHS.get(match.group(3).lower(), '00')
            year = match.group(4)
            if debug:
                debug_log("[DEBUG][resolution_date] Considerando pattern matched.")
                debug_log(f"[DEBUG][resolution_date] parsed='{year}-{month}-{day}'")
            return f"{year}-{month}-{day}"
        return None

    # Primary — opening paragraph (first 1000 chars)
    result = extract_date(text[:1000])
    if result:
        return result

    # Secondary — full document
    result = extract_date(text)
    if result:
        return result

    # Fallback — Considerando DGCINE presentation paragraph
    result = extract_date_from_considerando(text)
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


def parse_validated_amount_dop(text: str) -> float | None:
    """Parse the validated investment amount from the main resolution text."""
    # Try with and without colon after PRIMERO
    amount = parse_amount_dop(text, 'PRIMERO: VALIDAR')
    if amount is not None:
        return amount

    amount = parse_amount_dop(text, 'PRIMERO VALIDAR')
    if amount is not None:
        return amount

    # Reconsideration resolutions often move VALIDAR to SEGUNDO.
    amount = parse_amount_dop(text, 'SEGUNDO: VALIDAR')
    if amount is not None:
        return amount

    amount = parse_amount_dop(text, 'SEGUNDO VALIDAR')
    if amount is not None:
        return amount

    fallback_patterns = [
        r'inversi[oó]n.{0,220}?ascendente\s+a\s+la\s+suma(?:\s+de)?(?:\s+[^\(\.;]{1,140})?\s*\(?\s*R\s*D\s*[S$\.]{0,2}\s*([\d,\.]+)',
        r'realiz[oó]\s+una\s+inversi[oó]n.{0,180}?R\s*D\s*[S$\.]{0,2}\s*([\d,\.]+)',
        r'monto\s+de\s+R\s*D\s*[S$\.]{0,2}\s*([\d,\.]+).{0,120}?inversi[oó]n',
    ]

    for pattern in fallback_patterns:
        match = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
        if not match:
            continue
        val = parse_amount_value(match.group(1))
        if val is not None:
            return val

    return None


def parse_total_budget_approved(text: str, debug: bool = False) -> float | None:
    """Parse approved budget from CPND approval paragraph."""
    patterns = [
        r'aprob[óo0]\s+un\s+presupuesto\s+total.{0,220}?R\s*D\s*[S$\.]{0,2}\s*([\d,\.]+)',
        r'presupuesto\s+a\s+aplicar\s+al\s+incentivo.{0,260}?R\s*D\s*[S$\.]{0,2}\s*([\d,\.]+)',
        r'aprob[óo0].{0,120}?presupuesto.{0,260}?R\s*D\s*[S$\.]{0,2}\s*([\d,\.]+)',
        r'aprob[óo0].{0,100}?presu\w*.{0,260}?R\s*D\s*[S$\.]{0,2}\s*([\d,\.]+)',
        r'presupuesto\s+total\s+(?:aprobado|a\s+aplicar).{0,220}?R\s*D\s*[S$\.]{0,2}\s*([\d,\.]+)',
        r'aprob[óo0].{0,100}?pre.{0,30}?total.{0,200}?R\s*D\s*[S$\.]{0,2}\s*([\d,\.]+)',
        r'presupuesto\s+aprobado\s+ascendente.{0,200}?R\s*D\s*[S$\.]{0,2}\s*([\d,\.]+)',
        r'presupuesto\s+aprobado\s+ascendente.{0,200}?\((\d{1,3}(?:,\d{3})*\.\d{2})\)',
        r'presupuesto\s+aprobado\s+para\s+la\s+producci[oó]n.{0,100}?R\s*D\s*[S$\.]{0,2}\s*([\d,\.]+)',
        r'aprob[óo0]\s+un\s+presupuesto\s+ascendiente.{0,400}?R\s*D\s*[S$\.]{0,2}\s*([\d,\.]+)',
        r'con\s+un\s+presupuesto\s+aprobado\s+ascendente.{0,400}?R\s*D\s*[S$\.]{0,2}\s*([\d,\.]+)',
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
        r'ejecuci[oó]n\s+(?:total|parcial)\s+del\s+presupuesto.{0,400}?R\s*D\s*[S$\.]{0,2}\s*([\d,\.]+)',
        r'gastos\s+ejecutados.{0,200}?R\s*D\s*[S$\.]{0,2}\s*([\d,\.]+)',
        r'gastos\s+v[áa]lidos\s+ascendente.{0,400}?R\s*D\s*[S$\.]{0,2}\s*([\d,\.]+)',
        r'ejecuci[oó]n\s+(?:total|parcial).{0,260}?R\s*D\s*[S$\.]{0,2}\s*([\d,\.]+)',
        r'presupuesto\s+ejecutado.{0,300}?R\s*D\s*[S$\.]{0,2}\s*([\d,\.]+)',
        r'ejecut[oó]\s+(?:un\s+)?presupuesto.{0,300}?R\s*D\s*[S$\.]{0,2}\s*([\d,\.]+)',
        r'ejecuci[oó]n\s+de\s+un\s+presupuesto\s+total.{0,200}?R\s*D\s*[S$\.]{0,2}\s*([\d,\.]+)',
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
    total_budget_executed: float | None,
    resolution_type: str = 'approved',
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

    # Skip monetary fields for rejected resolutions
    if resolution_type == 'approved':
        if validated_amount_dop is None:
            score -= 0.10
            reasons.append('missing_validated_amount_dop')

        if tax_credit_dop is None:
            score -= 0.10
            reasons.append('missing_tax_credit_dop')

        if total_budget_approved is None:
            score -= 0.10
            reasons.append('missing_total_budget_approved')

        if total_budget_executed is None:
            score -= 0.10
            reasons.append('missing_total_budget_executed')

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
    resolution_type = parse_resolution_type(text_norm)

    investor = parse_investor_name(text_norm)
    production_company = parse_production_company(text_norm)

    # Normalize text fields to uppercase
    if investor:
        investor = investor.upper()
    if production_company:
        production_company = production_company.upper()

    if incentive_article == 'art_39':
        investor_rnc = None
        producer_rnc = parse_rnc(text_norm, 'R.N.C. Productor')
        if not production_company:
            production_company = investor
            producer_rnc = parse_rnc(text_norm, 'R.N.C')
        investor = None
    else:
        investor_rnc = parse_rnc(text_norm, 'R.N.C')
        producer_rnc = parse_rnc(text_norm, 'R.N.C. Productor', exclude_rnc=investor_rnc)

    resolution_date = parse_resolution_date(text_norm)
    total_budget_approved = parse_total_budget_approved(text_norm)
    total_budget_executed = parse_total_budget_executed(text_norm)

    validated_amount_dop = None
    tax_credit_dop = None
    if resolution_type == 'approved':
        validated_amount_dop = parse_validated_amount_dop(text_norm)
        tax_credit_dop = parse_amount_dop(text_norm, 'SEGUNDO: AUTORIZAR')

        # Art. 34: validated_amount and tax_credit are always equal
        # Use tax_credit_dop as the reference — it comes from the cleaner SEGUNDO paragraph
        if incentive_article == 'art_34':
            if tax_credit_dop and not validated_amount_dop:
                validated_amount_dop = tax_credit_dop
            elif validated_amount_dop and not tax_credit_dop:
                tax_credit_dop = validated_amount_dop
            elif tax_credit_dop and validated_amount_dop and tax_credit_dop != validated_amount_dop:
                validated_amount_dop = tax_credit_dop

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
        total_budget_executed=total_budget_executed,
        resolution_type=resolution_type,
    )

    return {
        'resolution_number':      resolution_number,
        'year':                   year,
        'incentive_article':      incentive_article,
        'resolution_type':        resolution_type,
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


def process_pdf(pdf_path: str, force_azure: bool = False) -> dict | None:
    """Process a single CIPAC PDF and return extracted fields."""
    print(f"Processing: {os.path.basename(pdf_path)}")

    text = extract_text(pdf_path, force_azure=force_azure)
    if not text:
        print(f"  Could not extract text from {pdf_path}")
        return None

    fields = extract_cipac_fields(text, pdf_path)
    return fields


def process_all_pdfs(
    year_filter: list[str] | None = None,
    force_azure: bool = False,
    skip_existing: bool = False,
) -> list[dict]:
    """Process all CIPAC PDFs in the raw data directory."""
    results = []
    cipac_dir = os.path.join(RAW_DATA_DIR, 'cipac')

    # Years with poor scan quality that benefit from Azure OCR
    AZURE_YEARS = {'2012', '2013'}

    if not os.path.exists(cipac_dir):
        print(f"Directory not found: {cipac_dir}")
        return results

    for year_dir in sorted(Path(cipac_dir).iterdir()):
        if not year_dir.is_dir():
            continue

        year = year_dir.name
        if year_filter and year not in year_filter:
            continue

        use_azure = force_azure or year in AZURE_YEARS

        # Load existing results if skip_existing
        existing_files = set()
        if skip_existing:
            json_path = os.path.join('data', f'cipac_{year}_results.json')
            if os.path.exists(json_path):
                with open(json_path, encoding='utf-8') as f:
                    existing = json.load(f)
                existing_files = {r['source_file'] for r in existing}
                results.extend(existing)

        pdfs = list(year_dir.glob('*.pdf'))
        new_pdfs = [p for p in pdfs if p.name not in existing_files]
        print(f"\nYear {year}: {len(pdfs)} PDFs total, {len(new_pdfs)} new {'(Azure)' if use_azure else ''}")

        for pdf_path in sorted(new_pdfs):
            fields = process_pdf(str(pdf_path), force_azure=use_azure)
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
            INSERT OR REPLACE INTO cipac_resolutions (
                resolution_number,
                year,
                movie_id,
                pur_number,
                cpnd_number,
                incentive_article,
                resolution_type,
                investor_name,
                investor_rnc,
                local_company,
                producer_rnc,
                foreign_producer,
                film_title,
                request_date,
                resolution_date,
                validated_amount_dop,
                tax_credit_dop,
                total_budget_approved,
                total_budget_executed,
                extraction_confidence,
                needs_review,
                review_reasons,
                manually_reviewed,
                manual_note,
                source_file
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            fields.get('resolution_number'),
            fields.get('year'),
            None,
            fields.get('pur_number'),
            fields.get('cpnd_number'),
            fields.get('incentive_article'),
            fields.get('resolution_type'),
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