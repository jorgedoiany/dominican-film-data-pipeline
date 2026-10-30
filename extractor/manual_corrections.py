"""Keep manually corrected values when a year is reprocessed.

Reprocessing a PDF re-extracts every field, so a value fixed by hand would be
lost. A manual_note records each correction as
    field|action|old|new|reason|source|date|author
separated by ';;'. The fields named in the note are copied back from the
previous record. Fields the note does not mention keep the fresh extraction.

The previous record must hold the corrected values (the yearly JSON file).
Pure functions with no third-party imports, so they are easy to test.
"""

# Never copied from the previous record: they identify the record or are
# recalculated by the extraction itself.
PROTECTED = {
    'resolution_number', 'year', 'source_file', 'manually_reviewed', 'manual_note',
    'extraction_confidence', 'needs_review', 'review_reasons',
}


def corrected_fields(note):
    """Return (field names cited in the note, True when the whole record was set by hand)."""
    names, whole_record = set(), False
    for entry in (note or '').split(';;'):
        parts = entry.split('|')
        if len(parts) < 2:
            continue
        field = parts[0].strip()
        if field == 'record' and 'all_fields' in parts:
            whole_record = True
        elif field:
            names.add(field)
    return names, whole_record


def carry_over(fields, prior):
    """Copy manually corrected values from `prior` into the re-extracted `fields`.

    Only non-empty values are copied, and only for fields the note cites. Returns
    the sorted list of field names that were carried over.
    """
    names, whole_record = corrected_fields(prior.get('manual_note'))
    if whole_record:
        names = set(prior)
    carried = []
    for name in sorted(names - PROTECTED):
        value = prior.get(name)
        if value is None or value == '':
            continue
        fields[name] = value
        carried.append(name)
    return carried


def refresh_review_flags(fields):
    """Drop 'missing_<field>' review reasons whose field now has a value."""
    reasons = [r for r in (fields.get('review_reasons') or '').split(';') if r]
    pending = [r for r in reasons
               if not (r.startswith('missing_') and fields.get(r[len('missing_'):]) not in (None, ''))]
    fields['review_reasons'] = ';'.join(pending) or None
    fields['needs_review'] = bool(pending)
