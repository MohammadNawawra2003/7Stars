# Seven Stars Halls — Rental: implementation

Companion to the two analysis documents. They say what to build and why; this says what was
built, what it does, and what is still open.

- `SEVEN_STARS_RENTAL_TECHNICAL_SPECIFICATION.md` — the canonical specification (§1–§23)
- `IMPLEMENTATION_PLAN.md` — the phase plan

**Status: phases 0–7 implemented and verified locally; deployed to Odoo.sh staging.**

---

## 1 · Business purpose

Seven Stars Halls (قاعات سفن ستارز, Al Walaja — Bethlehem) rents four event halls. The system
has to take a booking, guarantee a hall is never double-booked, price it, record the money
that actually arrives, print the contracts and operational sheets in Arabic, and keep each
role to what PRD §17 allows.

The single hardest requirement, and the one most likely to be broken by a well-meaning
change: **a wedding books hall 3 AND hall 4 for 14,000 total — never 28,000.**

---

## 2 · Architecture

| | |
|---|---|
| Business addon | `seven_stars_rental` |
| Data addon | `seven_stars_rental_demo` — data only, empty `__init__.py` |
| Dependencies | `['sale_renting']` — one entry |
| Central model | `sale.order` with `is_rental_order = True`. No new central model. |
| Main screen | Rental ▸ Orders ▸ Orders, the standard form plus one inherit |
| Custom models | **1** (`seven.stars.payment`) |
| Custom fields | **41** |
| Custom buttons | **7** |
| Reports | **8** |
| Security groups | **4** |

Every count matches the specification. This extends Odoo Rental: it is not a replacement
rental engine, there is no generic booking framework, no custom accounting, no duplicate
payment truth and no abstraction layer.

**Accounting position.** The accounting modules are installed only because
`sale_renting → sale → account_payment → account` requires them. This workflow implements no
accounting: no customer invoice and no account payment is ever created, and the invoice
buttons are hidden on rental orders. Asserted by a test that walks a complete booking and
checks `account.move` and `account.payment` counts are unchanged.

### Models inherited

`sale.order` · `sale.order.line` · `product.template` · `res.partner` · `res.config.settings`

### The one custom model

`seven.stars.payment` — 6 fields (`order_id`, `date`, `amount`, `currency_id`, `method`,
`reference`). PRD §13 needs a payment statement and a per-payment receipt, so this is a
genuine one-to-many history. It is the **only** source of truth for money actually received.

---

## 3 · Fields (41)

| Model | Count | Fields |
|---|---|---|
| `sale.order` | 25 | `event_type`, `guest_count`, `booking_state`, `internal_note_men`, `internal_note_women`, `required_deposit_amount`, `payment_ids`, `collected_amount`, `outstanding_amount`, `price_approved`, and the 15 `appendix_*` fields |
| `product.template` | 3 | `hall_capacity`, `prep_time` (4h), `cleanup_time` (5h) |
| `res.partner` | 3 | `id_number`, `whatsapp`, `responsible_person` |
| `res.config.settings` | 4 | `same_day_gap_mode/_hours`, `guest_tolerance_mode/_percent` |
| `seven.stars.payment` | 6 | see above |

Names checked against standard Odoo before use: `amount_paid` already exists on `sale.order`
and means online payment-transaction total, so money received is `collected_amount`.
`res.partner.mobile` does not exist in Odoo 19, so WhatsApp is its own field. `id_number` is
deliberately not `vat`, which is the tax ID.

---

## 4 · Constraints

| ID | Rule | Where |
|---|---|---|
| CON-01 | No two non-cancelled bookings hold one hall with intersecting `[start − prep, end + cleanup]` windows. Keyed on the SET of halls, so a wedding protects both. | `sale.order` |
| CON-02 | Manual discount ≤ 5% unless the price is formally approved | `sale.order.line` |
| CON-03 | `collected_amount ≥ required_deposit_amount` before confirming, unless the user is management | `sale.order` |
| CON-04 | Cannot close while `outstanding_amount != 0` | `sale.order` |
| CON-05 | Guest count vs the **summed** capacity of every hall on the booking. Enforced only once the tolerance is configured. | `sale.order` |
| CON-06 | The hall cannot change after confirmation | `sale.order` |

