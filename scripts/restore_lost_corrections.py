#!/usr/bin/env python3
"""Restore manual corrections whose value was lost but whose note survived.

For each (resolution, field) in RESTORE, the value is read from the latest
`set_manual` entry of that record's manual_note. It is written to dgcine.db
and to the yearly JSON only where the current value is empty or is extraction
garbage (text from the resolution preamble). A different non-empty value is
never overwritten: the script stops instead. manual_note is not changed.

Dry-run by default (writes nothing). Use --apply to write. Safe to re-run.
"""
import argparse
import json
import re
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

DB_PATH = Path('database/dgcine.db')
NUMERIC = {'validated_amount_dop', 'tax_credit_dop', 'total_budget_approved', 'total_budget_executed'}
GARBAGE = re.compile(r'CONSIDERANDO|QUE EN FECHA')

RESTORE = [
    ('CIPAC-2012-001', 'producer_rnc'), ('CIPAC-2012-001', 'request_date'),
    ('CIPAC-2012-001', 'tax_credit_dop'), ('CIPAC-2012-001', 'validated_amount_dop'),
    ('CIPAC-2012-001', 'production_company'),
    ('CIPAC-2012-002', 'investor_rnc'), ('CIPAC-2012-002', 'producer_rnc'),
    ('CIPAC-2012-003', 'investor_rnc'), ('CIPAC-2012-003', 'producer_rnc'),
    ('CIPAC-2012-004', 'investor_rnc'), ('CIPAC-2012-004', 'producer_rnc'),
    ('CIPAC-2012-005', 'investor_rnc'), ('CIPAC-2012-005', 'producer_rnc'),
    ('CIPAC-2012-010', 'producer_rnc'), ('CIPAC-2012-011', 'producer_rnc'),
]
FIELDS = {f for _, f in RESTORE}


def note_value(note, field):
    val = None
    for e in (note or '').split(';;'):
        p = e.split('|')
        if len(p) == 8 and p[0] == field and p[1] in ('set_manual', 'correct_value'):
            val = p[3]
    return None if val in (None, '', 'null') else val


def cast(field, s):
    return float(s) if field in NUMERIC else s


def is_empty_or_garbage(v):
    return v is None or str(v).strip() == '' or bool(GARBAGE.search(str(v)))


def status(cur, target):
    if is_empty_or_garbage(cur):
        return 'will restore'
    if cur == target or (isinstance(cur, (int, float)) and isinstance(target, float) and round(cur, 2) == round(target, 2)):
        return 'already restored'
    return f'UNEXPECTED value (not overwritten): {cur!r}'


def json_format(text):
    data = json.loads(text)
    body = text.rstrip('\n')
    for indent in (2, 4, 1, None):
        for ea in (False, True):
            if json.dumps(data, indent=indent, ensure_ascii=ea) == body:
                return dict(indent=indent, ensure_ascii=ea), text.endswith('\n')
    return None, None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--apply', action='store_true', help='write changes (default: dry-run)')
    args = ap.parse_args()

    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    jsons, plan, problems = {}, [], []
    print(f"{'APPLY' if args.apply else 'DRY-RUN'}\n")
    for res, f in RESTORE:
        assert f in FIELDS
        row = con.execute(f"SELECT {f} AS v, manual_note FROM cipac_resolutions WHERE resolution_number = ?", (res,)).fetchone()
        year = res.split('-')[1]
        if year not in jsons:
            p = Path(f'data/cipac_{year}_results.json')
            text = p.read_text(encoding='utf-8')
            fmt, nl = json_format(text)
            jsons[year] = dict(path=p, data=json.loads(text), fmt=fmt, nl=nl)
        rec = next((r for r in jsons[year]['data'] if r['resolution_number'] == res), None)
        nv = note_value(row['manual_note'], f) if row else None
        if row is None or rec is None or nv is None:
            print(f"{res} | {f}: PROBLEM (record or note value missing)")
            problems.append((res, f))
            continue
        target = cast(f, nv)
        db_s, js_s = status(row['v'], target), status(rec.get(f), target)
        print(f"{res} | {f} -> {target!r}\n   DB  : {db_s}\n   JSON: {js_s}")
        if db_s.startswith('UNEXPECTED') or js_s.startswith('UNEXPECTED'):
            problems.append((res, f))
        plan.append((res, f, target, db_s == 'will restore', js_s == 'will restore'))

    for j in jsons.values():
        print(f"\nJSON format {j['path']}: " + ('reproducible' if j['fmt'] else 'NOT reproducible'))
        if j['fmt'] is None:
            problems.append((str(j['path']), 'format'))
    if problems:
        print('\nSTOPPED. Nothing was written. Problems:', problems)
        sys.exit(1)
    if not any(d or s for *_, d, s in plan):
        print('\nNothing to do: all values are already restored.')
        return
    if not args.apply:
        print('\nDry-run only. Re-run with --apply to write.')
        return

    stamp = datetime.now().strftime('%Y%m%d-%H%M%S')
    for p in [DB_PATH] + [j['path'] for j in jsons.values()]:
        shutil.copy2(p, p.with_name(p.name + f'.bak-{stamp}'))
    print(f'\nBackups written (*.bak-{stamp}). Do not commit them.')
    with con:
        for res, f, target, do_db, _ in plan:
            if do_db:
                con.execute(f"UPDATE cipac_resolutions SET {f} = ? WHERE resolution_number = ?", (target, res))
    for res, f, target, _, do_js in plan:
        if do_js:
            rec = next(r for r in jsons[res.split('-')[1]]['data'] if r['resolution_number'] == res)
            rec[f] = target
    for j in jsons.values():
        j['path'].write_text(json.dumps(j['data'], **j['fmt']) + ('\n' if j['nl'] else ''), encoding='utf-8')
    print('Applied.')


if __name__ == '__main__':
    main()
