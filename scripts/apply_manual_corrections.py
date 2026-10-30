#!/usr/bin/env python3
"""Apply documented manual corrections to dgcine.db and the yearly JSON files.

Dry-run by default (writes nothing). Use --apply to write.
Safe to re-run: a correction already applied is skipped and a note is never
added twice. Each applied correction appends one entry to manual_note, in the
same format as earlier manual corrections:
    field|action|old|new|reason|source|date|author
An entry with garbage=True accepts any current value that is extraction
garbage (text from the resolution preamble) instead of an exact old value.
"""
import argparse
import json
import re
import shutil
import sqlite3
import sys
from datetime import date, datetime
from pathlib import Path

DB_PATH = Path('database/dgcine.db')
AUTHOR = 'JDP'
ALLOWED_FIELDS = {'film_title', 'investor_name', 'production_company'}
GARBAGE = re.compile(r'CONSIDERANDO|QUE EN FECHA')

SUFFIX = 'Legal suffix standardized to the dotted form for consistency across records of the same entity'
SAME_RNC = 'Consistency with other resolutions of the same RNC'
GARBAGE_REASON = 'OCR captured Considerando paragraph instead of the name'


def fix(res, field, old, new, reason, source, action='set_manual', garbage=False):
    return dict(res=res, field=field, old=old, new=new, reason=reason,
                source=source, action=action, garbage=garbage)


