# Seven Stars Rental — demo script

The walkthrough recorded in
`Seven_Stars_Rental_Odoo19_Full_Workflow_Demo.mp4` (7:02), step by step, so the same demo can
be repeated by hand or re-recorded.

**Nothing in the video is staged.** Every screen is the implemented module running on Odoo 19
Enterprise with `seven_stars_rental` + `seven_stars_rental_demo` installed. A real Chromium
browser was driven through the workflow; no mock-ups, no edited results, no records created
outside Odoo.

| | |
|---|---|
| Video | `~/seven-stars-demo/Seven_Stars_Rental_Odoo19_Full_Workflow_Demo.mp4` |
| With burned-in captions | `…_Captioned.mp4` |
| Captions only | `…_Demo.srt` |
| Recorded against | local Odoo 19 Enterprise, database `ss_demo`, both addons installed |
| Sign-in | `admin` / `admin`; the four role users are `ss_clerk`, `ss_accountant`, `ss_booking_manager`, `ss_manager` |

Recorded locally rather than on Odoo.sh staging because SSH port 22 to the Odoo.sh host is
filtered from this machine, so the staging database could not be signed into or seeded. The
code is identical — the same commit is deployed to `staging`.

---

## The business cycle, screen by screen

| # | Video | Menu / screen | Action | Expected result | PRD |
|---|---|---|---|---|---|
| 1 | 0:10 | Apps | — | **قاعات سفن ستارز** is its own app, carrying the client's logo | §1 |
| 2 | 0:17 | قاعات سفن ستارز | open the menu bar | Bookings · Payments · Master data · Settings — the whole workflow in one place | §1 |
| 3 | 0:28 | ▸ الحجوزات ▸ العملاء | — | 20 customers | §2 |
| 4 | 0:36 | open أحمد محمود العمري | — | name, phone, city | §2 |
| 5 | 0:43 | tab بيانات المناسبات | — | **رقم الهوية · واتساب · الشخص المسؤول** — the three details the contracts need and the standard contact has not got | §2 |
| 6 | 0:49 | ▸ الحجوزات ▸ الحجوزات | — | every booking with its state | §3 |
| 7 | 0:57 | open **S00013** | — | a wedding booking | §3, §5 |
| 8 | 1:03 | tab الحجز | — | event type زفاف, guest count 950 | §5 |
| 9 | 1:09 | tab Other Info | — | the member of staff responsible | §2 |
| 10 | 1:16 | tab Order Lines | — | **TWO hall lines** — hall 3 AND hall 4 on one booking | §5 |
| 11 | 1:23 | same screen | — | hall 3 **14,000** · hall 4 **0.00** · **Total ₪14,000.00 — not 28,000** | §6 |
| 12 | 1:40 | ▸ البيانات الأساسية ▸ القاعات ▸ hall 3 ▸ Rental prices | — | the price per pricelist, held as master data | §6 |
| 13 | 1:52 | hall 4 ▸ Rental prices | — | **0.00 on the two WEDDING pricelists only**; its own price on every other list | §6 |
| 14 | 2:00 | — | — | the price is *derived*, not typed, which is why *Update Prices* reproduces it instead of doubling it | §6 |
| 15 | 2:08 | back to S00013 | — | — | §4 |
| 16 | 2:13 | ⚙ Actions ▸ Duplicate | duplicate the booking | same two halls, same evening | §4 |
| 17 | 2:21 | — | — | **CON-01 refuses it**, naming the hall, the clashing booking S00013 and the customer | §4 |
| 18 | 2:30 | — | — | the window quoted runs **11:00 → 01:00**: the event plus 4h preparation and 5h cleanup | §4 |
| 19 | 2:45 | open **S00019** | — | a WINTER wedding, same two halls | §6 |
| 20 | 2:52 | tab Order Lines | — | **Total ₪12,000 — not 24,000.** A seasonal pair price is a TOTAL | §6 |
| 21 | 3:03 | tab الدفعات | — | required deposit **5,000**, received **0.00** | §9 |
| 22 | 3:07 | — | — | the agreed deposit is a **term**; money received is only ever the rows beneath it | §9 |
| 23 | 3:19 | button **تأكيد الحجز** | click | management confirms **without** the deposit — the authorised exception | §9, §17 |
| 24 | 3:26 | chatter | — | the waiver is written into the chatter against whoever confirmed | §9 |
| 25 | 3:37 | Print ▸ عقد استئجار القاعة | — | the wedding contract, **Arabic right-to-left**, with both halls, the totals, the signature blocks and the marked placeholder for the client's own legal wording | §8 |
| 26 | 3:50 | Print ▸ تأكيد الحجز | — | the booking confirmation | §10 |
| 27 | 4:02 | Print ▸ الملحق التشغيلي | — | the operational appendix, **all fifteen items** | §11 |
| 28 | 4:15 | Print ▸ تفاصيل المناسبة | — | the staff sheet, with each hall's real occupied window | §12, §13 |
| 29 | 4:28 | Print ▸ كشف الدفعات | — | the payment statement, one line per payment | §13 |
| 30 | 4:46 | **S00008** ▸ tab الملحق التشغيلي | — | the same fifteen items, on the booking | §11 |
| 31 | 4:54 | tab الدفعات | — | fully paid: **outstanding 0.00** | §15 |
| 32 | 5:02 | button **إغلاق الحجز** | click | state moves to **مكتمل**; quantities settle so the permanent "Late" flag clears | §16 |
| 33 | 5:14 | **S00009** ▸ tab الدفعات | — | a booking that still owes 1,500 | §15 |
| 34 | 5:21 | button **إغلاق الحجز** | click | **CON-04 refuses** to close it while the balance is not zero | §16 |
| 35 | 5:31 | ▸ الدفعات ▸ الدفعات | — | every shekel received, in one ledger | §13 |
| 36 | 5:41 | ▸ الحجوزات ▸ جدول المناسبات | — | the schedule | §18 |
| 37 | 5:44 | — | — | **hall 3 and hall 4 are SEPARATE rows** — two real physical halls, each with its own bookings | §18 |
| 38 | 5:59 | ▸ البيانات الأساسية ▸ القاعات | — | the four halls | §5 |
| 39 | 6:08 | open hall 3 | — | capacity **600**, preparation **4h**, cleanup **5h** (hall 4 is 550 → **1150** combined) | §5 |
| 40 | 6:23 | sign out, sign in as `ss_clerk` | — | the same system as a booking clerk | §17, §20 |
| 41 | 6:32 | app menu | — | a clerk sees bookings and payments — **no pricelists, no settings** | §17 |
| 42 | 6:37 | ▸ الحجوزات | — | she sees the bookings **she** took: the standard "own documents" rule | §17 |
| 43 | 6:49 | open a booking ▸ tab الدفعات | — | the agreed deposit is **read-only** for her | §17 |
| 44 | 6:57 | — | — | end | — |

