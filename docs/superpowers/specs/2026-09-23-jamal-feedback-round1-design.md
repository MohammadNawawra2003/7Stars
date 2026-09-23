# Seven Stars — Jamal feedback round 1

**Date:** 2026-09-23
**Source:** Jamal, seven annotated screenshots of staging `S00033` / `S00034` plus follow-up notes.
**Status:** items 1, 2, 7 settled · items 3, 4 designed, awaiting confirmation · items 5, 6 blocked.

---

## 0 · The scope reversal, stated plainly

The signed PRD §21 excludes accounting («خارج النطاق: برنامج المحاسبة الكامل»), and the client's
own requirements form answered «هل يجب إصدار فاتورة؟» → **لا**, with «نموذج الفاتورة» the single
attachment they did *not* request (TECH SPEC line 1053). The module was built on that evidence:
`account.payment` was rejected in writing (`models/seven_stars_payment.py:7`), the invoice buttons
are hidden for rental orders (`views/sale_order_views.xml:49-53`), and `tests/test_payments.py:143`
**asserts** `account.move` and `account.payment` stay at zero through a complete booking.

Jamal has reversed that decision:

> بعد تغيير الحالة الى مؤكد — فوترة اوتوماتيكية على المحاسبة، والدفعات التي تم انشاؤها يتم
> تسويتها من الفاتورة المصدرة على العقد

This document builds to that instruction. The contradiction with the signed PRD is recorded here
so it is not rediscovered later; it is a commercial matter for Al Shayeb and the client, not a
technical one. **This is not the full accounting programme of PRD §22 item 21** (hall costs,
expenses, supplier and staff wages, profit) — that remains out of scope.

---

## 1 · Accounting — invoice and payment *(settled)*

### Flow

| Moment | What happens |
|---|---|
| Any stage, including before confirmation | A payment is recorded as a posted `account.payment` (customer receipt). It lands on the partner ledger immediately, as an outstanding credit. |
| `booking_state → 'confirmed'` (BTN-03, `sale_order.py:356`) | A customer invoice for the whole booking is created **and posted**, automatically. |
| Immediately after posting | Every unreconciled customer credit on that partner belonging to this booking is reconciled against the invoice. |
| Closure (BTN-06, CON-04) | Requires the invoice residual to be zero. |

Full invoice at confirmation, **not** Odoo's down-payment wizard. A down-payment invoice puts only
the deposit on the customer's ذمة; Jamal asked for the balance to be visible, which requires the
whole contract value to be invoiced. This is also the shape that matches «الفاتورة المصدرة على
العقد» — one invoice per contract.

### Consequences to accept

- A posted invoice cannot be silently undone. Cancelling a confirmed booking now requires a credit
  note. This is correct accounting behaviour and must be explained to the clerks.
- Modifying the price after confirmation requires a credit note plus a new invoice.

### Model changes

`seven.stars.payment` is **deleted** — model, views, ACLs and menu. It is not mirrored into
`account.payment`. Two ledgers is the "duplicate payment truth" the technical specification
forbids (§6.1) and that the boss's rule 1 forbids (remove obsolete paths, no compatibility layer).

| Old | New |
|---|---|
| `seven.stars.payment.method` (`cash` / `transfer`) | the payment's journal — Cash / Bank |
| `seven.stars.payment.reference` | `account.payment.payment_reference` |
| negative amount = refund, manager-only | outbound customer payment, same manager-only guard |
| `payment_ids` (One2many) | the order's related `account.payment` records |

### Fields that must not change meaning

`outstanding_amount` keeps its formula — `amount_total - collected_amount`. `collected_amount`
becomes the sum of posted customer payments for the booking instead of the sum of ledger rows.
Keeping the formula means CON-03, CON-04 and all eight reports need no logic change.

`required_deposit_amount` stays a **term**, not money. Unchanged.

### Permissions

A hall clerk must not receive accounting groups. The booking's payment action runs `sudo()` behind
an explicit check on `seven_stars_rental.group_ss_*`.

⚠ `sudo()` grants no group membership — it preserves the uid. ⚠ `env.su` is True inside every
`@api.constrains` in Odoo 19; use `env.user` for any identity check there. Both traps already bit
this project once.

### Tax — decided, no toggle

Halls and services keep `taxes_id` **empty**. Every agreed total stays bit-identical, including the
load-bearing 14,000 for the halls 3+4 pair. A new test asserts the wedding-pair **invoice** total is
still 14,000.

**Rule for the future:** if VAT is ever switched on it must be a **price-included** tax. A
price-excluded 16% moves every price the client agreed to. No configuration is being built for
this — it is a data change on the products when and if the client's accountant asks for it.

### Tests

`tests/test_payments.py:130-145` inverts: it currently asserts zero accounting artefacts, and will
assert that the invoice and the payments **are** created, posted and reconciled.

### Pre-flight — blocking, must be confirmed on staging before any code

1. Is a chart of accounts installed on `mohammadnawawra2003-7stars-staging-38438116`? Without one,
   no invoice can post.
2. Is the company currency ILS?
3. The company country is currently **United States** — the contract header prints «الولايات
   المتحدة». Must become فلسطين.

Odoo.sh SSH port 22 is filtered from this machine, so these are browser checks. The implementation
itself is verified on the local rig `~/odoo19-test`.

---

## 2 · Operational appendix items → order lines *(settled)*

> عند اضافة فرقة الزفة او اي بند تشغيلي تحت الملحق التشغيلي يجب اضافتها على بند الطلب

Scope: the **four chargeable toggles** only.

