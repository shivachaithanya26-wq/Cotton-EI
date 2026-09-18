"""
All business-formula logic lives here, in one place, so it's easy to
audit and change without touching views/templates.
"""
from decimal import ROUND_HALF_UP, Decimal

from django.db.models import Sum, Count
from django.utils import timezone

from .models import CashCuttingRule, Expense, LivePrice, Purchase, Sale, TareRule, Investment, GRADE_CHOICES, PurchaseBag

TWO_PLACES = Decimal("0.01")
THREE_PLACES = Decimal('0.001')


def to_quintal(weight_kg: Decimal) -> Decimal:
    return weight_kg / Decimal("100")


def _resolve_tare_by_size(purchase: Purchase) -> dict:
    """
    Big and Small bags have different tare. For each size: a custom
    per-purchase override wins first, then the active TareRule for that
    size, then a hardcoded fallback (1.0 kg Big / 0.5 kg Small).
    """
    tare_by_size = {}
    size_defaults = {"BIG": Decimal("1.0"), "SMALL": Decimal("0.5")}
    custom_by_size = {"BIG": purchase.custom_tare_big_kg, "SMALL": purchase.custom_tare_small_kg}
    for size in ("BIG", "SMALL"):
        custom_value = custom_by_size[size]
        if custom_value is not None:
            tare_by_size[size] = Decimal(str(custom_value))
            continue
        rule = TareRule.active_default(bag_size=size)
        tare_by_size[size] = Decimal(str(rule.weight_per_bag_kg)) if rule else size_defaults[size]
    return tare_by_size


