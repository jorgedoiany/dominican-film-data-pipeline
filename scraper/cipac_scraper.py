import os
import re
import time
import requests
from bs4 import BeautifulSoup
from tqdm import tqdm
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import urllib3

# Suppress SSL warnings
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


# ─────────────────────────────────────────
# CONFIGURATION
# ─────────────────────────────────────────
BASE_URL = "https://dgcine.gob.do/sobre-nosotros/cipac/resoluciones/"
AJAX_URL = "https://dgcine.gob.do/wp-admin/admin-ajax.php"
RAW_DATA_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), '..', 'data', 'raw'
)
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/120.0.0.0 Safari/537.36",
    "Referer": BASE_URL,
    "X-Requested-With": "XMLHttpRequest",
}
DELAY_SECONDS = 0.5

YEAR_CATEGORIES = {
    '2012': '2452',
    '2013': '2453',
    '2014': '2454',
    '2015': '2455',
    '2016': '2456',
    '2017': '2457',
    '2018': '2458',
    '2019': '2459',
    '2020': '2460',
    '2021': '2461',
    '2022': '2450',
    '2023': '2449',
    '2024': '2484',
}

# Known exceptions that should be included even if title quality is irregular.
FORCE_INCLUDE_RESOLUTIONS = {
    'CIPAC-2022-223',
    'CIPAC-2022-203',
    'CIPAC-2022-086',
}

# Prefixes used to skip administrative resolutions in HTML years (2025-2026)
HTML_SKIP_PREFIXES = (
    'modificacion',
    'aprobacion',
    'emision',
    'establecimiento',
    'incremento',
    'procedimiento',
    'medida reglamentaria',
    'tasas',
)


