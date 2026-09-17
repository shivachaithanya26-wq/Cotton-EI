"""
All business-formula logic lives here, in one place, so it's easy to
audit and change without touching views/templates.
"""
from decimal import ROUND_HALF_UP, Decimal

from django.db.models import Sum
from django.utils import timezone

from .models import CashCuttingRule, Expense, LivePrice, Purchase, Sale, TareRule, Investment

TWO_PLACES = Decimal("0.01")


def to_quintal(weight_kg: Decimal) -> Decimal:
    return weight_kg / Decimal("100")


def calculate_purchase(purchase: Purchase) -> Purchase:
    """
    Implements requirement #9:

      1. Sum the individually-weighed bags -> gross weight, bag count.
      2. Subtract a fixed tare per bag (e.g. 0.5 kg) -> net weight.
      3. Convert net weight into the purchase's chosen unit (kg or quintal).
      4. Multiply by the live (or manual) price -> gross amount.
      5. Deduct a cash-cutting percentage (e.g. 5%) -> net amount payable
         to the client.

    Worked example matching the spec: 3 quintal x Rs.7000 = Rs.21,000.
    5% cash cutting = Rs.1,050. Net payable = Rs.19,950.
    """
    bags = list(purchase.bags.all())
    gross_weight_kg = sum((Decimal(str(b.weight_kg)) for b in bags), Decimal("0"))
    num_bags = len(bags)

    tare_rule = purchase.tare_rule or TareRule.active_default()
    if purchase.custom_tare_per_bag_kg is not None:
        tare_per_bag = Decimal(str(purchase.custom_tare_per_bag_kg))
    elif tare_rule:
        tare_per_bag = Decimal(str(tare_rule.weight_per_bag_kg))
    else:
        tare_per_bag = Decimal("0.5")
    tare_weight_kg = tare_per_bag * num_bags

    net_weight_kg = gross_weight_kg - tare_weight_kg
    if net_weight_kg < 0:
        net_weight_kg = Decimal("0")

    if purchase.live_price_id:
        price_per_quintal = Decimal(str(purchase.live_price.price_per_quintal))
    elif purchase.manual_price_per_quintal:
        price_per_quintal = Decimal(str(purchase.manual_price_per_quintal))
    else:
        price_per_quintal = Decimal("0")

    if purchase.unit == "QTL":
        net_qty_in_unit = to_quintal(net_weight_kg)
        price_per_unit = price_per_quintal
    else:  # KG
        net_qty_in_unit = net_weight_kg
        price_per_unit = price_per_quintal / Decimal("100")

    gross_amount = (net_qty_in_unit * price_per_unit).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)

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
    purchase.price_used_per_quintal = price_per_quintal
    purchase.gross_amount = gross_amount
    purchase.cash_cutting_amount = cash_cutting_amount
    purchase.net_payable = net_payable
    if purchase.cash_cutting_rule_id is None:
        purchase.cash_cutting_rule = cutting_rule
    if purchase.tare_rule_id is None:
        purchase.tare_rule = tare_rule
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
    return {k: (v or Decimal("0")) for k, v in agg.items()}, qs


def sale_totals(date_from, date_to):
    qs = Sale.objects.filter(date__gte=date_from, date__lte=date_to)
    agg = qs.aggregate(total_amount=Sum("amount"), total_quantity=Sum("quantity"))
    return {k: (v or Decimal("0")) for k, v in agg.items()}, qs


def expense_totals(date_from, date_to):
    qs = Expense.objects.filter(date__gte=date_from, date__lte=date_to)
    total = qs.aggregate(total=Sum("amount"))["total"] or Decimal("0")
    by_category = qs.values("category").annotate(total=Sum("amount")).order_by("category")
    return total, by_category, qs


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

    return total_invested - total_purchases - total_expenses