def calculate_purchase(purchase: Purchase) -> Purchase:
    """
    Implements requirement #9, extended for multiple cotton qualities in
    one purchase (Type A / B / C) AND two bag sizes (Big / Small), each
    with its own tare:

      1. Resolve the tare for Big bags and Small bags separately (custom
         override -> active TareRule for that size -> hardcoded default).
      2. Group the individually-weighed bags by grade.
      3. Within each grade, deduct each bag's OWN size-specific tare
         (bags of the same grade can still be a mix of Big and Small)
         -> net weight per grade.
      4. Convert each grade's net weight into the purchase's chosen unit
         and multiply by THAT grade's price -> gross amount per grade.
      5. Sum all grades' gross amounts -> total gross amount.
      6. Deduct ONE cash-cutting percentage from the total (not
         quality-dependent) -> net amount payable to the client.

    Worked example matching the spec: 3 quintal x Rs.7000 = Rs.21,000.
    5% cash cutting = Rs.1,050. Net payable = Rs.19,950.
    (That example only used Type A, Big bags, so it still matches exactly.)
    """
    bags = list(purchase.bags.all())
    gross_weight_kg = sum((Decimal(str(b.weight_kg)) for b in bags), Decimal("0"))
    num_bags = len(bags)

    tare_by_size = _resolve_tare_by_size(purchase)
    tare_weight_kg = sum((tare_by_size[b.bag_size] for b in bags), Decimal("0"))

    net_weight_kg = gross_weight_kg - tare_weight_kg
    if net_weight_kg < 0:
        net_weight_kg = Decimal("0")

    if purchase.live_price_id:
        price_type_a = Decimal(str(purchase.live_price.price_per_quintal))
    elif purchase.manual_price_per_quintal:
        price_type_a = Decimal(str(purchase.manual_price_per_quintal))
    else:
        price_type_a = Decimal("0")
    price_by_grade = {
        "A": price_type_a,
        "B": Decimal(str(purchase.price_type_b_per_quintal)) if purchase.price_type_b_per_quintal else Decimal("0"),
        "C": Decimal(str(purchase.price_type_c_per_quintal)) if purchase.price_type_c_per_quintal else Decimal("0"),
    }

    net_weight_by_grade = {"A": Decimal("0"), "B": Decimal("0"), "C": Decimal("0")}
    gross_amount_by_grade = {"A": Decimal("0"), "B": Decimal("0"), "C": Decimal("0")}
    gross_amount = Decimal("0")

    for grade in ("A", "B", "C"):
        grade_bags = [b for b in bags if b.grade == grade]
        if not grade_bags:
            continue
        grade_gross_weight_kg = sum((Decimal(str(b.weight_kg)) for b in grade_bags), Decimal("0"))
        grade_tare_kg = sum((tare_by_size[b.bag_size] for b in grade_bags), Decimal("0"))
        grade_net_weight_kg = grade_gross_weight_kg - grade_tare_kg
        if grade_net_weight_kg < 0:
            grade_net_weight_kg = Decimal("0")

        if purchase.unit == "QTL":
            grade_qty_in_unit = to_quintal(grade_net_weight_kg)
            price_per_unit = price_by_grade[grade]
        else:  # KG
            grade_qty_in_unit = grade_net_weight_kg
            price_per_unit = price_by_grade[grade] / Decimal("100")

        grade_gross_amount = (grade_qty_in_unit * price_per_unit).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)

        net_weight_by_grade[grade] = grade_net_weight_kg
        gross_amount_by_grade[grade] = grade_gross_amount
        gross_amount += grade_gross_amount

    cutting_rule = purchase.cash_cutting_rule or CashCuttingRule.active_default()
    if purchase.custom_cash_cutting_rate_percent is not None:
        cutting_rate = Decimal(str(purchase.custom_cash_cutting_rate_percent))
    elif cutting_rule:
        cutting_rate = Decimal(str(cutting_rule.rate_percent))
    else:
        cutting_rate = Decimal("5.00")
    cash_cutting_amount = (gross_amount * cutting_rate / Decimal("100")).quantize(
        TWO_PLACES, rounding=ROUND_HALF_UP
    )
    net_payable = gross_amount - cash_cutting_amount

    purchase.gross_weight_kg = gross_weight_kg
    purchase.num_bags = num_bags
    purchase.tare_weight_kg = tare_weight_kg
    purchase.net_weight_kg = net_weight_kg
    purchase.price_used_per_quintal = price_type_a
    purchase.gross_amount = gross_amount
    purchase.cash_cutting_amount = cash_cutting_amount
    purchase.net_payable = net_payable
    purchase.net_weight_type_a_kg = net_weight_by_grade["A"]
    purchase.net_weight_type_b_kg = net_weight_by_grade["B"]
    purchase.net_weight_type_c_kg = net_weight_by_grade["C"]
    purchase.gross_amount_type_a = gross_amount_by_grade["A"]
    purchase.gross_amount_type_b = gross_amount_by_grade["B"]
    purchase.gross_amount_type_c = gross_amount_by_grade["C"]
    if purchase.cash_cutting_rule_id is None:
        purchase.cash_cutting_rule = cutting_rule
    return purchase


# --------------------------------------------------------------------------
# Live price fetching (requirement #1). This is intentionally pluggable:
# cotton price sources (MCX, NCDEX, local mandi boards, data.gov.in
# Agmarknet, a private API you subscribe to, etc.) vary a lot by region
# and change their page structure/endpoints over time, so a hardcoded
# scraper here would be brittle and unverifiable from this environment.
# Point FETCH_STRATEGY at whichever source you choose, or leave it as
# 'manual' and enter the price yourself every day via /admin or the
# "Set Today's Price" form.
# --------------------------------------------------------------------------

FETCH_STRATEGY = "manual"  # change to "http" once you wire up a real source


def fetch_live_price_from_source() -> Decimal | None:
    """
    Replace the body of this function with a real request to your chosen
    price source. Example skeleton using `requests` + `BeautifulSoup`:

        import requests
        from bs4 import BeautifulSoup

        resp = requests.get("https://example-price-source/cotton", timeout=10)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        price_text = soup.select_one(".price-value").text  # adjust selector
        return Decimal(price_text.replace(",", "").strip())

    Return None if the source is unreachable/unparseable so the caller
    can fall back to the last manual entry instead of crashing.
    """
    if FETCH_STRATEGY != "http":
        return None
    try:
        # TODO: implement the real call described above.
        return None
    except Exception:
        return None