**What counts as a hall.** A rental product with `hall_capacity > 0`. This matters: an
ordinary rental product is not exclusive — Odoo Rental will rent two of the same projector at
once — so these rules apply to Seven Stars' halls and to nothing else.

**CON-01 blocks drafts too.** A tentative hold on an already-held hall must fail.

---

## 5 · Buttons (7)

Eight states minus `draft`, where a booking is created, leaves exactly seven transitions.

| Button | Method | Transition | Guard |
|---|---|---|---|
| حجز مبدئي | `action_hold_tentative` | draft → tentative | CON-01 |
| انتظار العربون | `action_await_deposit` | tentative → awaiting | CON-01 |
| تأكيد الحجز | `action_confirm_booking` | awaiting → confirmed | CON-03; also confirms the standard order and schedules the two reminders |
| جاهز للمناسبة | `action_mark_ready` | confirmed → ready | the operational appendix must have been started |
| تأجيل | `action_postpone` | confirmed/ready → postponed | CON-01 re-runs on the new dates |
| إغلاق الحجز | `action_close_booking` | ready → completed | CON-04; management only; settles `qty_delivered`/`qty_returned` so the permanent Late flag clears |
| إلغاء الحجز | `action_cancel_booking` | any → cancelled | bookings manager for an enquiry, **management** for a confirmed booking |

Reused as they are and not counted: Print, the standard confirm, the chatter.

---

## 6 · Screens

No new screen exists. Everything is an inherit:

- **Booking form** — three tabs added (الحجز, الدفعات, الملحق التشغيلي), the `booking_state`
  statusbar, the seven buttons, and the two invoice buttons hidden on rental orders only.
- **Rental product form** — the three hall fields on the existing Rental tab.
- **Customer form** — a بيانات المناسبات tab.
- **Rental settings** — a Seven Stars block showing the two pending rules.
- **Schedule (gantt)** — standard, unchanged. A multi-hall wedding shows two correctly dated
  rows, the 0.00-priced women's hall included.

---

## 7 · Reports (8)

All `qweb-pdf`, A4 via `base.paperformat_euro`, through `web.external_layout`.

| ID | Document | Model |
|---|---|---|
| RPT-01 | عقد استئجار القاعة (زفاف) | `sale.order` |
| RPT-02 | عقد حنة | `sale.order` |
| RPT-03 | عقد خدمات غداء | `sale.order` |
| RPT-04 | الملحق التشغيلي | `sale.order` |
| RPT-05 | تأكيد الحجز | `sale.order` |
| RPT-06 | كشف الدفعات | `sale.order` |
| RPT-07 | إيصال الدفع | **`seven.stars.payment`** — a receipt is for one payment |
| RPT-08 | تفاصيل المناسبة للموظفين | `sale.order` |

The three contracts share one base layout with a variant block.

**Arabic.** Each report sets a template variable named `lang` before calling
`web.html_container`, which is what `web.report_layout` reads for `<body dir=...>`
(`web/views/report_templates.xml:29`), and passes `t-lang` on the inner call, which formats
the field values. `rtlcss` is irrelevant here — it governs the backend UI bundle only.

**⚠ The contract clause block is a marked placeholder.** Appendix A records the legal text as
«الشايب / النص من سفن ستارز»: Seven Stars owns the wording. No legal language has been
invented. To put the real text in, replace the body of
`seven_stars_rental.report_contract_terms_placeholder` — nothing else changes.

**Signatures** are printed lines for both parties, per the agreed answer to the open
e-signature question. `depends` stays a single entry.

---

## 8 · Security

| Group | Implies | May |
|---|---|---|
| Booking Clerk | `sales_team.group_sale_salesman` | create and edit own bookings, record payments |
| Accountant | `sales_team.group_sale_salesman` | read every booking, full rights on payments |
| Booking Manager | clerk + `group_sale_salesman_all_leads` | every booking, cancel an enquiry, reschedule |
| Management | booking manager + `sales_team.group_sale_manager` | prices, discounts, cancel a confirmed booking, refunds, post-signature edits, extensions, closing, confirm without the deposit |

