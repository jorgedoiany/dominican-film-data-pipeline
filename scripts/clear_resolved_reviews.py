#!/usr/bin/env python3
"""Set needs_review = 0 where every review reason is resolved.

A reason 'missing_<field>' counts as resolved only when the field has a value
AND manual_note has a `<field>|set_manual|` or `<field>|correct_value|` entry.
review_reasons is kept as history. Records with any unresolved reason are left
untouched. Applies to dgcine.db and the yearly JSON files.

Dry-run by default (writes nothing). Use --apply to write. Safe to re-run.
"""
import argparse
import json
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

DB_PATH = Path('database/dgcine.db')


def resolved(row):
    note = row['manual_note'] or ''
    for reason in (row['review_reasons'] or '').split(';'):
        f = reason.replace('missing_', '', 1)
        if row[f] is None or row[f] == '':
            return False
        if f"{f}|set_manual|" not in note and f"{f}|correct_value|" not in note:
            return False
    return bool(row['review_reasons'])


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
    flagged = con.execute("SELECT * FROM cipac_resolutions WHERE needs_review = 1 ORDER BY resolution_number").fetchall()
    todo = [r['resolution_number'] for r in flagged if resolved(r)]
    left = [r['resolution_number'] for r in flagged if not resolved(r)]
    print(f"{'APPLY' if args.apply else 'DRY-RUN'} | flagged: {len(flagged)} | resolved: {len(todo)} | still pending: {len(left)}")
    for r in left:
        print('   stays flagged:', r)
    jsons, problems = {}, []
    for year in sorted({t.split('-')[1] for t in todo}):
        p = Path(f'data/cipac_{year}_results.json')
        text = p.read_text(encoding='utf-8')
        fmt, nl = json_format(text)
        jsons[year] = dict(path=p, data=json.loads(text), fmt=fmt, nl=nl)
        if fmt is None:
            problems.append(str(p))
    if problems:
        print('STOPPED. JSON format not reproducible:', problems)
        sys.exit(1)
    if not todo:
        print('Nothing to do.')
        return
    print('Will clear needs_review on:', ', '.join(todo))
    if not args.apply:
        print('Dry-run only. Re-run with --apply to write.')
        return
    stamp = datetime.now().strftime('%Y%m%d-%H%M%S')
    for p in [DB_PATH] + [j['path'] for j in jsons.values()]:
        shutil.copy2(p, p.with_name(p.name + f'.bak-{stamp}'))
    print(f'Backups written (*.bak-{stamp}). Do not commit them.')
    with con:
        for res in todo:
            con.execute("UPDATE cipac_resolutions SET needs_review = 0 WHERE resolution_number = ?", (res,))
    for res in todo:
        rec = next(r for r in jsons[res.split('-')[1]]['data'] if r['resolution_number'] == res)
        rec['needs_review'] = False
    for j in jsons.values():
        j['path'].write_text(json.dumps(j['data'], **j['fmt']) + ('\n' if j['nl'] else ''), encoding='utf-8')
    print('Applied.')


if __name__ == '__main__':
    main()
