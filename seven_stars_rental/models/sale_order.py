"""The booking. A standard sale.order in rental mode — no new central model (spec §1.3).

CON-01 lives here. Odoo 19 Rental never blocks or warns on an overlapping booking: there is
no action_confirm, no _action_confirm and no write override in sale_renting, and its only
date constraint is a single-row SQL CHECK (sale_renting/models/sale_order.py:24) that is
structurally unable to compare two rows. The gantt's consolidation_max is 1e9. Availability
is therefore entirely ours (spec §3.1).
"""
import base64
import logging
from datetime import timedelta

from odoo import Command, api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.tools.pdf import merge_pdf

from .product_template import APPENDIX_ITEMS
from .res_config_settings import (
    GUEST_TOLERANCE_KEY, SAME_DAY_GAP_KEY, get_optional_float,
)

_logger = logging.getLogger(__name__)

# The midweek discount exists but its day range was never stated, so it ships UNSET
# in the same way as the two deferred rules of spec §8.
MIDWEEK_WEEKDAYS_KEY = 'seven_stars_rental.midweek_weekdays'

# Phase 6. The ONLY way CON-01 can be stood down, and only for a controlled historical
# import. Never a disabled constraint and never a global switch.
SS_MIGRATION_CONTEXT_KEY = 'ss_migration_import'

EVENT_TYPES = [
    ('wedding', "زفاف"),
    ('lunch', "غداء"),
    ('henna', "حنة"),
    ('engagement', "خطوبة"),
    ('tawjihi', "حفل توجيهي"),
    ('aqiqa', "عقيقة"),
    ('students', "حفل طلبة"),
]