Root and the Odoo administrator are members of Management.

**Record rules.** The clerk needs none: a salesman without "all leads" is already confined to
their own documents by `sale.sale_order_personal_rule`, so half the §17 matrix comes free.
Only the accountant gets a rule — read every booking, write none.

**Field restrictions.** `price_approved` uses a Python `groups=`, the only field-level ACL
Odoo 19 honours. `price_unit`, `discount` and `required_deposit_amount` use **write guards**
instead, because a `groups=` is read-and-write in one and a clerk who could not read a price
could not quote a hall.

**Two traps worth keeping in mind:**

- `uid 1` bypasses every ACL. A permission verified as admin is not verified.
- `env.su` is **True inside every `@api.constrains`**, whatever the real uid. It cannot be
  used to recognise an administrator; `env.user` can. An `env.su` check silently disabled the
  discount ceiling for everybody until this was measured.
- `sudo()` grants no group membership — it keeps the original uid — so the guards refuse it.

---

## 9 · Pricing

Rental lines bypass pricelist *items* entirely and `product.pricing` has no date field, so
seasonal pricing is expressed as `product.pricing` rows keyed on
`pricelist_id + product_template_id + recurrence_id`. There is **no pricing engine**; the only
custom part is *choosing* which pricelist an event date calls for.

| Pricelist | Applies |
|---|---|
| التسعيرة القياسية | default |
| الموسم الشتوي | December–March, single hall |
| أيام وسط الأسبوع | midweek, single hall |
| زفاف (قاعتا 3 + 4) | a booking holding both wedding halls |
| زفاف بسعر مخفّض | the pair in winter or midweek — one list, because the client gave both discounts the same −2000 |
| أهل البلد · عائلة المالك | chosen by hand; who qualifies is a human judgement |

The pricelist **records** live in the business addon because the code references them by XML
ID; the **prices** live in the demo addon, so installing the business addon assumes no amount.

**Halls and services carry no tax.** `outstanding_amount` derives from `amount_total` and every
printed document quotes it, so a default sales tax would silently make the balance, the
receipts and the contracts disagree with the agreed price.

---

## 10 · Hall 3 + Hall 4 — the wedding pair

**One booking. Two rental lines, one per physical hall. One price: 14,000.**

Both halls are real everywhere it matters — CON-01 protects each of them, the schedule shows
two rows, and the capacity check sums to 600 + 550 = **1150**, which is why the real
800-guest wedding fits.

The combined price is carried by `product.pricing` on the wedding pricelist: **the full price
on hall 3, 0.00 on hall 4.**

**Never type the zero on the line.** The standard *Update Prices* button recomputes with
`force_price_recomputation=True` (`sale/models/sale_order.py:1375`), which bypasses the
manual-price guard and restores 28,000. Because the price is derived from master data, the
same button reproduces it.

⚠ The 0.00 row belongs to the two wedding-pair pricelists **only**. On the general winter,
midweek or segment pricelists it would make the women's hall free whenever it is rented alone.

⚠ `tests/test_wedding_pair.py::test_no_double_charging` **must never be deleted.** It is the
only automated guard against the specific regression that brings 28,000 back.

---

## 11 · Payments

`required_deposit_amount` is a **term** — the deposit agreed for this booking. Nothing has
been received because it has a value.

Money received exists only as `seven.stars.payment` rows. `collected_amount` and
`outstanding_amount` are stored computes over those rows, so the two can never drift apart.
There is no "is this row the deposit?" flag and none is needed: the confirmation gate only
ever asks how much has arrived in total.

```
required_deposit_amount agreed          (a term; no money yet)
   → a seven.stars.payment row          (money arrives)
   → collected_amount recomputes
   → CON-03: collected_amount ≥ required_deposit_amount
   → the booking may be confirmed
```

**Management exception.** Management may confirm a booking whose deposit has not arrived —
the client does this for bookings she takes herself. The waiver is posted to the chatter,
which already records who confirmed. No extra field.

**Refunds** are negative payment rows, management only. One ledger stays the truth.

---

## 12 · Demo addon

Data only, no Python. Install it for a populated system; uninstall to remove the records.