---

## What the video deliberately does NOT claim

- **The contract's legal wording is a marked placeholder.** Seven Stars owns that text
  («الشايب / النص من سفن ستارز»); none has been invented.
- **Signatures are printed lines** for both parties, per the agreed answer to the open
  e-signature question — not an in-system e-signature.
- **Discount authority is shown as management-only**, which is the documented working
  assumption (two sources against one). Client sign-off on that row is still pending.
- **No accounting document is created anywhere.** `account.move` and `account.payment` stay
  at zero through the whole cycle; a test asserts it.

## Re-recording it

```bash
# 1 · a clean demo database — the walkthrough mutates data, so always start fresh
dropdb -h ~/odoo19-test/pgsock -p 5456 ss_demo
odoo-bin -d ss_demo -i seven_stars_rental,seven_stars_rental_demo   # + the usual addons-path
odoo-bin shell -d ss_demo --no-http < scratchpad/setup_demo.py      # sets the demo passwords

# 2 · serve it
odoo-bin -d ss_demo --http-port=8090 --http-interface=127.0.0.1 --workers=0

# 3 · drive and record (Playwright lives in ~/odoo19-test/venv)
~/odoo19-test/venv/bin/python3 scratchpad/record_demo.py

# 4 · webm -> mp4
ffmpeg -i video_raw/*.webm -vf "fps=25,format=yuv420p" -c:v libx264 -crf 23 \
       -movflags +faststart Seven_Stars_Rental_Odoo19_Full_Workflow_Demo.mp4
```

Two traps worth keeping:

- **`wait_until="networkidle"` never fires in Odoo** — the web client holds a websocket open
  for ever. Wait on a selector instead.
- **A statusbar button fires a server call and the form re-renders**, detaching the element;
  Playwright's post-click stability check then retries until it times out even though the
  click landed. Click with `force=True` after waiting for visibility, then wait for the
  resulting state.
