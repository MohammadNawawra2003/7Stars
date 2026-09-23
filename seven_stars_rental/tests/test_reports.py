"""The eight documents (spec §10).

Arabic prints right-to-left because report HTML takes its direction from res.lang.direction
(web/views/report_templates.xml:29, :83, :270). rtlcss governs the backend UI bundle only
and is irrelevant here — the C6 correction, confirmed at runtime by T13.
"""
from odoo import Command
from odoo.tests import tagged

from .common import SevenStarsCommon

ORDER_REPORTS = [
    'action_report_hall_contract',
    'action_report_henna_contract',
    'action_report_lunch_contract',
    'action_report_operational_appendix',
    'action_report_booking_confirmation',
    'action_report_payment_statement',
    'action_report_event_details',
]


@tagged('post_install', '-at_install')
class TestReports(SevenStarsCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.hall_men = cls._hall("RPT Hall Men", 600, 14000.0)
        cls.hall_women = cls._hall("RPT Hall Women", 550, 14000.0)
        cls.service = cls._service("RPT Photography", 1500.0)

        cls.pair_pricelist = cls.env['product.pricelist'].create({
            'name': "RPT wedding pair", 'currency_id': cls.ils.id})
        cls.env['product.pricing'].create([
            {'product_template_id': cls.hall_men.id, 'recurrence_id': cls.recurrence.id,
             'price': 14000.0, 'pricelist_id': cls.pair_pricelist.id},
            {'product_template_id': cls.hall_women.id, 'recurrence_id': cls.recurrence.id,
             'price': 0.0, 'pricelist_id': cls.pair_pricelist.id},
        ])

        cls.booking = cls.env['sale.order'].create({
            'partner_id': cls.customer.id,
            'is_rental_order': True,
            'pricelist_id': cls.pair_pricelist.id,
            'rental_start_date': '2035-04-14 15:00:00',
            'rental_return_date': '2035-04-14 20:00:00',
            'event_type': 'wedding',
            'guest_count': 800,
            'required_deposit_amount': 3000.0,
            'internal_note_men': "ملاحظات قاعة الرجال",
            'internal_note_women': "ملاحظات قاعة النساء",
            'appendix_event_date': '2035-04-14',
            'appendix_promo_show': True,
            'appendix_dabke_women': True,
            'appendix_lighting': "إنارة كاملة",
            'appendix_hospitality_men': "قهوة وتمر",
            'appendix_hospitality_time': "19:30",
            'appendix_details': "تفاصيل الاختبار",
            'order_line': [
                Command.create({'product_id': cls.hall_men.product_variant_id.id,
                                'product_uom_qty': 1, 'is_rental': True}),
                Command.create({'product_id': cls.hall_women.product_variant_id.id,
                                'product_uom_qty': 1, 'is_rental': True}),
                Command.create({'product_id': cls.service.product_variant_id.id,
                                'product_uom_qty': 1}),
                Command.create({'display_type': 'line_note', 'name': "— تصوير فوتوغرافي"}),
            ],
        })
        cls.payment = cls._post_payment(cls.booking, 3000.0, 'cash', 'REC-TEST-1')

    @classmethod
    def _post_payment(cls, order, amount, journal_type, memo):
        """Money is a posted account.payment since 2026-09-23."""
        payment = cls.env['account.payment'].create({
            'ss_order_id': order.id,
            'partner_id': order.partner_id.id,
            'partner_type': 'customer',
            'payment_type': 'inbound',
            'amount': amount,
            'journal_id': cls.env['account.journal'].search(
                [('type', '=', journal_type)], limit=1).id,
            'memo': memo,
        })
        payment.action_post()
        return payment

    def _html(self, xmlid, record):
        report = self.env.ref(f'seven_stars_rental.{xmlid}')
        body, report_type = report._render_qweb_html(report.report_name, record.ids)
        self.assertEqual(report_type, 'html')
        return body.decode() if isinstance(body, bytes) else body

    def test_all_eight_reports_render(self):
        for xmlid in ORDER_REPORTS:
            with self.subTest(report=xmlid):
                html = self._html(xmlid, self.booking)
                self.assertIn('<html', html, f"{xmlid} produced no document")
        receipt = self._html('action_report_payment_receipt', self.payment)
        self.assertIn('<html', receipt)

    def test_arabic_documents_render_right_to_left(self):
        html = self._html('action_report_hall_contract', self.booking)
        self.assertIn('dir="rtl"', html,
                      "the contract must print right-to-left; res.lang.direction drives this")

    def test_the_contract_shows_both_halls_and_the_agreed_total(self):
        """A wedding prints TWO hall rows and ONE price. 28,000 must never appear."""
        html = self._html('action_report_hall_contract', self.booking)
        self.assertIn(self.hall_men.name, html)
        self.assertIn(self.hall_women.name, html, "the women's hall belongs on the contract")
        # 14,000 for the pair + 1,500 photography + the two appendix items this fixture ticks
        # (عرض برومو 500, فرقة دبكة 1,200), which are now order lines rather than bare flags.
        self.assertEqual(self.booking.amount_total, 17200.0)
        self.assertNotIn('28,000', html)
        self.assertNotIn('29,000', html)

    def test_the_contract_carries_the_customer_owned_placeholder_not_invented_legal_text(self):
        html = self._html('action_report_hall_contract', self.booking)
        self.assertIn('الشروط والأحكام', html)
        self.assertIn('مملوك للعميل', html,
                      "the clause block must stay visibly a placeholder until Seven Stars "
                      "supplies its own wording")

    def test_the_contract_has_signature_blocks_for_both_parties(self):
        html = self._html('action_report_hall_contract', self.booking)
        self.assertIn('الطرف الأول', html)
        self.assertIn('الطرف الثاني', html)
        self.assertIn('التوقيع', html)

    def test_the_appendix_prints_all_fifteen_items(self):
        html = self._html('action_report_operational_appendix', self.booking)
        for label in ("تاريخ المناسبة", "عرض برومو", "فرقة دبكة", "فرقة زفة للعريس",
                      "عرض الزفة على الشاشات", "نظام الإنارة", "ضيافة قاعة الرجال",
                      "ضيافة قاعة النساء", "موعد تنزيل الضيافة", "التوزيعات",
                      "حجز طاولات أهل العريس", "حجز طاولات أهل العروس", "أمن القاعة",
                      "استوديو التصوير", "التفاصيل"):
            self.assertIn(label, html, f"the appendix is missing «{label}»")

    def test_the_payment_statement_lists_every_payment_row(self):
        self._post_payment(self.booking, 2000.0, 'bank', 'TRF-TEST-2')
        html = self._html('action_report_payment_statement', self.booking)
        self.assertIn('REC-TEST-1', html)
        self.assertIn('TRF-TEST-2', html)

    def test_the_receipt_is_for_one_payment(self):
        html = self._html('action_report_payment_receipt', self.payment)
        self.assertIn('REC-TEST-1', html)
        self.assertIn('إيصال دفع', html)

    def test_the_staff_sheet_shows_the_preparation_and_cleanup_window(self):
        """RPT-08 is for the floor: it prints when each hall is really occupied, which is the
        event plus its 4h preparation and 5h cleanup."""
        html = self._html('action_report_event_details', self.booking)
        self.assertIn('بداية التجهيز', html)
        self.assertIn('2035-04-14 11:00:00', html, "15:00 minus the 4h preparation buffer")
        self.assertIn('2035-04-15 01:00:00', html, "20:00 plus the 5h cleanup buffer")

    def test_every_report_is_bound_and_uses_a4(self):
        a4 = self.env.ref('base.paperformat_euro')
        for xmlid in ORDER_REPORTS + ['action_report_payment_receipt']:
            report = self.env.ref(f'seven_stars_rental.{xmlid}')
            self.assertEqual(report.report_type, 'qweb-pdf', xmlid)
            self.assertEqual(report.paperformat_id, a4, xmlid)
            self.assertTrue(report.binding_model_id, f"{xmlid} is not on any Print menu")