4 halls · 10 services · 3 packages · 7 pricelists' worth of prices · 20 tagged customers ·
4 users, one per role · **32 bookings** across all eight states, single- and multi-hall, past
and future, every pricelist family, same-day pairs in different halls · **31 payment rows** ·
9 filled operational appendices.

No record overlaps another on the same hall — CON-01 would refuse to install the module
otherwise, which is the guarantee that keeps the dataset honest. Conflicts are exercised in
`tests/`, never shipped as data.

Demo records are easy to spot: customers carry the tag «بيانات تجريبية», products a `SS-`
code prefix.

**Three Odoo 19 behaviours shaped this addon:**

1. Demo data is **off by default** in Odoo 19; `--without-demo` is the documented default.
2. `load_data` forces `noupdate=True` on everything under a manifest `demo` key, so `-u`
   could never re-apply an edited record.
3. `load_demo` downgrades any failure to a *warning* and reports the module installed with no
   data — a broken file would pass CI silently.

So these files sit under `data`, not `demo`: no flag needed, failures are hard errors, and
`-u seven_stars_rental,seven_stars_rental_demo` re-applies an edit.

⚠ Every `order_line` list starts with `(5, 0, 0)`. `(0, 0, {...})` is a *create* command, so
without the clear each upgrade appended a second copy of every hall line — measured, 220
lines became 264 on one upgrade. A test fails if a booking ever holds the same hall twice.

---

## 13 · Configuration

- `base.ILS` activated; every pricelist is in shekels, which drives `sale.order.currency_id`.
  The company currency itself is a one-off manual step on a live database.
- Arabic (`ar_001`, direction RTL) activated with its translations.
- `wkhtmltopdf` must be on PATH; restart Odoo after installing it, its state is cached.

**Three rules ship UNSET** — not zero, not unlimited, not forbidden. An absent
`ir.config_parameter` is genuinely distinguishable from a stored `'0'`:

| Parameter | While unset |
|---|---|
| `seven_stars_rental.same_day_gap_hours` | true overlaps still blocked; no extra separation invented |
| `seven_stars_rental.guest_tolerance_percent` | guest count recorded and visible; nothing blocked |
| `seven_stars_rental.midweek_weekdays` | no booking is ever treated as midweek |

The first two have a settings screen showing the pending state instead of hiding it behind a
number. Choosing *Pending* deletes the parameter.

---

## 14 · Historical import

Audit first. `tools/import_historical_bookings.py` reads the source export and writes a
conflict list of every pair CON-01 would refuse, using the same envelope rule the constraint
uses so the two cannot disagree. Each pair is then corrected or approved with the client
before anything is imported.

The bypass is an explicit context flag that CON-01 honours **only when the user is also
management** — the flag alone is worthless by design, because context travels from the client
on every RPC call. Every use is logged, nothing is stored, no constraint is ever disabled, and
tests prove CON-01 is refusing overlaps again the moment the run ends.

⚠ `sale.order.line.start_date` and `return_date` are related, `store=False` fields and cannot
be imported. The booking period lives on the order.

---

## 15 · Files

46 files. `seven_stars_rental/`: 6 model files, 4 view files, 4 report files, 3 security
files, 2 data files, 9 test files, the icon and this document. `seven_stars_rental_demo/`:
7 data files and two manifests. `tools/`: the import script and a synthetic source file.

---

## 16 · Implementation decisions

| Decision | Why |
|---|---|
| Demo files under `data`, not `demo` | the three Odoo 19 behaviours in §12 |
| Pricelist records in the business addon, prices in the demo addon | the auto-selection code references them by XML ID, but no amount should be assumed on install |
| RPT-07 bound to `seven.stars.payment` | a receipt is for one payment; from the booking it would emit every receipt at once |
| Write guards rather than `groups=` on `price_unit` / `discount` | `groups=` is read-and-write in one; a clerk must still be able to read a price |
| A hall is a rental product with a capacity | ordinary rental products are not exclusive, and applying availability to all of them broke two upstream tests |
| One reduced pair pricelist for winter and midweek | the client gave both the same −2000; two lists with identical numbers would be two things to keep in step |
| `(5, 0, 0)` on every demo `order_line` | `(0, 0, …)` is a create command and these files are updatable |
| BTN-04 requires only that the appendix has been *started* | which of the fifteen items make it "complete" was never stated; enforcing all fifteen would block real work on a guess |

