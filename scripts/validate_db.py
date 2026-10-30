#!/usr/bin/env python3
"""Read-only validation of cipac_resolutions in database/dgcine.db.

Prints, per rule, how many records violate it and a few examples.
It never writes. Exit code is always 0: this is a report, not a gate.
"""
import re
import sqlite3
from collections import defaultdict
from pathlib import Path

DB_PATH = Path('database/dgcine.db')
RNC = re.compile(r'^\d-\d{2}-\d{5}-\d$|^\d{3}-\d{7}-\d$')
DATE = re.compile(r'^\d{4}-\d{2}-\d{2}$')
GARBAGE = re.compile(r'CONSIDERANDO|QUE EN FECHA|PARA LA APLICACI|^RNC\b|\ufffd')
NAME_COLS = ('investor_name', 'production_company', 'film_title')

findings = defaultdict(list)


def flag(rule, row, detail=''):
    findings[rule].append(f"{row['resolution_number']} {detail}".strip())


def main():
    con = sqlite3.connect(f'file:{DB_PATH}?mode=ro', uri=True)
    con.row_factory = sqlite3.Row
    rows = con.execute("SELECT r.*, p.pur_number AS p_pur, p.cpnd_number AS p_cpnd "
                       "FROM cipac_resolutions r LEFT JOIN productions p ON p.project_id = r.project_id").fetchall()

    for r in rows:
        m = re.match(r'^CIPAC-(\d{4})-(\d{3})$', r['resolution_number'] or '')
        if not m:
            flag('R1 resolution_number format', r)
        elif m.group(1) != str(r['year']):
            flag('R1 year column differs from resolution_number', r, f"year={r['year']}")

        for c in ('investor_rnc', 'producer_rnc'):
            v = r[c]
            if v is not None and not RNC.match(v):
                flag(f'R2 {c} format', r, repr(v))

        rd, qd = r['resolution_date'], r['request_date']
        for c, v in (('request_date', qd), ('resolution_date', rd)):
            if v is not None and not DATE.match(v):
                flag(f'R3 {c} not ISO', r, repr(v))
        if qd and rd and DATE.match(qd) and DATE.match(rd):
            if qd > rd:
                flag('R3 request_date after resolution_date', r, f'{qd} > {rd}')
            if rd[:4] != str(r['year']):
                flag('R3 resolution_date year differs from year', r, f'{rd} vs {r["year"]}')

        art, pct = r['incentive_article'], r['tax_credit_pct']
        expected = {'art_34': 100.0, 'art_39': 25.0}.get(art)
        if expected is not None and pct is not None and abs(pct - expected) > 0.01:
            flag('R4 tax_credit_pct does not match article', r, f'{art} pct={pct}')
        v, t = r['validated_amount_dop'], r['tax_credit_dop']
        if v is not None and t is not None and pct is not None:
            if abs(t - v * pct / 100) > max(1.0, 0.001 * v):
                flag('R4 tax_credit_dop != pct x validated', r, f'validated={v} credit={t} pct={pct}')
            if t > v + 1:
                flag('R4 tax_credit_dop greater than validated', r, f'{t} > {v}')
        for c in ('validated_amount_dop', 'tax_credit_dop', 'total_budget_approved', 'total_budget_executed'):
            if r[c] is not None and r[c] <= 0:
                flag(f'R5 {c} not positive', r, repr(r[c]))
        a, e = r['total_budget_approved'], r['total_budget_executed']
        if a and e and not (0.2 <= e / a <= 5):
            flag('R5 budget executed/approved ratio outside 0.2-5 (review)', r, f'approved={a} executed={e}')

        for c in NAME_COLS:
            v = r[c]
            if v is None:
                continue
            if GARBAGE.search(v):
                flag(f'R6 {c} looks like extraction garbage', r, v[:50])
            elif v != v.strip() or '  ' in v:
                flag(f'R6 {c} has extra spaces', r, repr(v[:50]))
            elif len(v) > 90:
                flag(f'R6 {c} unusually long', r, v[:50])

        if art == 'art_34':
            for c in ('cpnd_number', 'investor_name', 'investor_rnc'):
                if r[c] in (None, ''):
                    flag(f'R7 art_34 without {c}', r)
        if art == 'art_39' and r['investor_name']:
            flag('R7 art_39 with investor_name (review)', r, r['investor_name'][:40])

        if r['project_id'] is None:
            flag('R8 no project_id', r)
        else:
            if r['p_pur'] is None and r['p_cpnd'] is None:
                flag('R8 project_id not found in productions', r, r['project_id'])
            elif r['pur_number'] and r['p_pur'] is not None and str(r['pur_number']).lstrip('0') != str(r['p_pur']):
                flag('R8 pur_number differs from productions', r, f"{r['pur_number']} vs {r['p_pur']}")

    seen = defaultdict(list)
    for r in rows:
        key = (r['film_title'], r['investor_rnc'], r['validated_amount_dop'], r['resolution_date'])
        seen[key].append(r['resolution_number'])
    for key, res in seen.items():
        if len(res) > 1:
            findings['R9 possible duplicates (same title, investor RNC, amount, date)'].append(' / '.join(res))

    per_project = defaultdict(lambda: defaultdict(set))
    for r in rows:
        if r['project_id'] and r['incentive_article'] == 'art_34':
            for c in ('total_budget_approved', 'total_budget_executed'):
                if r[c] is not None:
                    per_project[(r['project_id'], c)]['v'].add(round(r[c], 2))
    for (pid, c), d in per_project.items():
        if len(d['v']) > 1:
            findings[f'R10 art_34 project with several distinct {c} (review)'].append(f'{pid}: {sorted(d["v"])[:3]}')

    print(f'Validated {len(rows)} records.\n')
    if not findings:
        print('No violations found.')
    for rule in sorted(findings):
        items = findings[rule]
        print(f'{rule}: {len(items)}')
        for it in items[:5]:
            print('    ', it[:150])
        if len(items) > 5:
            print(f'     ... and {len(items) - 5} more')


if __name__ == '__main__':
    main()