CORRECTIONS = [
    fix('CIPAC-2012-012', 'film_title', 'FEE DE DÍA, LINDO DE NOCHE', 'FEO DE DÍA, LINDO DE NOCHE',
        'OCR misread FEO as FEE', 'Resolution PDF title'),
    fix('CIPAC-2012-012', 'investor_name', 'RNC: 1-01-04029-7', 'BANCO MÚLTIPLE BDI, S.A.',
        'Name field held the RNC instead of the investor name', 'Resolution PDF header'),
    fix('CIPAC-2012-014', 'film_title', 'FEE DE DÍA, LINDO DE NOCHE', 'FEO DE DÍA, LINDO DE NOCHE',
        'OCR misread FEO as FEE; same film as CIPAC-2012-012', 'productions table'),
    fix('CIPAC-2020-051', 'film_title', 'TRAVESIÍA', 'TRAVESÍA',
        'Extra letter I; correct spelling per JSON and productions table', 'cipac_2020_results.json'),
    fix('CIPAC-2012-015', 'film_title', 'FEO DE DÍA, LINDA DE NOCHE', 'FEO DE DÍA, LINDO DE NOCHE',
        'OCR misread LINDO as LINDA', 'Resolution PDF title'),
    fix('CIPAC-2012-016', 'film_title', 'FEO DE DÍA, LINDA DE NOCHE', 'FEO DE DÍA, LINDO DE NOCHE',
        'OCR misread LINDO as LINDA; same film as CIPAC-2012-015', 'productions table'),
    fix('CIPAC-2022-202', 'film_title', "DOMINICANA'S GOTTALENT - SEGUNDA TEMPORADA",
        "DOMINICANA'S GOT TALENT-SEGUNDA TEMPORADA",
        'Extraction merged GOT TALENT and added spaces around the hyphen', 'Resolution PDF title'),
    # --- Entity name consistency (rule A: dotted legal suffix) ---
    fix('CIPAC-2012-002', 'production_company', 'ENTREPRENEUR FILMS, SRL', 'ENTREPRENEUR FILMS, S.R.L.', SUFFIX, SAME_RNC),
    fix('CIPAC-2012-003', 'production_company', 'ENTREPRENEUR FILMS, SRL', 'ENTREPRENEUR FILMS, S.R.L.', SUFFIX, SAME_RNC),
    fix('CIPAC-2012-004', 'production_company', 'ENTREPRENEUR FILMS, SRL', 'ENTREPRENEUR FILMS, S.R.L.', SUFFIX, SAME_RNC),
    fix('CIPAC-2012-005', 'production_company', 'ENTREPRENEUR FILMS, SRL', 'ENTREPRENEUR FILMS, S.R.L.', SUFFIX, SAME_RNC),
    fix('CIPAC-2012-012', 'production_company', 'CINDERELLA, SRL', 'CINDERELO, S.R.L.',
        'OCR misread CINDERELO as CINDERELLA; suffix standardized', SAME_RNC),
    fix('CIPAC-2012-013', 'production_company', 'OCR_garbage', 'CINDERELO, S.R.L.', GARBAGE_REASON,
        'Resolution PDF header', action='correct_value', garbage=True),
    fix('CIPAC-2012-014', 'production_company', 'CINDERELO, SRL', 'CINDERELO, S.R.L.', SUFFIX, SAME_RNC),
    fix('CIPAC-2012-015', 'production_company', 'OCR_garbage', 'CINDERELO, S.R.L.', GARBAGE_REASON,
        'Resolution PDF header', action='correct_value', garbage=True),
    fix('CIPAC-2012-016', 'production_company', 'CINDERELO, SRL', 'CINDERELO, S.R.L.', SUFFIX, SAME_RNC),
    fix('CIPAC-2012-019', 'production_company', 'CINDERELO, SRL', 'CINDERELO, S.R.L.', SUFFIX, 'Same company name as other resolutions of the film'),
    fix('CIPAC-2012-020', 'production_company', 'CINDERELO, SRL', 'CINDERELO, S.R.L.', SUFFIX, SAME_RNC),
    fix('CIPAC-2012-005', 'investor_name', 'UNITED BRANDS, S. A.', 'UNITED BRANDS, S.A.',
        'Extra space inside the legal suffix', SAME_RNC),
    fix('CIPAC-2012-013', 'investor_name', 'CENTROS DEL CARIBE, SAS', 'CENTROS DEL CARIBE, S.A.S.', SUFFIX, SAME_RNC),
    fix('CIPAC-2012-020', 'investor_name', 'SIGMA PETROLEUM CORP., SRL', 'SIGMA PETROLEUM CORP, S.R.L.',
        'Extra period after CORP; suffix standardized', SAME_RNC),
    fix('CIPAC-2012-015', 'investor_name', 'OCR_garbage', 'CARIBBEAN FILMS DISTRIBUTION, S.R.L.', GARBAGE_REASON,
        'Resolution PDF header', action='correct_value', garbage=True),
    fix('CIPAC-2016-103', 'investor_name', 'CARIBBEAN FILMS DISTRIBUTION R&L, S.R.L.',
        'CARIBBEAN FILMS DISTRIBUTION, S.R.L.',
        'Extra R&L in the name; same entity as CIPAC-2012-015', SAME_RNC),
    fix('CIPAC-2012-010', 'investor_name', 'ORANGE DOMINICANA, S. A.', 'ALTICE DOMINICANA, S.A.',
        'Same entity as the other resolutions of this RNC (company rebranded from Orange to Altice)',
        SAME_RNC, action='correct_value'),
    fix('CIPAC-2012-019', 'investor_name', 'CENTRO CUESTA NACIONAL (CCN), C. POR A.', 'CENTRO CUESTA NACIONAL, S.A.S.',
        'Same entity as the other resolutions of this RNC (legal form and name written differently)',
        SAME_RNC, action='correct_value'),
]


def marker(c):
    return f"{c['field']}|{c['action']}|{c['old']}|{c['new']}|"


def entry(c, today):
    return f"{marker(c)}{c['reason']}|{c['source']}|{today}|{AUTHOR}"


def add_note(existing, c, today):
    if existing and marker(c) in existing:
        return existing, False
    e = entry(c, today)
    return (f"{existing};;{e}" if existing else e), True


def json_format(text):
    """Find json.dumps kwargs that reproduce the file exactly, or None."""
    data = json.loads(text)
    body = text.rstrip('\n')
    for indent in (2, 4, 1, None):
        for ea in (False, True):
            if json.dumps(data, indent=indent, ensure_ascii=ea) == body:
                return dict(indent=indent, ensure_ascii=ea), text.endswith('\n')
    return None, None