def get_or_create_today_price(manual_price: Decimal | None = None) -> LivePrice:
    """
    Requirement #1: get today's price, live if possible, else manual.
    Called by the 'fetch_live_price' management command or a view.
    """
    today = timezone.localdate()
    existing = LivePrice.objects.filter(date=today).order_by("-fetched_at").first()
    if existing:
        return existing

    fetched = fetch_live_price_from_source()
    if fetched is not None:
        return LivePrice.objects.create(date=today, price_per_quintal=fetched, source="LIVE")

    if manual_price is not None:
        return LivePrice.objects.create(date=today, price_per_quintal=manual_price, source="MANUAL")

    # Fall back to yesterday's price if nothing else is available.
    last = LivePrice.objects.order_by("-date", "-fetched_at").first()
    if last:
        return LivePrice.objects.create(date=today, price_per_quintal=last.price_per_quintal, source="MANUAL")

    raise ValueError("No live price available and no manual price supplied.")


# --------------------------------------------------------------------------
# Reporting (requirements #2, #3, #5, #7)
# --------------------------------------------------------------------------

def purchase_totals(date_from, date_to):
    qs = Purchase.objects.filter(date__gte=date_from, date__lte=date_to)
    agg = qs.aggregate(
        total_gross=Sum("gross_amount"),
        total_cash_cutting=Sum("cash_cutting_amount"),
        total_net_payable=Sum("net_payable"),
        total_net_weight_kg=Sum("net_weight_kg"),
        total_bags=Sum("num_bags"),
    )
    # Sum() over a DecimalField can come back with SQLite-driven trailing
    # noise digits (e.g. "54363.7400000000") -- quantize everything to the
    # field's real precision so totals always display cleanly.
    money_keys = {"total_gross", "total_cash_cutting", "total_net_payable"}
    result = {}
    for k, v in agg.items():
        v = v or Decimal("0")
        result[k] = v.quantize(TWO_PLACES) if k in money_keys else (
            v.quantize(THREE_PLACES) if k == "total_net_weight_kg" else v
        )
    return result, qs

def stock_summary():
    """
    Running stock ledger: total kg ever purchased (net weight, after tare,
    across every quality) minus total kg ever sold. Sales can be recorded
    in either KG or QTL, so each sale's quantity is normalized to kg before
    subtracting, otherwise mixed units would silently misreport stock.
    This is a running total (never reset per day), same idea as
    investment_balance() -- whatever's left on hand simply carries forward.
    """
    total_purchased_kg = Purchase.objects.aggregate(t=Sum("net_weight_kg"))["t"] or Decimal("0")

    total_sold_kg = Decimal("0")
    for row in Sale.objects.values("unit").annotate(total=Sum("quantity")):
        qty_sum = row["total"] or Decimal("0")
        total_sold_kg += qty_sum * Decimal("100") if row["unit"] == "QTL" else qty_sum

    remaining_kg = total_purchased_kg - total_sold_kg
    return {
        "total_purchased_kg": total_purchased_kg.quantize(THREE_PLACES),
        "total_sold_kg": total_sold_kg.quantize(THREE_PLACES),
        "remaining_kg": remaining_kg.quantize(THREE_PLACES),
    }

def overall_totals():
    """
    All-time totals (no date filter), for the dashboard's "Total purchases
    and sales" card -- separate from stock_summary()'s kg-only ledger and
    separate from "Today"'s date-scoped figures.
    """
    stock = stock_summary()
    total_purchase_amount = (Purchase.objects.aggregate(t=Sum("net_payable"))["t"] or Decimal("0")).quantize(
        TWO_PLACES
    )
    total_sale_amount = (Sale.objects.aggregate(t=Sum("amount"))["t"] or Decimal("0")).quantize(TWO_PLACES)
    return {
        "total_purchase_amount": total_purchase_amount,
        "total_purchase_qty_kg": stock["total_purchased_kg"],
        "total_sale_amount": total_sale_amount,
        "total_sale_qty_kg": stock["total_sold_kg"],
    }