# ─────────────────────────────────────────
# SESSION WITH RETRY
# ─────────────────────────────────────────
def get_session() -> requests.Session:
    """Create a session with retry logic."""
    session = requests.Session()
    retry = Retry(
        total=3,
        backoff_factor=2,
        status_forcelist=[500, 502, 503, 504],
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount('https://', adapter)
    session.mount('http://', adapter)
    return session


# ─────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────
def normalize(text: str) -> str:
    """Normalize text — lowercase and remove accents."""
    return (
        text.lower()
        .replace('ó', 'o')
        .replace('í', 'i')
        .replace('é', 'e')
        .replace('á', 'a')
        .replace('ú', 'u')
        .replace('ñ', 'n')
    )


def extract_year(text: str) -> str | None:
    match = re.search(r'(20\d{2})', text)
    return match.group(1) if match else None


def is_validation_title(title: str) -> bool:
    """Match validation titles — handles accents, typos and short forms."""
    t = normalize(title)
    has_validation = bool(re.search(r'vali', t))
    has_exclusion = bool(re.search(
        r'calificacion|clasificacion|'
        r'validacion\W*de\W*inv?cremento\W*presupu(?:est|es)|'
        r'(?:\bconstruccion\b.*\b(sala|salas|cine|complejo)\b|'
        r'\b(sala|salas|cine|complejo)\b.*\bconstruccion\b)|'
        r'servicios\W*tecnico',
        t
    ))
    return has_validation and not has_exclusion


def extract_cipac_subject(title: str) -> str:
    """Extract text after CIPAC number to evaluate title-level rules."""
    t = normalize(title).strip()
    return re.sub(r'^cipac-\d{4}-\d+\s*[-–]?\s*', '', t)


def is_html_skip_title(title: str) -> bool:
    """Skip admin/non-project HTML resolutions by subject prefix."""
    subject = extract_cipac_subject(title)
    # Some titles start with IDs like "31014237_..."; strip non-letters first.
    subject = re.sub(r'^[^a-z]+', '', subject)
    return any(subject.startswith(prefix) for prefix in HTML_SKIP_PREFIXES)


def infer_html_year(text: str, href: str) -> str | None:
    """Infer 2025/2026 from title first, then from URL path."""
    match = re.search(r'(2025|2026)', text)
    if match:
        return match.group(1)
    match = re.search(r'/uploads/(2025|2026)/', href)
    if match:
        return match.group(1)
    return None


def is_html_resolution_candidate(text: str, href: str) -> bool:
    """Match HTML entries relevant to CIPAC 2025-2026 scraping."""
    t = normalize(text)
    h = normalize(href)

    has_cipac_token = bool(re.search(r'cipac-202[56]', t))
    has_cipac_file = bool(re.search(r'cipac-202[56]', h))
    has_admin_prefix = is_html_skip_title(text)
    in_target_year_folder = bool(re.search(r'/uploads/(2025|2026)/', h))

    return has_cipac_token or has_cipac_file or (
        in_target_year_folder and has_admin_prefix
    )


def get_incentive_type(text: str) -> str:
    """Determine incentive type from title or URL."""
    t = normalize(text)
    if re.search(r'gasto', t):
        return 'art_39'
    return 'art_34'


def parse_resolution_text(text: str) -> dict:
    """
    Parse resolution info from text like:
    CIPAC-2026-001- EL MUNDO SECRETO DE MARINA- ECO MOTORS, S.A.S
    """
    text = text.strip()

    res_match = re.match(r'(CIPAC-\d{4}-\d+)', text, re.IGNORECASE)
    resolution_number = res_match.group(1).upper() if res_match else None

    year = extract_year(text)

    parts = re.split(r'\s*[-–]\s*', text, maxsplit=3)

    film_title = parts[2].strip() if len(parts) > 2 else None
    investor_name = parts[3].strip() if len(parts) > 3 else None

    return {
        'resolution_number': resolution_number,
        'year': year,
        'film_title': film_title,
        'investor_name': investor_name,
    }


def parse_resolution_url(url: str) -> dict:
    """Parse resolution info from URL filename."""
    filename = url.split('/')[-1].replace('.pdf', '').lower()

    year_num_match = re.search(r'(\d{4})-(\d{3})', filename)
    year = year_num_match.group(1) if year_num_match else extract_year(url)
    resolution_seq = year_num_match.group(2) if year_num_match else None
    resolution_number = (
        f"CIPAC-{year}-{resolution_seq}"
        if year and resolution_seq else None
    )

    return {
        'resolution_number': resolution_number,
        'year': year,
        'film_title': None,
        'investor_name': None,
        'raw_filename': filename,
    }


def is_forced_include_resolution(url: str) -> bool:
    """Return True when a resolution must be included by exception rule."""
    resolution_number = parse_resolution_url(url).get('resolution_number')
    return bool(resolution_number in FORCE_INCLUDE_RESOLUTIONS)


# ─────────────────────────────────────────
# AJAX SCRAPER (2012-2024)
# ─────────────────────────────────────────
def get_total_pages(cat_id: str, session: requests.Session) -> int:
    """Get total pages for a category."""
    params = {
        'juwpfisadmin': 'false',
        'action': 'wpfd',
        'task': 'files.display',
        'view': 'files',
        'id': cat_id,
        'rootcat': cat_id,
        'page': '1',
        'orderCol': 'created_time',
        'orderDir': 'desc',
        'page_limit': '20',
        'show_files': '1'
    }
    r = session.get(
        AJAX_URL, params=params, headers=HEADERS, timeout=30, verify=False
    )
    data = r.json()

    pagination_html = data.get('pagination', '')

    if not pagination_html or not isinstance(pagination_html, str):
        return 1

    page_numbers = re.findall(r"data-page='(\d+)'", pagination_html)
    return max([int(p) for p in page_numbers], default=1)


def scrape_ajax_year(
    year: str, cat_id: str, session: requests.Session
) -> list[dict]:
    """Scrape all resolutions for a year using AJAX API."""
    results = []
    total_pages = get_total_pages(cat_id, session)

    for page in range(1, total_pages + 1):
        params = {
            'juwpfisadmin': 'false',
            'action': 'wpfd',
            'task': 'files.display',
            'view': 'files',
            'id': cat_id,
            'rootcat': cat_id,
            'page': str(page),
            'orderCol': 'created_time',
            'orderDir': 'desc',
            'page_limit': '20',
            'show_files': '1'
        }
        try:
            r = session.get(
                AJAX_URL, params=params, headers=HEADERS,
                timeout=30, verify=False
            )
            data = r.json()
            files = data.get('files', [])

            for f in files:
                download_url = f.get('linkdownload', '')
                title = f.get('post_title', '')

                if not download_url:
                    continue

                forced_include = is_forced_include_resolution(download_url)

                if not forced_include and not is_validation_title(title):
                    continue

                metadata = parse_resolution_url(download_url)
                metadata['year'] = year
                metadata['url'] = download_url
                metadata['filename'] = download_url.split('/')[-1]
                metadata['source'] = 'ajax'
                metadata['file_id'] = f.get('ID')
                metadata['created_date'] = f.get('created', '')
                metadata['incentive_type'] = get_incentive_type(title)

                results.append(metadata)

        except Exception as e:
            print(f"\nError scraping {year} page {page}: {e}")
            time.sleep(2)

        time.sleep(DELAY_SECONDS)

    return results


# ─────────────────────────────────────────
# HTML SCRAPER (2025-2026)
# ─────────────────────────────────────────
def scrape_html_years(session: requests.Session) -> list[dict]:
    """Scrape 2025-2026 resolutions directly from HTML."""
    results = []

    r = session.get(BASE_URL, headers=HEADERS, timeout=30, verify=False)
    soup = BeautifulSoup(r.text, 'html.parser')

    for a_tag in soup.find_all('a', href=True):
        href = str(a_tag['href'])
        text = a_tag.get_text(strip=True)

        if not is_html_resolution_candidate(text, href):
            continue

        if not href.endswith('.pdf'):
            continue

        if is_html_skip_title(text):
            continue

        metadata = parse_resolution_text(text)
        metadata['url'] = href
        metadata['filename'] = href.split('/')[-1]
        metadata['source'] = 'html'
        metadata['file_id'] = None
        metadata['created_date'] = ''
        metadata['raw_filename'] = href.split('/')[-1].lower()
        metadata['year'] = infer_html_year(text, href)
        metadata['incentive_type'] = get_incentive_type(text)

        results.append(metadata)

    return results


# ─────────────────────────────────────────
# DOWNLOAD
# ─────────────────────────────────────────
def download_pdf(
    url: str, filename: str, year_dir: str, session: requests.Session
) -> str | None:
    """Download a PDF and save it to the year directory."""
    os.makedirs(year_dir, exist_ok=True)
    filepath = os.path.join(year_dir, filename)

    if os.path.exists(filepath):
        return filepath

    try:
        r = session.get(url, headers=HEADERS, timeout=60, verify=False)
        r.raise_for_status()
        with open(filepath, 'wb') as f:
            f.write(r.content)
        return filepath
    except Exception as e:
        print(f"\nError downloading {url}: {e}")
        return None


# ─────────────────────────────────────────
# MAIN SCRAPER
# ─────────────────────────────────────────
def scrape_resolutions(download: bool = True) -> list[dict]:
    """
    Main scraper — fetch all CIPAC investment validation resolutions.

    Args:
        download: If True, download PDFs. If False, only collect metadata.
    """
    print("Starting CIPAC resolutions scraper...")
    print(f"Source: {BASE_URL}")
    print(f"Output: {RAW_DATA_DIR}")
    print("─" * 50)

    session = get_session()
    all_links: list[dict] = []

    # ── 2012-2024: AJAX API ──
    print("\nScraping 2012-2024 via AJAX API...")
    for year, cat_id in sorted(YEAR_CATEGORIES.items()):
        links = scrape_ajax_year(year, cat_id, session)
        all_links.extend(links)
        print(f"  {year}: {len(links)} resolutions found")
        time.sleep(DELAY_SECONDS)

    # ── 2025-2026: HTML ──
    print("\nScraping 2025-2026 via HTML...")
    html_links = scrape_html_years(session)

    years_html: dict[str, int] = {}
    for link in html_links:
        year = link.get('year') or 'unknown'
        years_html[year] = years_html.get(year, 0) + 1

    for year, count in sorted(years_html.items()):
        print(f"  {year}: {count} resolutions found")

    all_links.extend(html_links)

    # ── Summary ──
    print(f"\nTotal resolutions found: {len(all_links)}")

    art_34 = sum(1 for l in all_links if l.get('incentive_type') == 'art_34')
    art_39 = sum(1 for l in all_links if l.get('incentive_type') == 'art_39')
    print(f"  Art. 34 (Dominican): {art_34}")
    print(f"  Art. 39 (Foreign):   {art_39}")

    if not download:
        return all_links

    # ── Download PDFs ──
    print("\nStarting downloads...")
    downloaded = 0
    errors = 0
    results = []

    for link in tqdm(all_links, desc="Downloading PDFs"):
        year = link.get('year') or 'unknown'
        year_dir = os.path.join(RAW_DATA_DIR, 'cipac', str(year))
        filepath = download_pdf(
            link['url'], link['filename'], year_dir, session
        )

        if filepath:
            downloaded += 1
            results.append({**link, 'filepath': filepath})
        else:
            errors += 1

        time.sleep(DELAY_SECONDS)

    print(f"\nScraping complete:")
    print(f"  Downloaded: {downloaded}")
    print(f"  Errors:     {errors}")

    return results


if __name__ == "__main__":
    results = scrape_resolutions(download=False)

    print(f"\nBreakdown by year:")
    years: dict[str, int] = {}
    for r in results:
        year = r.get('year') or 'unknown'
        years[year] = years.get(year, 0) + 1

    for year in sorted(years.keys()):
        print(f"  {year}: {years[year]}")