def status(cur, c):
    if cur == c['new']:
        return 'already applied'
    if c['garbage']:
        if isinstance(cur, str) and GARBAGE.search(cur):
            return 'will apply'
    elif cur == c['old']:
        return 'will apply'
    return f'UNEXPECTED value: {cur!r}'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--apply', action='store_true', help='write changes (default: dry-run)')
    args = ap.parse_args()
    today = date.today().isoformat()

    for c in CORRECTIONS:
        assert c['field'] in ALLOWED_FIELDS, c['field']

    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row

    jsons = {}  # year -> dict(path, data, fmt, nl)
    problems = []
    pending = False
    print(f"{'DRY-RUN' if not args.apply else 'APPLY'} | date {today}\n")
    for c in CORRECTIONS:
        row = con.execute(
            f"SELECT {c['field']} AS v, manual_note FROM cipac_resolutions WHERE resolution_number = ?",
            (c['res'],)).fetchone()
        year = str(c['res']).split('-')[1]
        if year not in jsons:
            p = Path(f'data/cipac_{year}_results.json')
            text = p.read_text(encoding='utf-8')
            fmt, nl = json_format(text)
            jsons[year] = dict(path=p, data=json.loads(text), fmt=fmt, nl=nl)
        rec = next((r for r in jsons[year]['data'] if r['resolution_number'] == c['res']), None)
        db_status = 'MISSING record' if row is None else status(row['v'], c)
        js_status = 'MISSING record' if rec is None else status(rec.get(c['field']), c)
        print(f"{c['res']} | {c['field']}\n   DB  : {db_status}\n   JSON: {js_status}")
        pending = pending or 'will apply' in (db_status, js_status) \
            or (row is not None and marker(c) not in (row['manual_note'] or '')) \
            or (rec is not None and marker(c) not in (rec.get('manual_note') or ''))
        for s in (db_status, js_status):
            if s.startswith(('UNEXPECTED', 'MISSING')):
                problems.append((c['res'], c['field'], s[:90]))

    for j in jsons.values():
        print(f"\nJSON format {j['path']}: " + ('reproducible' if j['fmt'] else 'NOT reproducible'))
        if j['fmt'] is None:
            problems.append((str(j['path']), 'format', 'cannot rewrite without a noisy diff'))

    if problems:
        print('\nSTOPPED. Nothing was written. Problems:')
        for p in problems:
            print('  ', p)
        sys.exit(1)

    if not pending:
        print('\nNothing to do: all corrections and notes are already in place.')
        return

    if not args.apply:
        print('\nDry-run only. Re-run with --apply to write.')
        return

    stamp = datetime.now().strftime('%Y%m%d-%H%M%S')
    for p in [DB_PATH] + [j['path'] for j in jsons.values()]:
        shutil.copy2(p, p.with_name(p.name + f'.bak-{stamp}'))
    print(f'\nBackups written (*.bak-{stamp}). Do not commit them.')

    with con:  # single transaction
        for c in CORRECTIONS:
            cur = con.execute(
                f"SELECT {c['field']} AS v, manual_note FROM cipac_resolutions WHERE resolution_number = ?",
                (c['res'],)).fetchone()
            note, _ = add_note(cur['manual_note'], c, today)
            con.execute(
                f"UPDATE cipac_resolutions SET {c['field']} = ?, manual_note = ?, manually_reviewed = 1 "
                "WHERE resolution_number = ?", (c['new'], note, c['res']))

    for c in CORRECTIONS:
        j = jsons[str(c['res']).split('-')[1]]
        rec = next(r for r in j['data'] if r['resolution_number'] == c['res'])
        rec[c['field']] = c['new']
        rec['manual_note'], _ = add_note(rec.get('manual_note'), c, today)
        rec['manually_reviewed'] = True
    for j in jsons.values():
        out = json.dumps(j['data'], **j['fmt']) + ('\n' if j['nl'] else '')
        j['path'].write_text(out, encoding='utf-8')

    print('\nApplied. Verify with: sqlite3 -readonly database/dgcine.db '
          '"SELECT resolution_number, film_title, production_company, investor_name FROM cipac_resolutions '
          "WHERE resolution_number BETWEEN 'CIPAC-2012-002' AND 'CIPAC-2012-020' OR resolution_number IN ('CIPAC-2020-051','CIPAC-2022-202');\"")


if __name__ == '__main__':
    main()