| Field (`sale_order.py:103-106`) | Label |
|---|---|
| `appendix_promo_show` | عرض برومو |
| `appendix_dabke_women` | فرقة دبكة (النساء) |
| `appendix_zaffa_groom` | فرقة زفة للعريس |
| `appendix_zaffa_on_screens` | عرض الزفة على الشاشات |

The service products already exist — the S00033 contract prints `[SS-SRV-003] فرقة زفة للعريس` at
1,000.00. Only the link from the checkbox to the line is missing.

**Mechanism:** each boolean becomes `compute` + `inverse`, `store=False`.

- `compute` — true when an order line for that product exists.
- `inverse` — ticking adds the line, unticking removes it.

The order line is the single source of truth; the checkbox is a view of it. The printed appendix
keeps reading the boolean and needs no change.

**Pricing:** the line is added through the order's pricelist, never `product.list_price`.

**Guard:** toggling is blocked once the booking is invoiced, with a clear message.

The remaining appendix fields (`ضيافة`, `توزيعات`, `طاولات`, `أمن القاعة`, `استوديو التصوير`,
`نظام الإنارة`) stay descriptive `Char` fields. They carry counts and notes, and no price per unit
has ever been supplied.

---

## 3 · نوع العقد, multi-select *(designed, needs a decision)*

> اضافة نوع العقد - امكانية اختيار أكثر من نوع

Three contract reports exist (`report/report_actions.xml`):
`action_report_hall_contract` (زفاف) · `action_report_henna_contract` (حنة) ·
`action_report_lunch_contract` (خدمات غداء).

**Recommended:** `contract_report_ids = fields.Many2many('ir.actions.report')`, domained to those
three. No new model, no new data table, and adding a fourth contract type later is just adding a
report — which you would do anyway. A single print action prints whichever are selected.

**Alternative:** three Booleans. More boring to read, but every new contract type is a code change.

---

## 4 · Hall picker → order line at the hall's price *(designed, needs confirmation)*

> اختيار القاعة: عند الاختيار اضافتها على بند الطلب حسب القاعة السعر

Same `compute` + `inverse` mechanism as item 2, applied to a `Many2many` of hall products
(`product_tmpl_id.hall_capacity > 0`) on tab الحجز.

### ⚠⚠⚠ The landmine

The price **must** come from the order's pricelist, never `product.list_price`.

Halls 3+4 are **14,000 total, not 28,000**. That figure exists only as a `product.pricing` row on
the wedding pricelists — full price on hall 3, **0.00 on hall 4**. A picker that adds lines at the
product price bills double. `test_no_double_charging` is the guard; it stays green or the feature
does not ship.

### Bonus fix

S00033 prints «السعة الإجمالية للقاعات: 0» against 500 معازيم. The capacity constraint
(`sale_order.py:535`) returns early when the order has no hall line, so that booking has no capacity
checking at all. Making halls reachable from the booking form closes this hole.

---

## 5 · Report font *(blocked on a decision)*

> تغيير نوع الخط font

Needs either a named font from Jamal, or approval of a sample. Candidates: Cairo, Tajawal,
Noto Naskh Arabic.

⚠ The font must be genuinely available to the PDF renderer on Odoo.sh, not merely named in CSS, or
the PDF silently falls back and nothing changes.

---

## 6 · Review the contracts against the originals *(blocked — cannot start)*

> راجع العقود اذا صح بتطلع او لاء حسب المبعوت

**The originals are not on this machine.** `Odoo Work/Task 13/` contains only `Seven Stars Hall
PRD.pdf`, `نموذج جمع المتطلبات الاولية.pdf` (15 pages, scanned) and the two analysis documents.

The technical specification records that contract copies were attached and that confirming them is
PRD §22 item 16 — «تأكيد أن النسخ المرفقة نهائية» (line 1332) — and that the print template must
match the paper form (line 1357). The contract body wording currently ships as a **deliberate
placeholder**; it was never invented, precisely because the originals were never supplied.

**Needed:** the paper contracts, as photo, PDF or WhatsApp export.

---

## 7 · Identity fields on the booking form *(settled — trivial)*

> ضيفة العنوان ورقم الواتساب ورقم الهوية والشخص المسؤول عن المناسبة

**This is not a bug.** `models/res_partner.py` already defines `id_number`, `whatsapp` and
`responsible_person`, and `report/report_contract_templates.xml:63,69,73` binds all three
correctly. They printed blank on S00033 only because the customer record is empty — they live on a
partner tab that nobody visits while taking a booking.

**Fix:** surface the four values on the booking form as related fields, so the clerk fills them
while booking: العنوان · رقم واتساب · رقم الهوية · الشخص المسؤول عن المناسبة.

---

## 8 · Build order

Cheapest-correct first; accounting last because it is built on the order lines being right
(boss's rule 3 — grow in layers, never trade a working product for unfinished complexity).

| Layer | Items |
|---|---|
| 1 | 7 (identity fields) + company country → فلسطين |
| 2 | 2 (appendix toggles) + 4 (hall picker) |
| 3 | 3 (contract type) + 5 (font) |
| 4 | 1 (accounting) |
| — | 6 (contract review) whenever the originals arrive |

Pull item 1 forward if Jamal is blocked on it.

## 9 · Open questions

1. The original contracts, for item 6.
2. The font, for item 5.
3. Staging: chart of accounts installed, and company currency ILS?
4. Item 3 — Many2many on `ir.actions.report`, or three Booleans?
5. A payment dated in the future still counts as collected. S00033 shows المدفوع 4,500 /
   المتبقي 0.00 and state مكتمل, with two of its three payments dated **Sep 30** — a week ahead.
   A booking can therefore be closed on money that has not arrived. Demo artefact, or a hole to
   plug?
