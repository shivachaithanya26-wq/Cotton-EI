# Cotton Business Manager (Django)

A small end-to-end Django app for a cotton purchase/sales business:
live/manual pricing, bag-wise purchase intake with automatic
cash-cutting and tare deductions, sales tracking, extra-cost tracking
(labour, transport, shop rent), and daily/monthly/custom profit reports.

## 1. Setup

```bash
python3 -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -r requirements.txt

python manage.py migrate
python manage.py createsuperuser  # create your login
python manage.py runserver
```

Visit `http://127.0.0.1:8000/` and log in. Visit `/admin/` for the
Django admin (useful for bulk data entry / fixing records).

Before your first purchase, create at least one **CashCuttingRule** and
one **TareRule** in `/admin/` (or they default to 5% and 0.5 kg/bag —
see `core/services.py`).

## 2. How the requirements map to the code

| # | Requirement | Where it lives |
|---|---|---|
| 1 | Live/manual cotton price | `core.models.LivePrice`, `core/views.set_today_price`, `core/management/commands/fetch_live_price.py` |
| 2 | Daily purchase totals | `core.services.purchase_totals`, `/reports/daily/` |
| 3 | Monthly / custom range totals | `core.services.profit_report`, `/reports/monthly/`, `/reports/custom/` |
| 4 | Manual data entry + price lookup + purchase formula | `core.views.purchase_create`, `core.services.calculate_purchase` |
| 5 | Sales, daily/monthly | `core.models.Sale`, `/sales/`, `/reports/...` |
| 6 | Extra costs: cash-while-buying, shop rent, vehicle rent, labour | `core.models.Expense` (category choices) |
| 7 | Profit = Sales − Purchases − Expenses | `core.services.profit_report` |
| 8 | KG / Quintal unit toggle | `unit` field on `Purchase`/`Sale`, conversion in `calculate_purchase` |
| 9 | Bag-by-bag entry, tare + cash-cutting formula | `core.models.PurchaseBag`, `core.services.calculate_purchase` |

## 3. The purchase formula (requirement #9), worked example

Say you buy from a client in 1 bag of 300 kg (= 3 quintal), live price
₹7,000/quintal, cash-cutting rule 5%, tare rule 0 kg/bag:

```
gross_weight   = 300 kg
net_weight     = gross_weight − (tare_per_bag × num_bags)
gross_amount   = (net_weight ÷ 100) × price_per_quintal
               = 3 × 7000 = ₹21,000
cash_cutting   = gross_amount × cash_cutting_rate%
               = 21,000 × 5% = ₹1,050
net_payable    = gross_amount − cash_cutting
               = 21,000 − 1,050 = ₹19,950   <-- paid to the client
```

Both the cash-cutting **rate** and the tare **weight per bag** are
stored as editable rules (`CashCuttingRule`, `TareRule`) rather than
hardcoded, since these numbers tend to change by season/negotiation.
Bags are entered one at a time via a formset (`PurchaseBagFormSet`) —
each bag row is summed, then the tare is subtracted, before pricing.

If `unit = KG` instead of `QTL`, the same net weight is priced at
`price_per_quintal / 100` per kg — the underlying price is always
stored per quintal so nothing gets inconsistent between units.

## 4. Live price feed (requirement #1)

Real cotton price sources (MCX, NCDEX, a regional mandi board, a paid
data API, etc.) each have different endpoints/HTML that change over
time, and I can't verify any specific scraper still works from this
environment — so `core/services.py` ships with a **pluggable** fetch
function (`fetch_live_price_from_source`) that returns `None` by
default (`FETCH_STRATEGY = "manual"`). To wire it up:

1. Pick a source and confirm you're allowed to pull data from it.
2. Fill in `fetch_live_price_from_source()` with a `requests` call
   (a skeleton with `BeautifulSoup` is already commented in there).
3. Set `FETCH_STRATEGY = "http"`.
4. Schedule the command daily:

```bash
# crontab -e
0 9 * * * /path/to/venv/bin/python /path/to/manage.py fetch_live_price
```

If the fetch fails or you never wire one up, use **Set Price** in the
nav bar (or `/admin/`) to enter the day's price manually — purchases
will use whichever `LivePrice` you pick, or a manual override typed
directly into the purchase form.

## 5. Project layout

```
cotton_project/       Django settings/urls
core/
  models.py            Client, Buyer, LivePrice, CashCuttingRule, TareRule,
                        Purchase, PurchaseBag, Sale, Expense
  services.py           all business-formula + reporting logic (audit this file first)
  forms.py               PurchaseForm + PurchaseBagFormSet (bag-by-bag entry)
  views.py, urls.py       dashboard, CRUD, reports
  admin.py                 full admin for bulk entry / corrections
  management/commands/fetch_live_price.py
  templates/core/            Bootstrap-based UI
```

## 6. Known simplifications / next steps

- Auth is basic Django session login — add roles (e.g. accountant vs
  owner) if multiple people will use it.
- Sales are entered as a single quantity/price line; if you also need
  bag-wise entry on the sales side (e.g. selling to an industry by the
  bag), mirror `PurchaseBag` into a `SaleBag` model the same way.
- No PDF/print receipts yet — the `docx`/`pdf` generation could be
  added per-purchase if you want printable slips for clients.
- SQLite is fine for a single-shop setup; switch `DATABASES` in
  `settings.py` to Postgres/MySQL if multiple people write concurrently.
