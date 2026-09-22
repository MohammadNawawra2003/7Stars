"""Phase 6 — the historical import, and the one way CON-01 can be stood down.

The rule the plan sets: audit FIRST, produce a written conflict list, clean or approve every
pair with the client, and only then import. Any technical bypass must be explicit,
migration-only, scoped to the run and tested.
"""
from datetime import datetime

from odoo.exceptions import ValidationError
from odoo.tests import tagged

from .common import SevenStarsCommon
from odoo.addons.seven_stars_rental.models.sale_order import SS_MIGRATION_CONTEXT_KEY


@tagged('post_install', '-at_install')
class TestImportAudit(SevenStarsCommon):
    """The audit runs on the SOURCE data, before a single record is created."""

    def test_the_audit_finds_the_pairs_con_01_would_refuse(self):
        rows = [
            # same hall, same evening — a straight overlap
            {'ref': 'OLD-001', 'hall': 'hall_3',
             'start': '2024-05-10 15:00:00', 'end': '2024-05-10 20:00:00'},
            {'ref': 'OLD-002', 'hall': 'hall_3',
             'start': '2024-05-10 17:00:00', 'end': '2024-05-10 21:00:00'},
            # same hall, next morning — clear of the event but inside the 5h cleanup
            {'ref': 'OLD-003', 'hall': 'hall_3',
             'start': '2024-05-10 23:00:00', 'end': '2024-05-11 02:00:00'},
            # a different hall at the same hour is not a conflict
            {'ref': 'OLD-004', 'hall': 'hall_4',
             'start': '2024-05-10 15:00:00', 'end': '2024-05-10 20:00:00'},
            # and a later date on the same hall is fine
            {'ref': 'OLD-005', 'hall': 'hall_3',
             'start': '2024-06-14 15:00:00', 'end': '2024-06-14 20:00:00'},
        ]
        conflicts = self.env['sale.order'].ss_find_import_conflicts(rows)
        pairs = {tuple(sorted(conflict['refs'])) for conflict in conflicts}

        self.assertIn(('OLD-001', 'OLD-002'), pairs)
        self.assertIn(('OLD-001', 'OLD-003'), pairs, "the cleanup buffer counts as occupied")
        self.assertNotIn(('OLD-001', 'OLD-004'), pairs, "different halls never clash")
        self.assertNotIn(('OLD-001', 'OLD-005'), pairs)
        for conflict in conflicts:
            self.assertEqual(conflict['hall'], 'hall_3')

    def test_clean_source_data_produces_an_empty_conflict_list(self):
        rows = [
            {'ref': 'OK-001', 'hall': 'hall_1',
             'start': '2024-07-05 09:00:00', 'end': '2024-07-05 13:00:00'},
            {'ref': 'OK-002', 'hall': 'hall_2',
             'start': '2024-07-05 09:00:00', 'end': '2024-07-05 13:00:00'},
            {'ref': 'OK-003', 'hall': 'hall_1',
             'start': '2024-07-12 09:00:00', 'end': '2024-07-12 13:00:00'},
        ]
        self.assertEqual(self.env['sale.order'].ss_find_import_conflicts(rows), [])

    def test_the_audit_honours_per_hall_buffers(self):
        """A hall with no cleanup time makes two adjacent bookings legal."""
        rows = [
            {'ref': 'B-001', 'hall': 'hall_9', 'prep': 0, 'cleanup': 0,
             'start': '2024-08-02 09:00:00', 'end': '2024-08-02 13:00:00'},
            {'ref': 'B-002', 'hall': 'hall_9', 'prep': 0, 'cleanup': 0,
             'start': '2024-08-02 13:00:00', 'end': '2024-08-02 17:00:00'},
        ]
        self.assertEqual(self.env['sale.order'].ss_find_import_conflicts(rows), [],
                         "half-open windows: one booking may end where the next begins")


@tagged('post_install', '-at_install')
class TestMigrationBypass(SevenStarsCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.hall = cls._hall("MIG Hall", 600, 14000.0).product_variant_id
        cls.clerk = cls._user('test_mig_clerk', 'group_ss_clerk')
        cls.manager = cls._user('test_mig_manager', 'group_ss_manager')
        cls.window = (datetime(2024, 9, 5, 18, 0), datetime(2024, 9, 5, 23, 0))
        cls.overlapping = (datetime(2024, 9, 5, 20, 0), datetime(2024, 9, 5, 23, 30))

    def _migration_env(self, user):
        return self.env['sale.order'].with_user(user).with_context(
            **{SS_MIGRATION_CONTEXT_KEY: True})

    def test_without_the_flag_a_historical_overlap_is_refused(self):
        self._booking([self.hall], *self.window)
        with self.assertRaises(ValidationError):
            self._booking([self.hall], *self.overlapping)

    def test_the_flag_alone_does_not_switch_con_01_off(self):
        """The context arrives from the client on every RPC call, so the flag by itself has
        to be worthless. A clerk who passes it gets exactly the same refusal."""
        self._booking([self.hall], *self.window, user=self.clerk)
        with self.assertRaises(ValidationError):
            self._migration_env(self.clerk).create({
                'partner_id': self.customer.id, 'is_rental_order': True,
                'rental_start_date': self.overlapping[0],
                'rental_return_date': self.overlapping[1],
                'order_line': [(0, 0, {'product_id': self.hall.id,
                                       'product_uom_qty': 1, 'is_rental': True})],
            })

    def test_management_plus_the_flag_may_load_an_approved_historical_overlap(self):
        self._booking([self.hall], *self.window)
        imported = self._migration_env(self.manager).create({
            'partner_id': self.customer.id, 'is_rental_order': True,
            'rental_start_date': self.overlapping[0],
            'rental_return_date': self.overlapping[1],
            'order_line': [(0, 0, {'product_id': self.hall.id,
                                   'product_uom_qty': 1, 'is_rental': True})],
        })
        self.assertTrue(imported.id)

    def test_con_01_fires_normally_again_once_the_run_is_over(self):
        """The bypass is scoped to the run, not stored anywhere. This is the assertion that
        matters most: the import must not leave availability checking weakened."""
        self._booking([self.hall], *self.window)
        self._migration_env(self.manager).create({
            'partner_id': self.customer.id, 'is_rental_order': True,
            'rental_start_date': self.overlapping[0],
            'rental_return_date': self.overlapping[1],
            'order_line': [(0, 0, {'product_id': self.hall.id,
                                   'product_uom_qty': 1, 'is_rental': True})],
        })

        # ordinary user, ordinary context — the everyday path, unchanged
        with self.assertRaises(ValidationError):
            self._booking([self.hall], *self.overlapping, user=self.clerk)
        # and management gets no free pass without the flag either
        with self.assertRaises(ValidationError):
            self._booking([self.hall], *self.overlapping, user=self.manager)

    def test_the_flag_is_not_persisted_on_the_imported_record(self):
        imported = self._migration_env(self.manager).create({
            'partner_id': self.customer.id, 'is_rental_order': True,
            'rental_start_date': datetime(2024, 10, 3, 18, 0),
            'rental_return_date': datetime(2024, 10, 3, 23, 0),
            'order_line': [(0, 0, {'product_id': self.hall.id,
                                   'product_uom_qty': 1, 'is_rental': True})],
        })
        reread = self.env['sale.order'].browse(imported.id)
        self.assertNotIn(SS_MIGRATION_CONTEXT_KEY, reread.env.context)
        with self.assertRaises(ValidationError):
            self._booking([self.hall], datetime(2024, 10, 3, 20, 0),
                          datetime(2024, 10, 3, 23, 30))