def grade_totals(date_from, date_to):
    """
    Total quantity (gross bag weight) and bag count purchased per cotton
    quality (Type A/B/C) within a date range, based on the purchase's date.
    Used on reports/dashboard to answer "how much of each grade did we buy".
    """
    qs = (
        PurchaseBag.objects.filter(purchase__date__gte=date_from, purchase__date__lte=date_to)
        .values("grade")
        .annotate(total_weight_kg=Sum("weight_kg"), total_bags=Count("id"))
    )
    by_grade = {row["grade"]: row for row in qs}
    grade_labels = dict(GRADE_CHOICES)
    return [
        {
            "grade": code,
            "label": grade_labels[code],
            "total_weight_kg": (by_grade.get(code, {}).get("total_weight_kg") or Decimal("0")).quantize(
                THREE_PLACES
            ),
            "total_bags": by_grade.get(code, {}).get("total_bags") or 0,
        }
        for code in ("A", "B", "C")
    ]


def sale_totals(date_from, date_to):
    qs = Sale.objects.filter(date__gte=date_from, date__lte=date_to)
    agg = qs.aggregate(total_amount=Sum("amount"), total_quantity=Sum("quantity"))
    total_amount = (agg["total_amount"] or Decimal("0")).quantize(TWO_PLACES)
    total_quantity = (agg["total_quantity"] or Decimal("0")).quantize(THREE_PLACES)
    return {"total_amount": total_amount, "total_quantity": total_quantity}, qs


def expense_totals(date_from, date_to):
    qs = Expense.objects.filter(date__gte=date_from, date__lte=date_to)
    total = (qs.aggregate(total=Sum("amount"))["total"] or Decimal("0")).quantize(TWO_PLACES)
    by_category = qs.values("category").annotate(total=Sum("amount")).order_by("category")
    return total, by_category, qs


def purchase_report(date_from, date_to):
    """Purchases-only report section (no sales data at all)."""
    totals, qs = purchase_totals(date_from, date_to)
    return {
        "date_from": date_from,
        "date_to": date_to,
        **totals,
        "grade_totals": grade_totals(date_from, date_to),
        "purchases": qs.select_related("client").order_by("-date", "-created_at"),
    }


def sale_report(date_from, date_to):
    """Sales-only report section (no purchase data at all)."""
    totals, qs = sale_totals(date_from, date_to)
    return {
        "date_from": date_from,
        "date_to": date_to,
        **totals,
        "sales": qs.select_related("buyer").order_by("-date", "-created_at"),
    }


def profit_report(date_from, date_to):
    """
    Requirement #7: Profit = Sales - Purchases (net payable) - Expenses.
    """
    purchase_agg, _ = purchase_totals(date_from, date_to)
    sale_agg, _ = sale_totals(date_from, date_to)
    expense_total, expense_by_category, _ = expense_totals(date_from, date_to)

    total_purchase_cost = purchase_agg["total_net_payable"]
    total_sales = sale_agg["total_amount"]
    profit = total_sales - total_purchase_cost - expense_total

    return {
        "date_from": date_from,
        "date_to": date_to,
        "total_purchase_cost": total_purchase_cost,
        "total_purchase_bags": purchase_agg["total_bags"],
        "total_purchase_net_weight_kg": purchase_agg["total_net_weight_kg"],
        "total_sales": total_sales,
        "total_sale_quantity": sale_agg["total_quantity"],
        "total_expenses": expense_total,
        "expense_by_category": expense_by_category,
        "profit": profit,
    }


#--------------------------------------------------------------
#Daily Investments 
#--------------------------------------------------------------

def investment_balance(): 
    total_invested = Investment.objects.aggregate(total=Sum('amount'))['total'] or Decimal('0.00') 
    total_purchases = Purchase.objects.aggregate(total=Sum('net_payable'))['total'] or Decimal('0.00') 
    total_expenses = Expense.objects.aggregate(total=Sum('amount'))['total'] or Decimal('0.00') 

    return (total_invested - total_purchases - total_expenses).quantize(TWO_PLACES)