---

## 17 · Tests

`odoo-bin -d <db> -i seven_stars_rental,seven_stars_rental_demo --test-enable --test-tags /seven_stars_rental`

| File | Covers |
|---|---|
| `test_demo.py` | demo integrity, group hierarchy, Arabic RTL, no duplicated hall lines, the shipped wedding pair totalling 14,000 |
| `test_availability.py` | CON-01, both buffers, half-open adjacency, drafts blocking, cancelled releasing, rescheduling, the tri-state parameter |
| `test_wedding_pair.py` | the 8-method acceptance suite of spec §19.1 |
| `test_pricing.py` | hall pricing, packages, services, tax, whole-period billing |
| `test_payments.py` | balances, both CON-03 branches, CON-04, no accounting artefacts |
| `test_lifecycle.py` | the eight-state walk, closure clearing the Late flag, cancellation rights |
| `test_reports.py` | all eight render, Arabic RTL, both halls on the contract, the placeholder, signatures |
| `test_rules.py` | seasonal selection, the ceiling, summed capacity, the hall lock, the reminders |
| `test_security.py` | the §17 matrix, each cell from a real role session |
| `test_migration.py` | the import audit and the migration bypass |

---

## 18 · Known limitations

- **The midweek day range is unset**, so midweek auto-selection is inert until the client says
  which days. Winter (December–March) is explicit and active.
- **Contract legal text is a placeholder** until Seven Stars supplies its wording.
- **The real historical import has not run** — the client's Excel export is not available and
  the record volume is unstated. The tooling is built and proven on synthetic data.
- **A hall cannot host both a lunch and an evening event on the same day.** With 4h
  preparation and 5h cleanup the windows always intersect. This matches the PRD, where the
  same-day pair is lunch in halls 1/2 and the wedding in halls 3/4 — different halls.
- **A 5-hour evening bills a whole day** (`math.ceil` in `product_pricing._compute_price`).
  Not a bug; it is how the client's prices are quoted.
- **The company currency is not changed by the addon.** Pricelists are in ILS, which is what
  drives order currency; setting `res.company.currency_id` is a one-off manual step.
- **Booking `state` and `booking_state` are independent.** Demo bookings carry a booking state
  without a confirmed sale order; that is by design and was verified at runtime.

---

## 19 · Unresolved client decisions

| Item | Effect |
|---|---|
| PRD §22 item 7 — who may discount | Built on **management only**, the stronger evidence (two sources against one). **Phase 5 sign-off remains pending client confirmation.** |
| PRD §22 item 8 — is the 5% ceiling binding | One constant in `sale_order_line.py` |
| PRD §22 item 6 — same-day gap | Ships UNSET |
| PRD §22 item 11 — guest tolerance | Ships UNSET; the question largely dissolved once capacities are summed |
| Which days count as midweek | Ships UNSET |
| PRD §22 item 16 — contract wording | Placeholder block |
| Is hall 4 ever rented alone, and at what price | On a wedding pricelist it prices 0.00 by design; booked alone it must use an ordinary pricelist |
| What makes the operational appendix "complete" | Only the event date is enforced today |
| PRD §22 items 18/19 — migration volume | The real import is pending |
| PRD §22 item 21 — full accounting | Commercial decision; the PRD excludes it |
| WhatsApp / SMS notifications | Commercial decision; the PRD excludes them |

---

## 20 · Commits

| Phase | SHA | |
|---|---|---|
| 0 | `7bf2af6` | foundation, both addons, security groups, starter dataset |
| 1 | `dd4d0e9` | a hall cannot be double-booked |
| 2 | `0703937` | price, deposit, balance, closure |
| 3 | `839691b` | the eight documents, in Arabic |
| 4 | `24464e8` | the business rules bite |
| 5 | `2146cb4` | roles and permissions |
| 6 | `e2e2ac4` | historical import tooling |

Branch `staging` only. `main`, `stage` and `dev` were never touched, and nothing was
force-pushed.
