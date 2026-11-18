# ShopFlow development seeds

`seed.py` creates a complete demo dataset in `shopflow_dev`: one shop, three
counters, staff, categories, products (grocery + medicine with batch/expiry),
customers, loyalty accounts, a loyalty rule, and a week of finalized invoices
spread across all three counters, together with matching `stock_movements` and
`payments`. All seeded amounts are demo figures.

## Run

```powershell
cd apps\api
$env:PYTHONPATH='.'
.\.venv\Scripts\python.exe -m ..\..\database\seeds\seed.py
# or, from the repo root:
#   cd D:\Projects\shopflow
#   $env:PYTHONPATH='apps\api'
#   apps\api\.venv\Scripts\python.exe database\seeds\seed.py
```

Seeding is idempotent: it exits without changes if a `shops` row already exists.

## Rules embedded in the seed

* `Category.loyalty_eligible` controls which purchases earn points.
* Invoices earn `floor(total / 100)` points when a named customer is attached.
* `Payment.method` cycles through `cash`, `bkash`, `nagad` - the three methods
  the shop accepts.
* Medicine rows get a `medicine_details` row plus a `medicine_batches` row so
  the dashboard expiry alerts have real data.
