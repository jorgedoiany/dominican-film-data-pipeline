#!/usr/bin/env python3
"""Apply documented manual corrections to dgcine.db and the yearly JSON files.

Dry-run by default (writes nothing). Use --apply to write.
Safe to re-run: a correction already applied is skipped and a note is never
added twice. Each applied correction appends one entry to manual_note, in the
same format as earlier manual corrections:
    field|set_manual|old|new|reason|source|date|author
"""
import argparse
import json
import shutil
import sqlite3
import sys
from datetime import date, datetime
from pathlib import Path

DB_PATH = Path('database/dgcine.db')
AUTHOR = 'JDP'
ALLOWED_FIELDS = {'film_title', 'investor_name'}

CORRECTIONS = [
    dict(res='CIPAC-2012-012', field='film_title',
         old='FEE DE DÍA, LINDO DE NOCHE', new='FEO DE DÍA, LINDO DE NOCHE',
         reason='OCR misread FEO as FEE', source='Resolution PDF title'),
    dict(res='CIPAC-2012-012', field='investor_name',
         old='RNC: 1-01-04029-7', new='BANCO MÚLTIPLE BDI, S.A.',
         reason='Name field held the RNC instead of the investor name',
         source='Resolution PDF header'),
    dict(res='CIPAC-2012-014', field='film_title',
         old='FEE DE DÍA, LINDO DE NOCHE', new='FEO DE DÍA, LINDO DE NOCHE',
         reason='OCR misread FEO as FEE; same film as CIPAC-2012-012',
         source='productions table'),
    dict(res='CIPAC-2020-051', field='film_title',
         old='TRAVESIÍA', new='TRAVESÍA',
         reason='Extra letter I; correct spelling per JSON and productions table',
         source='cipac_2020_results.json'),
    dict(res='CIPAC-2012-015', field='film_title',
         old='FEO DE DÍA, LINDA DE NOCHE', new='FEO DE DÍA, LINDO DE NOCHE',
         reason='OCR misread LINDO as LINDA', source='Resolution PDF title'),
    dict(res='CIPAC-2012-016', field='film_title',
         old='FEO DE DÍA, LINDA DE NOCHE', new='FEO DE DÍA, LINDO DE NOCHE',
         reason='OCR misread LINDO as LINDA; same film as CIPAC-2012-015',
         source='productions table'),
    dict(res='CIPAC-2022-202', field='film_title',
         old="DOMINICANA'S GOTTALENT - SEGUNDA TEMPORADA",
         new="DOMINICANA'S GOT TALENT-SEGUNDA TEMPORADA",
         reason='Extraction merged GOT TALENT and added spaces around the hyphen',
         source='Resolution PDF title'),
]


def marker(c):
    return f"{c['field']}|set_manual|{c['old']}|{c['new']}|"


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
    if cur == c['old']:
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

    jsons = {}  # year -> dict(path, text, data, fmt, nl)
    problems = []
    pending = False
    print(f"{'DRY-RUN' if not args.apply else 'APPLY'} | date {today}\n")
    for c in CORRECTIONS:
        row = con.execute(
            f"SELECT {c['field']} AS v, manual_note FROM cipac_resolutions WHERE resolution_number = ?",
            (c['res'],)).fetchone()
        year = c['res'].split('-')[1]
        if year not in jsons:
            p = Path(f'data/cipac_{year}_results.json')
            text = p.read_text(encoding='utf-8')
            fmt, nl = json_format(text)
            jsons[year] = dict(path=p, text=text, data=json.loads(text), fmt=fmt, nl=nl)
        j = jsons[year]
        rec = next((r for r in j['data'] if r['resolution_number'] == c['res']), None)
        db_status = 'MISSING record' if row is None else status(row['v'], c)
        js_status = 'MISSING record' if rec is None else status(rec.get(c['field']), c)
        print(f"{c['res']} | {c['field']}\n   DB  : {db_status}\n   JSON: {js_status}")
        pending = pending or 'will apply' in (db_status, js_status) \
            or (row is not None and marker(c) not in (row['manual_note'] or '')) \
            or (rec is not None and marker(c) not in (rec.get('manual_note') or ''))
        for s in (db_status, js_status):
            if s.startswith(('UNEXPECTED', 'MISSING')):
                problems.append((c['res'], c['field'], s))

    for y, j in jsons.items():
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
        j = jsons[c['res'].split('-')[1]]
        rec = next(r for r in j['data'] if r['resolution_number'] == c['res'])
        rec[c['field']] = c['new']
        rec['manual_note'], _ = add_note(rec.get('manual_note'), c, today)
        rec['manually_reviewed'] = True
    for j in jsons.values():
        out = json.dumps(j['data'], **j['fmt']) + ('\n' if j['nl'] else '')
        j['path'].write_text(out, encoding='utf-8')

    print('\nApplied. Verify with: git diff --stat && sqlite3 -readonly database/dgcine.db '
          '"SELECT resolution_number, film_title, investor_name FROM cipac_resolutions '
          "WHERE resolution_number IN ('CIPAC-2012-012','CIPAC-2012-014','CIPAC-2020-051');\"")


if __name__ == '__main__':
    main()