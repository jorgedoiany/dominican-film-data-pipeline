import unittest

from extractor.manual_corrections import carry_over, corrected_fields, refresh_review_flags

NOTE = ('total_budget_approved|set_manual|null|29736672.00|Amount from CPND|CPND No. 004|2026-08-13|JDP'
        ';;production_company|correct_value|OCR_garbage|CINDERELO, S.R.L.|OCR error|PDF header|2026-10-30|JDP')


class CorrectedFields(unittest.TestCase):
    def test_reads_every_cited_field(self):
        names, whole = corrected_fields(NOTE)
        self.assertEqual(names, {'total_budget_approved', 'production_company'})
        self.assertFalse(whole)

    def test_pipe_inside_a_value_does_not_break_the_field_name(self):
        note = 'investor_name|set_manual|null|SERVINET, S.R.L. | KE KARIBE, S.R.L.|Multiple investors|PDF|2026-08-13|JDP'
        self.assertEqual(corrected_fields(note)[0], {'investor_name'})

    def test_empty_or_missing_note(self):
        self.assertEqual(corrected_fields(None), (set(), False))
        self.assertEqual(corrected_fields(''), (set(), False))

    def test_whole_record_marker(self):
        self.assertTrue(corrected_fields('record|set_manual|null|all_fields|Stamped PDF|PDF|2026-08-13|JDP')[1])


class CarryOver(unittest.TestCase):
    def setUp(self):
        self.prior = {'resolution_number': 'CIPAC-2012-012', 'total_budget_approved': 29736672.0,
                      'production_company': 'CINDERELO, S.R.L.', 'film_title': 'FEO DE DIA',
                      'manual_note': NOTE, 'manually_reviewed': True}
        self.fresh = {'resolution_number': 'CIPAC-2012-012', 'total_budget_approved': None,
                      'production_company': '. CONSIDERANDO: QUE EN FECHA', 'film_title': 'FEE DE DIA',
                      'manual_note': None, 'manually_reviewed': False}

    def test_cited_fields_are_kept_and_the_rest_is_re_extracted(self):
        carried = carry_over(self.fresh, self.prior)
        self.assertEqual(carried, ['production_company', 'total_budget_approved'])
        self.assertEqual(self.fresh['total_budget_approved'], 29736672.0)
        self.assertEqual(self.fresh['production_company'], 'CINDERELO, S.R.L.')
        self.assertEqual(self.fresh['film_title'], 'FEE DE DIA')  # not cited, so the new extraction wins

    def test_protected_fields_are_never_copied(self):
        self.prior['manual_note'] = 'resolution_number|set_manual|a|b|r|s|d|JDP;;manual_note|set_manual|a|b|r|s|d|JDP'
        self.assertEqual(carry_over(self.fresh, self.prior), [])
        self.assertEqual(self.fresh['resolution_number'], 'CIPAC-2012-012')

    def test_empty_previous_value_does_not_erase_the_new_one(self):
        self.prior['total_budget_approved'] = None
        self.fresh['total_budget_approved'] = 5.0
        carry_over(self.fresh, self.prior)
        self.assertEqual(self.fresh['total_budget_approved'], 5.0)

    def test_field_that_is_not_a_column_is_ignored(self):
        self.prior['manual_note'] = 'budget_executed|set_manual|null|1.0|typo|s|d|JDP'
        self.assertEqual(carry_over(self.fresh, self.prior), [])

    def test_whole_record_note_copies_every_unprotected_field(self):
        self.prior['manual_note'] = 'record|set_manual|null|all_fields|Stamped PDF|PDF|2026-08-13|JDP'
        carried = carry_over(self.fresh, self.prior)
        self.assertEqual(carried, ['film_title', 'production_company', 'total_budget_approved'])


class RefreshReviewFlags(unittest.TestCase):
    def test_resolved_reasons_are_dropped(self):
        f = {'total_budget_approved': 1.0, 'producer_rnc': None,
             'review_reasons': 'missing_total_budget_approved;missing_producer_rnc', 'needs_review': True}
        refresh_review_flags(f)
        self.assertEqual(f['review_reasons'], 'missing_producer_rnc')
        self.assertTrue(f['needs_review'])

    def test_no_reasons_left_clears_the_flag(self):
        f = {'total_budget_approved': 1.0, 'review_reasons': 'missing_total_budget_approved', 'needs_review': True}
        refresh_review_flags(f)
        self.assertIsNone(f['review_reasons'])
        self.assertFalse(f['needs_review'])

    def test_other_reasons_are_kept(self):
        f = {'review_reasons': 'low_confidence', 'needs_review': True}
        refresh_review_flags(f)
        self.assertEqual(f['review_reasons'], 'low_confidence')
        self.assertTrue(f['needs_review'])


if __name__ == '__main__':
    unittest.main()
