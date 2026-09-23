"""Jamal feedback #6 — the agreement and the booking sheet (2026-09-23).

Jamal supplied a real hall agreement and a real «تفاصيل الحجز» sheet, with the note that
«contract and booking to be able doing this, however, they will have different template».

So two things are asserted here: that each document carries the content its source document
carries, mapped onto REAL fields, and that the two stay different documents — the booking
sheet has no legal text and no signatures, the agreement has both.

⚠ The supplied files belong to «قاعات بلدي للأفراح والمناسبات» (Ramallah), a different
company. Its clause wording is deliberately absent from this addon, and
test_no_other_companys_contract_wording_was_copied keeps it that way.
"""
from datetime import datetime

from odoo import Command
from odoo.tests import tagged

from .common import SevenStarsCommon

EVENING = (datetime(2033, 9, 14, 18, 0), datetime(2033, 9, 14, 23, 0))
CONTRACTS = ('action_report_hall_contract', 'action_report_henna_contract',
             'action_report_lunch_contract')


@tagged('post_install', '-at_install')
class TestContractAndBookingDocuments(SevenStarsCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.hall = cls._hall("DOC Hall", 600, 9000.0)
        cls.service = cls._service("DOC تصوير", 1200.0)
        cls.customer.write({
            'street': "الولجة", 'city': "بيت لحم",
            'phone': '+970 2 274 0000', 'whatsapp': '+970 599 123 456',
            'id_number': '900112233', 'responsible_person': "أبو المناسبة",
        })
        cls.booking = cls.env['sale.order'].create({
            'partner_id': cls.customer.id,
            'is_rental_order': True,
            'rental_start_date': EVENING[0],
            'rental_return_date': EVENING[1],
            'event_type': 'wedding',
            'guest_count': 450,
            'groom_name': "سامي",
            'bride_name': "ليلى",
            'required_deposit_amount': 3000.0,
            'internal_note_men': "ملاحظة الرجال",
            'internal_note_women': "ملاحظة النساء",
            'order_line': [
                Command.create({'product_id': cls.hall.product_variant_id.id,
                                'product_uom_qty': 1, 'is_rental': True}),
                Command.create({'product_id': cls.service.product_variant_id.id,
                                'product_uom_qty': 1}),
            ],
        })

    def _html(self, xmlid, record=None):
        report = self.env.ref(f'seven_stars_rental.{xmlid}')
        body, _type = report._render_qweb_html(
            report.report_name, (record or self.booking).ids)
        return body.decode() if isinstance(body, bytes) else body

    # ------------------------------------------------------------- the booking sheet
    def test_the_booking_sheet_carries_every_section_of_the_supplied_document(self):
        html = self._html('action_report_booking_sheet')
        for heading in ("تفاصيل الحجز", "معلومات الحجز الأساسية", "عنوان الحاجز",
                        "تفاصيل المناسبة", "معلومات القاعة", "المعلومات المالية",
                        "الخدمات الإضافية", "السعر النهائي للحجز"):
            self.assertIn(heading, html, f"the booking sheet is missing «{heading}»")

    def test_the_booking_sheet_shows_real_booking_data(self):
        html = self._html('action_report_booking_sheet')
        self.assertIn(self.booking.name, html)
        self.assertIn(self.customer.name, html)
        self.assertIn("سامي", html)
        self.assertIn("ليلى", html)
        self.assertIn("450", html, "the guest count belongs on the sheet")
        self.assertIn(self.hall.name, html, "the hall comes from the rental line")
        self.assertIn("الولجة", html)
        self.assertIn('+970 599 123 456', html, "WhatsApp belongs on the sheet")

    def test_the_booking_sheet_lists_the_services_actually_charged(self):
        html = self._html('action_report_booking_sheet')
        self.assertIn(self.service.name, html,
                      "extra services are order lines, not free text")

    def test_the_booking_sheet_never_prints_the_currency_twice(self):
        """The supplied sheet printed «₪ 1,900.00 ₪» — a hand-typed symbol beside the
        widget's own. Ours may not."""
        html = self._html('action_report_booking_sheet')
        self.assertNotIn('₪ ₪', html)
        self.assertNotIn('₪&nbsp;₪', html)

    def test_an_empty_address_prints_nothing_not_bare_commas(self):
        """The supplied sheet printed «، ،» for a customer with no address."""
        blank = self.env['res.partner'].create({'name': "بدون عنوان"})
        # A separate date: copying the booking would hold the same hall twice and CON-01
        # would rightly refuse it.
        order = self.env['sale.order'].create({
            'partner_id': blank.id,
            'is_rental_order': True,
            'rental_start_date': datetime(2033, 11, 4, 18, 0),
            'rental_return_date': datetime(2033, 11, 4, 23, 0),
            'order_line': [Command.create({
                'product_id': self.hall.product_variant_id.id,
                'product_uom_qty': 1, 'is_rental': True})],
        })
        html = self._html('action_report_booking_sheet', order)
        self.assertNotIn('، ،', html)

    def test_the_booking_sheet_is_not_a_contract(self):
        """«they will have different template» — no legal text, no signature boxes."""
        html = self._html('action_report_booking_sheet')
        self.assertNotIn("التوقيع", html)
        self.assertNotIn("الفريق الأول", html)

    # ------------------------------------------------------------------- the agreement
    def test_every_contract_carries_the_agreement_structure(self):
        for xmlid in CONTRACTS:
            with self.subTest(contract=xmlid):
                html = self._html(xmlid)
                for part in ("الفريق الأول", "الفريق الثاني",
                             "أولاً: مقدمة الاتفاقية", "رابعاً: التوقيعات",
                             "التوقيع والختم"):
                    self.assertIn(part, html, f"{xmlid} is missing «{part}»")

    def test_the_agreement_intro_quotes_the_order_number_and_the_agreed_amount(self):
        html = self._html('action_report_hall_contract')
        self.assertIn(self.booking.name, html)
        self.assertIn("10,200", html, "9,000 hall + 1,200 photography")

    def test_the_first_party_is_the_company_never_hard_coded(self):
        html = self._html('action_report_hall_contract')
        self.assertIn(self.env.company.name, html)

    def test_a_contract_type_prints_its_own_approved_wording(self):
        """The three contracts are different documents because each carries its own text."""
        report = self.env.ref('seven_stars_rental.action_report_henna_contract')
        report.ss_contract_body = '<p>بند اختباري خاص بعقد الحنة.</p>'

        henna = self._html('action_report_henna_contract')
        wedding = self._html('action_report_hall_contract')

        self.assertIn("بند اختباري خاص بعقد الحنة", henna)
        self.assertNotIn("بند اختباري خاص بعقد الحنة", wedding,
                         "wording must not leak between contract types")

    def test_a_contract_with_no_approved_wording_says_so_visibly(self):
        report = self.env.ref('seven_stars_rental.action_report_lunch_contract')
        report.ss_contract_body = False

        html = self._html('action_report_lunch_contract')
        self.assertIn("الشروط والأحكام", html)
        self.assertIn("مملوك للعميل", html,
                      "missing legal text must stay visibly missing, never invented")

    def test_no_other_companys_contract_wording_was_copied(self):
        """The documents Jamal supplied belong to a different hall in Ramallah. Their
        identity and their commercial terms must never appear in a Seven Stars contract."""
        html = ''.join(self._html(xmlid) for xmlid in CONTRACTS)
        for foreign in ("بلدي", "رام الله", "البيرة", "1500 شيكل"):
            self.assertNotIn(foreign, html,
                             f"«{foreign}» belongs to another company's agreement")