# The eight PRD states. Independent of the standard `state` field, which has four values and
# keeps its own meaning; the two were verified coexisting at runtime (T4).
BOOKING_STATES = [
    ('draft', "مسودة"),
    ('tentative', "حجز مبدئي غير ثابت"),
    ('awaiting', "انتظار العربون وتوقيع العقد"),
    ('confirmed', "مؤكد"),
    ('ready', "جاهز للمناسبة"),
    ('postponed', "مؤجل"),
    ('completed', "مكتمل"),
    ('cancelled', "ملغي"),
]


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    event_type = fields.Selection(
        EVENT_TYPES, string="نوع المناسبة", tracking=True,
        help="Decides which contract is printed (spec §10).")
    guest_count = fields.Integer(
        string="عدد المعازيم", tracking=True,
        help="Always recorded. It is only checked against hall capacity once the overrun "
             "tolerance has been configured (spec §8) — while that rule is pending, "
             "recording a large number blocks nothing.")
    booking_state = fields.Selection(
        BOOKING_STATES, string="حالة الحجز", default='draft', copy=False,
        tracking=True, index=True, required=True)
    # A wedding is booked in the couple's name, and every contract and floor sheet is read by
    # staff looking for exactly these two. Kept plain text: they are not customers of the
    # business — the person who signs and pays is partner_id.
    groom_name = fields.Char(string="اسم العريس")
    bride_name = fields.Char(string="اسم العروس")
    internal_note_men = fields.Text(string="ملاحظات داخلية — قاعة الرجال")
    internal_note_women = fields.Text(string="ملاحظات داخلية — قاعة النساء")

    # The four customer details the contracts print. They already live on res.partner and the
    # contract template already binds them correctly — they printed blank because they sit on
    # a partner tab nobody opens while taking a booking. Related and writable, so the clerk
    # fills them here and they land on the customer record.
    partner_street = fields.Char(
        related='partner_id.street', string="العنوان", readonly=False)
    partner_whatsapp = fields.Char(
        related='partner_id.whatsapp', string="رقم واتساب", readonly=False)
    partner_id_number = fields.Char(
        related='partner_id.id_number', string="رقم الهوية", readonly=False)
    partner_responsible_person = fields.Char(
        related='partner_id.responsible_person',
        string="الشخص المسؤول عن المناسبة", readonly=False)

    # Picking a hall here writes the rental line, and the line is the single truth — this
    # field is a view of it, never a second copy. The price comes from the order's pricelist
    # because the line is created without one and Odoo computes it; see _inverse_ss_hall_ids.
    hall_ids = fields.Many2many(
        'product.product', string="القاعات",
        compute='_compute_ss_hall_ids', inverse='_inverse_ss_hall_ids',
        domain=[('product_tmpl_id.hall_capacity', '>', 0)],
        help="اختيار القاعة يضيفها إلى بنود الطلب بسعرها حسب قائمة أسعار الحجز.")

    # PRD §10 prints three different contracts and a booking can need more than one — a
    # wedding with a henna night and a lunch. They live on their own model, NOT as fields on
    # ir.actions.report: a stored column there makes upgrading from the web UI impossible.
    # See seven_stars_contract_type.py for the traceback that proved it.
    contract_type_ids = fields.Many2many(
        'seven.stars.contract.type', string="نوع العقد",
        help="العقود التي تُطبع لهذا الحجز. يمكن اختيار أكثر من نوع.")

    # --------------------------------------------------------------- money (§6.1)
    # required_deposit_amount is a TERM. It is the deposit agreed for this booking, and
    # nothing has been received because it has a value. Money received exists only as posted
    # account.payment records; everything below that looks like received money is a stored
    # compute over those, so the two can never drift apart.
    required_deposit_amount = fields.Monetary(
        string="العربون المطلوب", tracking=True,
        help="The deposit agreed with the customer — a condition of the booking, not a "
             "payment. Money actually received is recorded in the Payments tab.")
    # ⚠⚠⚠ These three are computed with compute_sudo and are NOT stored, and both facts are
    # load-bearing.
    #
    # They sit on EVERY sale.order, including quotations that have nothing to do with Seven
    # Stars. A plain One2many to account.payment made Odoo search that model as the reading
    # user, so a salesperson without accounting rights could no longer read any order at all:
    # measured as three standard `sale` failures (test_access_sales_person,
    # test_access_sales_manager, test_credit_limit_access). This is the same trap a field-level
    # groups= caused here before, and standard Odoo dodges it the same way — sale.order.
    # invoice_ids is computed, not a relation (sale/models/sale_order.py:239).
    #
    # Nothing is stored because a stored compute needs a real relation to depend on, which is
    # the very thing removed. account.payment invalidates them instead; see its write/create.
    payment_ids = fields.Many2many(
        'account.payment', string="الدفعات", copy=False,
        compute='_compute_ss_payment_ids', compute_sudo=True)
    collected_amount = fields.Monetary(
        string="المبلغ المدفوع", compute='_compute_ss_amounts', compute_sudo=True,
        help="Money actually received: the posted customer payments on this booking, less any "
             "refund. Named collected_amount because sale.order.amount_paid already exists "
             "and counts online payment transactions only.")
    outstanding_amount = fields.Monetary(
        string="المبلغ المتبقي", compute='_compute_ss_amounts', compute_sudo=True)
    price_approved = fields.Boolean(
        string="اعتماد السعر", tracking=True,
        help="PRD §8/§17. Management approves the price; once approved, a discount above "
             "the ceiling is allowed.\n\n"
             "⚠ This field deliberately carries NO Python groups=. A field-level ACL here "
             "reaches every sale.order in the database, and anything that reads all fields "
             "as a plain salesman then fails: adding it broke NINE standard `sale` tests "
             "with AccessError on price_approved. The clerk is kept away from it by the "
             "view, which hides the widget, and by _ss_check_management_only_write(), which "
             "is what actually stops the write over RPC. Reading a boolean flag is harmless; "
             "setting it is the part that matters.")

    # ------------------------------------------------ the operational appendix (§10)
    # Fifteen fields, in the order of the paper form. A fixed, non-repeating set, so they
    # are fields rather than a child model (spec §22). PRD §10 lists fifteen items; an
    # earlier audit miscounted fourteen.
    appendix_event_date = fields.Date(string="تاريخ المناسبة")

    # The four CHARGEABLE items. Ticking one adds its service to the order lines and unticking
    # removes it, so the money and the appendix can never disagree — the order line is the
    # truth and the checkbox is computed from it. The other appendix fields below stay
    # descriptive: they carry counts and notes, and no price per unit was ever supplied.
    appendix_promo_show = fields.Boolean(
        string="عرض برومو",
        compute='_compute_ss_appendix_items', inverse='_inverse_ss_appendix_items')
    appendix_dabke_women = fields.Boolean(
        string="فرقة دبكة (النساء)",
        compute='_compute_ss_appendix_items', inverse='_inverse_ss_appendix_items')
    appendix_zaffa_groom = fields.Boolean(
        string="فرقة زفة للعريس",
        compute='_compute_ss_appendix_items', inverse='_inverse_ss_appendix_items')
    appendix_zaffa_on_screens = fields.Boolean(
        string="عرض الزفة على الشاشات",
        compute='_compute_ss_appendix_items', inverse='_inverse_ss_appendix_items')
    appendix_lighting = fields.Char(string="نظام الإنارة")
    appendix_hospitality_men = fields.Char(string="ضيافة قاعة الرجال")
    appendix_hospitality_women = fields.Char(string="ضيافة قاعة النساء")
    appendix_hospitality_time = fields.Char(string="موعد تنزيل الضيافة")
    appendix_giveaways = fields.Char(string="التوزيعات")
    appendix_tables_groom = fields.Char(string="حجز طاولات أهل العريس")
    appendix_tables_bride = fields.Char(string="حجز طاولات أهل العروس")
    appendix_security = fields.Char(string="أمن القاعة")
    appendix_photo_studio = fields.Char(string="استوديو التصوير")
    appendix_details = fields.Text(string="التفاصيل")

    # A payment counts as received once it is posted. Odoo moves a posted payment to
    # 'in_process' and then to 'paid' when it is matched, so both mean the money is in.
    SS_RECEIVED_STATES = ('in_process', 'paid')

    def _compute_ss_payment_ids(self):
        payments = self.env['account.payment']
        for order in self:
            origin = order._origin
            order.payment_ids = payments.search(
                [('ss_order_id', '=', origin.id)]) if origin.id else payments

    @api.depends('payment_ids', 'amount_total')
    def _compute_ss_amounts(self):
        for order in self:
            collected = sum(
                payment.amount if payment.payment_type == 'inbound' else -payment.amount
                for payment in order.payment_ids
                if payment.state in self.SS_RECEIVED_STATES
            )
            order.collected_amount = collected
            order.outstanding_amount = order.amount_total - collected

    # --------------------------------------------- halls and appendix items as ORDER LINES
    def _ss_check_lines_editable(self):
        """Lines may not be added or removed once the booking has been invoiced.

        Changing them afterwards would leave the invoice disagreeing with the contract, and
        an invoice that is already posted can only be undone with a credit note.
        """
        self.ensure_one()
        if self.invoice_ids.filtered(lambda move: move.state == 'posted'):
            raise UserError(self.env._(
                "لا يمكن تعديل القاعات أو بنود الملحق التشغيلي بعد إصدار الفاتورة.\n"
                "أصدر إشعاراً دائناً أولاً إذا كان التعديل ضرورياً.\n\n"
                "The booking has a posted invoice, so its lines are fixed. Issue a credit "
                "note first if the booking really must change."))

    @api.depends('order_line.product_id', 'order_line.is_rental')
    def _compute_ss_hall_ids(self):
        for order in self:
            order.hall_ids = order._ss_hall_products()

    def _inverse_ss_hall_ids(self):
        """Write the picked halls onto the order as rental lines.

        ⚠⚠⚠ The line is created WITHOUT a price_unit on purpose. Odoo then computes it from
        the order's pricelist, which is the only thing that keeps halls 3+4 at 14,000 rather
        than 28,000 — that pair price exists solely as a 0.00 product.pricing row on hall 4 in
        the wedding pricelists. Never seed this from product.list_price. test_no_double_charging
        and test_hall_picker_uses_pricelist are the guards.
        """
        for order in self:
            current = order._ss_hall_products()
            to_add = order.hall_ids - current
            to_remove = current - order.hall_ids
            if not to_add and not to_remove:
                continue
            order._ss_check_lines_editable()
            commands = [
                Command.delete(line.id)
                for line in order.order_line.filtered(
                    lambda line: line.is_rental and line.product_id in to_remove)
            ]
            commands += [
                Command.create({
                    'product_id': hall.id, 'product_uom_qty': 1, 'is_rental': True,
                })
                for hall in to_add
            ]
            order.order_line = commands

    @api.depends('order_line.product_id')
    def _compute_ss_appendix_items(self):
        for order in self:
            sold = set(order.order_line.product_id.product_tmpl_id.mapped('ss_appendix_item'))
            for item_key, _label in APPENDIX_ITEMS:
                order[f'appendix_{item_key}'] = item_key in sold

    def _inverse_ss_appendix_items(self):
        for order in self:
            for item_key, label in APPENDIX_ITEMS:
                order._ss_sync_appendix_line(item_key, label, order[f'appendix_{item_key}'])

    def _ss_sync_appendix_line(self, item_key, label, wanted):
        """Add or remove the service that sells one appendix item.

        Priced by the pricelist for the same reason as the halls: the line carries no
        price_unit and Odoo computes it.
        """
        self.ensure_one()
        lines = self.order_line.filtered(
            lambda line: line.product_id.product_tmpl_id.ss_appendix_item == item_key)
        if bool(lines) == bool(wanted):
            return
        self._ss_check_lines_editable()
        if not wanted:
            self.order_line = [Command.delete(line.id) for line in lines]
            return
        product = self.env['product.product'].search(
            [('product_tmpl_id.ss_appendix_item', '=', item_key)], limit=1)
        if not product:
            # Silently leaving the box ticked would be a lie: the field is computed from the
            # lines, so it would flip back to unticked on the next read.
            raise UserError(self.env._(
                "لا توجد خدمة مرتبطة بالبند «%(label)s».\n"
                "افتح الخدمة المطلوبة وحدّد «بند الملحق التشغيلي» عليها أولاً.\n\n"
                "No service product is tagged with this appendix item. Set «بند الملحق "
                "التشغيلي» on the service that sells it, then tick the box again.",
                label=label))
        self.order_line = [Command.create({'product_id': product.id, 'product_uom_qty': 1})]

    def action_ss_print_contracts(self):
        """Print every contract type selected on this booking, as one PDF."""
        self.ensure_one()
        reports = self.contract_type_ids.report_id
        if not reports:
            raise UserError(self.env._(
                "اختر «نوع العقد» أولاً في تبويب «الحجز».\n\n"
                "No contract type is selected on this booking."))
        if len(reports) == 1:
            return reports.report_action(self)
        streams = [
            report._render_qweb_pdf(report.report_name, self.ids)[0]
            for report in reports
        ]
        attachment = self.env['ir.attachment'].create({
            'name': f"عقود - {self.name}.pdf",
            'type': 'binary',
            'datas': base64.b64encode(merge_pdf(streams)),
            'mimetype': 'application/pdf',
            'res_model': self._name,
            'res_id': self.id,
        })
        return {
            'type': 'ir.actions.act_url',
            'url': f'/web/content/{attachment.id}?download=true',
            'target': 'self',
        }

    # ------------------------------------------------------------------ helpers
    def _ss_hall_products(self):
        """The physical halls this booking occupies.

        A wedding holds TWO of them — hall 3 and hall 4 — on one order, which is what lets
        every hall be protected, scheduled and counted separately (spec §3.5).

        A HALL is a rental product that has a capacity. That is what makes these rules apply
        to Seven Stars' four halls and to nothing else: an ordinary rental product is not
        exclusive — Odoo Rental will happily rent two of the same projector at once — so
        applying an availability constraint to every rental line would be wrong, and was.
        Measured: before this scoping, CON-01 refused a standard sale_renting test booking
        for a "Projector" and broke two upstream tests.
        """
        self.ensure_one()
        rental_lines = self.order_line.filtered(lambda line: line.is_rental and line.product_id)
        return rental_lines.product_id.filtered(
            lambda product: product.product_tmpl_id.hall_capacity > 0)

    def _ss_is_hall_booking(self):
        """True for a Seven Stars hall booking, false for any other rental order."""
        self.ensure_one()
        return bool(self.is_rental_order and self._ss_hall_products())

    def _ss_envelope(self, hall, extra=timedelta()):
        """The window this booking really occupies the hall for: the event plus the hall's
        own preparation and cleanup time, plus any configured same-day gap.

        Nothing here is invented — prep_time and cleanup_time are the PRD's 4 and 5 hours,
        and `extra` is zero until the client decides PRD §22 item 6 (spec §8).
        """
        self.ensure_one()
        template = hall.product_tmpl_id
        return (
            self.rental_start_date - timedelta(hours=template.prep_time) - extra,
            self.rental_return_date + timedelta(hours=template.cleanup_time) + extra,
        )

    def _ss_is_live_booking(self):
        """A booking that still holds its halls.

        CON-01 blocks against ALL non-cancelled bookings, drafts included: a tentative hold
        on an already-held hall must fail. Proven and intended (spec §12).
        """
        self.ensure_one()
        return (
            self.is_rental_order
            and self.state != 'cancel'
            and self.booking_state != 'cancelled'
            and self.rental_start_date
            and self.rental_return_date
        )

    # --------------------------------------------------- Phase 6, historical import
    def _ss_migration_bypass_active(self):
        """True only inside a controlled historical import run.

        TWO conditions, both required: the explicit context flag AND a management user.
        The flag alone would be worthless, because context travels from the client on every
        RPC call — an ordinary user could otherwise switch availability checking off simply
        by asking for it. Proven by test_migration.py, which also proves CON-01 goes back to
        refusing overlaps the moment the run is over.
        """
        if not self.env.context.get(SS_MIGRATION_CONTEXT_KEY):
            return False
        if not self.env.user.has_group('seven_stars_rental.group_ss_manager'):
            _logger.warning(
                "Seven Stars: %s was passed by %s, who is not management. CON-01 stays on.",
                SS_MIGRATION_CONTEXT_KEY, self.env.user.login)
            return False
        return True

    @api.model
    def ss_find_import_conflicts(self, rows):
        """Audit source data for the overlaps CON-01 would refuse — BEFORE importing.

        `rows` are dicts with `ref`, `hall`, `start`, `end` and optional `prep`/`cleanup`
        (hours, defaulting to the PRD's 4 and 5). Returns one entry per clashing pair, so
        the conflict list can be taken to the client and cleaned or approved. Each pair is
        either bad source data to correct or a genuine past event the client must confirm;
        it is not something to bypass because the import is inconvenient.

        The comparison is the same half-open envelope rule CON-01 itself uses, so the audit
        cannot disagree with the constraint.
        """
        by_hall = {}
        for row in rows:
            start = fields.Datetime.to_datetime(row['start'])
            end = fields.Datetime.to_datetime(row['end'])
            prep = timedelta(hours=float(row.get('prep', 4.0)))
            cleanup = timedelta(hours=float(row.get('cleanup', 5.0)))
            by_hall.setdefault(row['hall'], []).append(
                (row['ref'], start - prep, end + cleanup, start, end))

        conflicts = []
        for hall, entries in by_hall.items():
            entries.sort(key=lambda entry: entry[1])
            for i, left in enumerate(entries):
                for right in entries[i + 1:]:
                    if right[1] >= left[2]:
                        break            # sorted by envelope start: nothing later can clash
                    if left[1] < right[2] and right[1] < left[2]:
                        conflicts.append({
                            'hall': hall,
                            'refs': (left[0], right[0]),
                            'windows': ((left[3], left[4]), (right[3], right[4])),
                            'envelopes': ((left[1], left[2]), (right[1], right[2])),
                        })
        return conflicts

    # ------------------------------------------------------------------- CON-01
    @api.constrains('rental_start_date', 'rental_return_date', 'order_line',
                    'state', 'booking_state')
    def _check_hall_availability(self):
        if self._ss_migration_bypass_active():
            _logger.warning(
                "Seven Stars: CON-01 stood down for a historical import by %s (%s records). "
                "This is expected only during a migration run.",
                self.env.user.login, len(self))
            return

        gap = get_optional_float(self.env, SAME_DAY_GAP_KEY)
        # The gap widens the envelope of the booking being checked, once — not both sides,
        # which would silently require twice the separation the client asked for.
        extra = timedelta(hours=gap) if gap is not None else timedelta()

        for order in self:
            if not order._ss_is_live_booking():
                continue
            for hall in order._ss_hall_products():
                mine_start, mine_end = order._ss_envelope(hall, extra)
                template = hall.product_tmpl_id
                # Coarse pre-filter. The other booking's envelope is widened by the SAME
                # hall's buffers, so this pad can never exclude a real clash.
                pad = timedelta(hours=template.prep_time + template.cleanup_time) + extra
                candidates = self.search([
                    ('id', '!=', order.id or 0),
                    ('is_rental_order', '=', True),
                    ('state', '!=', 'cancel'),
                    ('booking_state', '!=', 'cancelled'),
                    ('order_line.product_id', '=', hall.id),
                    ('rental_start_date', '<', mine_end + pad),
                    ('rental_return_date', '>', mine_start - pad),
                ])
                for other in candidates:
                    if hall not in other._ss_hall_products():
                        continue
                    other_start, other_end = other._ss_envelope(hall)
                    # Half-open interval: one booking may end exactly where the next begins.
                    if mine_start < other_end and other_start < mine_end:
                        raise ValidationError(self.env._(
                            "القاعة «%(hall)s» غير متاحة في هذا الوقت.\n"
                            "يوجد حجز آخر: %(other)s — %(customer)s\n"
                            "من %(other_start)s إلى %(other_end)s "
                            "(شاملاً وقت التجهيز والتنظيف).\n\n"
                            "Hall '%(hall)s' is not available then. It is held by booking "
                            "%(other)s for %(customer)s, whose occupied window including "
                            "preparation and cleanup runs %(other_start)s to %(other_end)s.",
                            hall=hall.display_name,
                            other=other.display_name,
                            customer=other.partner_id.display_name,
                            other_start=fields.Datetime.to_string(other_start),
                            other_end=fields.Datetime.to_string(other_end),
                        ))

    # ------------------------------------------------------------ CON-03, CON-04
    def _ss_check_deposit_before_confirm(self):
        """CON-03 — a booking is confirmed once enough money has actually arrived.

        The gate asks whether `collected_amount` has reached the agreed deposit. There is no
        "is this row the deposit?" flag and none is needed: a deposit is an ordinary payment
        row, and the question is only ever how much has been received (spec §6.1).

        The authorised management exception is a branch INSIDE the rule, not a later patch.
        The client confirms bookings she takes herself before any money arrives
        («فقط في حالات حجز من طرف سيدة الإدارة فقط», spec §23.3 G3). The waiver is written to
        the chatter, which already records who confirmed and when — no extra field.
        """
        self.ensure_one()
        if self.currency_id.compare_amounts(
                self.collected_amount, self.required_deposit_amount) >= 0:
            return
        if self.env.user.has_group('seven_stars_rental.group_ss_manager'):
            self.message_post(body=self.env._(
                "تم تأكيد الحجز دون استلام العربون المطلوب (%(required)s) — استثناء إداري. "
                "المبلغ المستلم حتى الآن: %(collected)s."
                "<br/>Confirmed without the required deposit under the management exception.",
                required=self.required_deposit_amount,
                collected=self.collected_amount,
            ))
            return
        raise ValidationError(self.env._(
            "لا يمكن تأكيد الحجز قبل استلام العربون المطلوب.\n"
            "العربون المطلوب: %(required)s\nالمبلغ المستلم: %(collected)s\n"
            "سجّل الدفعة في تبويب «الدفعات» ثم أكّد الحجز.\n\n"
            "This booking cannot be confirmed before the agreed deposit has been received "
            "(required %(required)s, received %(collected)s). Record the payment in the "
            "Payments tab first. Management may confirm without it.",
            required=self.required_deposit_amount,
            collected=self.collected_amount,
        ))

    def _ss_check_balance_before_close(self):
        """CON-04 — a booking is not closed while money is still owed."""
        self.ensure_one()
        if not self.currency_id.is_zero(self.outstanding_amount):
            raise ValidationError(self.env._(
                "لا يمكن إغلاق الحجز والحساب غير مصفّر.\n"
                "الإجمالي: %(total)s\nالمدفوع: %(collected)s\nالمتبقي: %(outstanding)s\n\n"
                "This booking still has an outstanding balance of %(outstanding)s and "
                "cannot be closed.",
                total=self.amount_total,
                collected=self.collected_amount,
                outstanding=self.outstanding_amount,
            ))

    # ------------------------------------------------------- the 7 custom buttons
    # Eight states minus `draft`, which is where a booking is created, leaves exactly seven
    # transitions (spec §9.1). Nothing else here is custom: Print, the standard confirm and
    # the chatter are all reused as they are.
    def action_hold_tentative(self):
        """BTN-01 — حجز مبدئي. CON-01 has already refused the hall if it was taken."""
        self.booking_state = 'tentative'
        return True

    def action_await_deposit(self):
        """BTN-02 — انتظار العربون وتوقيع العقد."""
        self.booking_state = 'awaiting'
        return True

    def action_confirm_booking(self):
        """BTN-03 — تأكيد الحجز, guarded by CON-03."""
        for order in self:
            order._ss_check_deposit_before_confirm()
            order.booking_state = 'confirmed'
            if order.state in ('draft', 'sent'):
                order.action_confirm()
            # PRD steps 11 and 13. Standard mail.activity — no cron, no automated action,
            # no server action anywhere in this addon (spec §13).
            order._ss_schedule_reminders()
            order._ss_invoice_booking()
        return True

    # ------------------------------------------------------------------ accounting (§1.2)
    def _ss_invoice_booking(self):
        """Jamal, 2026-09-23 — «بعد تغيير الحالة الى مؤكد، فوترة اوتوماتيكية على المحاسبة».

        The WHOLE booking is invoiced, not a down payment: the customer's receivable must
        show what the contract is worth, which is what «الرصيد/الذمة» means. The deposit was
        taken before this invoice existed, so it is sitting as an unreconciled credit on the
        customer — _ss_reconcile_payments settles it against this invoice immediately, which
        is «والدفعات التي تم انشاؤها يتم تسويتها من الفاتورة المصدرة على العقد».

        Runs sudo because the clerk who confirms a booking has no accounting groups by
        design; the permission question was already answered by CON-03 above.
        """
        invoices = self.env['account.move']
        for order in self:
            if not order._ss_is_hall_booking():
                continue
            order_sudo = order.sudo()
            invoice = order_sudo.invoice_ids.filtered(lambda move: move.state != 'cancel')
            if not invoice:
                if not any(order_sudo.order_line.mapped('qty_to_invoice')):
                    continue
                invoice = order_sudo._create_invoices()
            invoice.filtered(lambda move: move.state == 'draft').action_post()
            order_sudo._ss_reconcile_payments()
            invoices |= invoice
        return invoices

    def _ss_reconcile_payments(self):
        """Settle every posted payment on this booking against its invoice."""
        self.ensure_one()
        order = self.sudo()
        invoices = order.invoice_ids.filtered(
            lambda move: move.state == 'posted' and move.move_type == 'out_invoice')
        payments = order.payment_ids.filtered(
            lambda payment: payment.state in self.SS_RECEIVED_STATES)
        if not invoices or not payments:
            return

        def open_receivables(moves):
            return moves.line_ids.filtered(
                lambda line: line.account_id.account_type == 'asset_receivable'
                and not line.reconciled)

        lines = open_receivables(invoices) | open_receivables(payments.move_id)
        # Both sides must be present, or reconcile() would pointlessly match an invoice
        # against itself.
        if len(lines.mapped('move_id')) > 1:
            lines.reconcile()

    def action_mark_ready(self):
        """BTN-04 — جاهز للمناسبة, guarded by the operational appendix (spec §9.1).

        The guard is deliberately the weakest defensible one: the appendix must have been
        STARTED, which means its own anchor field — the event date — is filled in. The client
        never defined which of the fifteen items must be present for the appendix to count as
        complete, and enforcing all fifteen would block real work on a guess. Recorded as an
        open client question; tightening it later is a one-line change here.
        """
        for order in self:
            if not order.appendix_event_date:
                raise ValidationError(self.env._(
                    "لا يمكن تعليم الحجز «جاهز للمناسبة» قبل تعبئة الملحق التشغيلي.\n"
                    "ابدأ بتعبئة «تاريخ المناسبة» في تبويب «الملحق التشغيلي».\n\n"
                    "The operational appendix has not been started: fill in the event date "
                    "on the Operational Appendix tab first (spec §10, RPT-04)."))
            order.booking_state = 'ready'
        return True

    def action_postpone(self):
        """BTN-05 — تأجيل. The notice period is a Phase 4 rule; moving the dates re-runs
        CON-01 by itself, because the constraint watches them."""
        self.booking_state = 'postponed'
        return True

    def action_close_booking(self):
        """BTN-06 — إغلاق الحجز, guarded by CON-04.

        Closing also settles the rental quantities. Rental never leaves `pickup` unless
        quantities move, and "Late Pickup" is permanent while qty_delivered is below the
        ordered quantity (spec §3.2, runtime T5) — so a closed booking that never had its
        quantities set would read as late for ever.
        """
        if not self._ss_is_management():
            raise ValidationError(self.env._(
                "إغلاق الحجز من صلاحية الإدارة فقط (القسم 17).\n\n"
                "Closing a booking is reserved to management (PRD §17, spec §11)."))
        for order in self:
            order._ss_check_balance_before_close()
            for line in order.order_line.filtered('is_rental'):
                line.qty_delivered = line.product_uom_qty
                line.qty_returned = line.product_uom_qty
            order.booking_state = 'completed'
        return True

    def action_cancel_booking(self):
        """BTN-07 — إلغاء. Booking managers and above (spec §11); the cancellation notice
        rules are Phase 4.

        The view's groups= attribute only hides the button. A method is callable over RPC by
        anyone who can reach the record, so the right to cancel is checked here too.
        """
        if not self.env.user.has_group('seven_stars_rental.group_ss_booking_manager'):
            raise ValidationError(self.env._(
                "إلغاء الحجز من صلاحية مسؤول الحجوزات أو الإدارة فقط.\n\n"
                "Cancelling a booking is reserved to booking managers and management "
                "(PRD §17)."))
        # «إلغاء حجز مؤكد» is a narrower right than cancelling an enquiry: once the booking
        # is confirmed, only management may cancel it (PRD §17).
        if not self._ss_is_management():
            confirmed = self.filtered(lambda o: o.booking_state in self.SS_SIGNED_STATES)
            if confirmed:
                raise ValidationError(self.env._(
                    "إلغاء حجز مؤكد من صلاحية الإدارة فقط (القسم 17).\n"
                    "الحجوزات: %(orders)s\n\n"
                    "Cancelling a CONFIRMED booking is reserved to management (PRD §17); a "
                    "bookings manager may still cancel an enquiry or a tentative hold.",
                    orders=", ".join(confirmed.mapped('display_name'))))
        for order in self:
            order.booking_state = 'cancelled'
            if order.state != 'cancel':
                order.action_cancel()
        return True

    # ================================================================ PHASE 4
    # Seasonal pricing, the capacity check, the hall lock, and the two reminders.

    def _ss_pricelist_for_event(self):
        """The pricelist the event date and the chosen halls call for, or False.

        The client asked for this explicitly: «اختيار قائمة الأسعار تلقائياً من تاريخ المناسبة»
        (spec Appendix A item 14). Two discounts exist and both are −2000, taking a wedding
        from 14000 to 12000: winter, which the client defined as «(12 حتى 3)», and midweek.

        Rental lines bypass pricelist items entirely and product.pricing has no date field
        (spec §3.3), so no standard mechanism can do this — but the custom part is only
        *choosing* a pricelist. Every amount still comes from ordinary master data.
        """
        self.ensure_one()
        if not self.rental_start_date:
            return False

        halls = self._ss_hall_products()
        if not halls:
            return False

        reduced = self._ss_is_winter() or self._ss_is_midweek()
        is_pair = len(halls) > 1
        ref = self.env.ref
        if is_pair:
            return (ref('seven_stars_rental.pricelist_wedding_pair_reduced') if reduced
                    else ref('seven_stars_rental.pricelist_wedding_pair'))
        if self._ss_is_winter():
            return ref('seven_stars_rental.pricelist_winter')
        if self._ss_is_midweek():
            return ref('seven_stars_rental.pricelist_midweek')
        return ref('seven_stars_rental.pricelist_standard')

    def _ss_is_winter(self):
        """«خصم الشتاء (12 حتى 3)» — December, January, February, March."""
        self.ensure_one()
        return self.rental_start_date and self.rental_start_date.month in (12, 1, 2, 3)

    def _ss_is_midweek(self):
        """The midweek discount exists, but WHICH DAYS count was never stated.

        So it ships UNSET, exactly like the two deferred rules of spec §8: while the
        parameter is absent no booking is ever treated as midweek, and nothing is invented.
        Setting seven_stars_rental.midweek_weekdays to a comma-separated list of Python
        weekday numbers (Monday=0 … Sunday=6) turns it on with no code change.
        """
        self.ensure_one()
        raw = self.env['ir.config_parameter'].sudo().get_param(MIDWEEK_WEEKDAYS_KEY, default=None)
        if not raw or not self.rental_start_date:
            return False
        try:
            days = {int(part) for part in str(raw).split(',') if part.strip() != ''}
        except ValueError:
            return False
        return self.rental_start_date.weekday() in days

    @api.onchange('rental_start_date', 'order_line')
    def _onchange_ss_seasonal_pricelist(self):
        """Suggest the right pricelist as soon as the dates and halls are known.

        Getting this wrong costs the client 2,000 per booking in either direction, which is
        why it is offered rather than left to memory. It is an onchange, so the clerk sees
        the change before saving and can override it.
        """
        for order in self:
            if order.booking_state in ('completed', 'cancelled'):
                continue
            suggested = order._ss_pricelist_for_event()
            if suggested and order.pricelist_id != suggested:
                order.pricelist_id = suggested
                # Changing the pricelist does not reprice anything by itself:
                # _compute_price_unit depends on product_id, product_uom_id and
                # product_uom_qty (sale_order_line.py:590) and not on the pricelist. Without
                # this the clerk would see the right pricelist beside the wrong total.
                # The plain compute is used deliberately, NOT the forced one: a price a
                # manager typed by hand still wins.
                order.order_line._compute_price_unit()

    # ------------------------------------------------------------------- CON-05
    @api.constrains('guest_count', 'order_line', 'rental_start_date')
    def _check_ss_guest_capacity(self):
        """Guest count against the SUMMED capacity of every hall on the booking.

        Summing is the whole point: a wedding on halls 3+4 seats 600 + 550 = 1150, which is
        what dissolved PRD §22 item 11 — the real 800-guest case fits (spec §3.5, T28).

        The overrun tolerance itself is still UNSET, so while it is pending this rule
        enforces nothing at all. The count is always recorded and always visible.
        """
        tolerance = get_optional_float(self.env, GUEST_TOLERANCE_KEY)
        if tolerance is None:
            return
        for order in self:
            if not order._ss_is_live_booking() or not order.guest_count:
                continue
            capacity = sum(
                hall.product_tmpl_id.hall_capacity for hall in order._ss_hall_products())
            if not capacity:
                continue
            allowed = capacity * (1.0 + tolerance / 100.0)
            if order.guest_count > allowed:
                raise ValidationError(self.env._(
                    "عدد المعازيم (%(guests)s) يتجاوز سعة القاعات المحجوزة (%(capacity)s) "
                    "بأكثر من نسبة التجاوز المسموحة (%(tolerance).2f%%).\n\n"
                    "%(guests)s guests exceed the %(capacity)s combined capacity of the "
                    "booked halls by more than the configured %(tolerance).2f%% tolerance.",
                    guests=order.guest_count, capacity=capacity, tolerance=tolerance))

    # ------------------------------------------------------------------- CON-06
    # Changing any of these is «تغيير السعر» or «التعديل بعد التوقيع» once the contract has
    # been signed — management only (PRD §17, spec §23.1 item 14).
    SS_COMMERCIAL_FIELDS = (
        'rental_start_date', 'rental_return_date', 'order_line',
        'partner_id', 'pricelist_id', 'event_type',
    )
    SS_SIGNED_STATES = ('confirmed', 'ready', 'completed')

    def _ss_is_management(self):
        return self.env.user.has_group('seven_stars_rental.group_ss_manager')

    def _ss_check_management_only_write(self, vals):
        """PRD §17 — the clerk and the bookings manager alike are barred from editing a
        booking after its contract is signed, and from setting the agreed deposit.

        «الموافقة على التمديد» is covered by the same rule: extending a confirmed booking
        means moving rental_return_date, which is in the guarded list.
        """
        if self._ss_is_management():
            return
        if 'price_approved' in vals:
            raise ValidationError(self.env._(
                "اعتماد السعر من صلاحية الإدارة فقط (القسم 17).\n\n"
                "Approving a price is reserved to management (PRD §17)."))
        if 'required_deposit_amount' in vals:
            raise ValidationError(self.env._(
                "تحديد قيمة العربون المطلوب من صلاحية الإدارة فقط (القسم 17).\n\n"
                "Setting the agreed deposit is reserved to management (PRD §17)."))
        touched = set(vals) & set(self.SS_COMMERCIAL_FIELDS)
        if not touched:
            return
        signed = self.filtered(
            lambda o: o._ss_is_hall_booking() and o.booking_state in self.SS_SIGNED_STATES)
        if signed:
            raise ValidationError(self.env._(
                "لا يمكن تعديل حجز بعد توقيع العقد إلا بصلاحية الإدارة (القسم 17).\n"
                "الحجوزات: %(orders)s\nالحقول: %(fields)s\n\n"
                "Editing a booking after its contract has been signed — including extending "
                "it — is reserved to management (PRD §17).",
                orders=", ".join(signed.mapped('display_name')),
                fields=", ".join(sorted(touched))))

    def write(self, vals):
        """CON-06 — the hall cannot change after confirmation.

        «هل يمكن تغيير القاعة بعد التأكيد؟ لا» (spec §23.1). The dates may still move — that
        is what postponement is, and CON-01 re-checks them — but the hall itself is fixed.
        """
        self._ss_check_management_only_write(vals)

        locked = self.browse()
        halls_before = {}
        if 'order_line' in vals:
            locked = self.filtered(
                lambda o: o.booking_state in ('confirmed', 'ready', 'completed'))
            halls_before = {order.id: order._ss_hall_products() for order in locked}

        result = super().write(vals)

        for order in locked:
            if order._ss_hall_products() != halls_before[order.id]:
                raise ValidationError(self.env._(
                    "لا يمكن تغيير القاعة بعد تأكيد الحجز.\n"
                    "القاعات المؤكدة: %(halls)s\n\n"
                    "The hall cannot be changed once a booking is confirmed. Cancel the "
                    "booking and create a new one, or postpone it to another date.",
                    halls=", ".join(halls_before[order.id].mapped('display_name'))))
        return result

    # -------------------------------------------------------------- reminders
    def _ss_schedule_reminders(self):
        self.ensure_one()
        if not self.rental_start_date:
            return
        todo = self.env.ref('mail.mail_activity_data_todo', raise_if_not_found=False)
        if not todo:
            return
        existing = self.activity_ids.filtered(lambda a: a.activity_type_id == todo)
        summaries = existing.mapped('summary')

        # PRD step 11 — fill in the operational appendix, two weeks before the event.
        appendix_summary = "تعبئة الملحق التشغيلي"
        if appendix_summary not in summaries:
            self.activity_schedule(
                'mail.mail_activity_data_todo',
                date_deadline=(self.rental_start_date - timedelta(days=14)).date(),
                summary=appendix_summary,
                note=self.env._("املأ الملحق التشغيلي ليوم المناسبة قبل أسبوعين من الموعد."))

        # PRD step 13 — the مندوب walks the hall on the day.
        inspection_summary = "جولة المندوب قبل المناسبة"
        if inspection_summary not in summaries:
            self.activity_schedule(
                'mail.mail_activity_data_todo',
                date_deadline=self.rental_start_date.date(),
                summary=inspection_summary,
                note=self.env._("جولة تفقدية للقاعة قبل ساعتين من بداية المناسبة."))
