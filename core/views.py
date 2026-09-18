import calendar
from datetime import date

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from . import services
from .forms import (
    BuyerForm,
    ClientForm,
    DateRangeForm,
    ExpenseForm,
    PurchaseBagFormSet,
    PurchaseExpenseFormSet,
    PurchaseForm,
    SaleForm,
    TodayPriceForm,
    InvestmentForm,
)
from .models import Buyer, Client, Expense, LivePrice, Purchase, Sale, Investment


@login_required
def dashboard(request):
    today = timezone.localdate()
    today_purchases, purchase_qs = services.purchase_totals(today, today)
    today_sales, sale_qs = services.sale_totals(today, today)
    today_expenses, _, _ = services.expense_totals(today, today)
    today_price = LivePrice.latest_for(today)

    stock = services.stock_summary()
    overall = services.overall_totals()

    context = {
        "today": today,
        "today_price": today_price,
        "today_purchase_total": today_purchases["total_net_payable"],
        "today_purchase_count": purchase_qs.count(),
        "today_purchase_qty_kg": today_purchases["total_net_weight_kg"],
        "today_sale_total": today_sales["total_amount"],
        "today_sale_count": sale_qs.count(),
        "today_sale_qty": today_sales["total_quantity"],
        "today_expense_total": today_expenses,
        "stock": stock,
        "overall": overall,
        "investment_balance": services.investment_balance(),
    }
    return render(request, "core/dashboard.html", context)


# ---------------------------------------------------------------------
# Live / manual price (requirement #1)
# ---------------------------------------------------------------------

@login_required
def set_today_price(request):
    today = timezone.localdate()
    if request.method == "POST":
        form = TodayPriceForm(request.POST)
        if form.is_valid():
            LivePrice.objects.create(
                date=today,
                price_per_quintal=form.cleaned_data["price_per_quintal"],
                source="MANUAL",
            )
            messages.success(request, f"Price for {today} saved.")
            return redirect("core:dashboard")
    else:
        form = TodayPriceForm()
    price_history = LivePrice.objects.all()[:15]
    return render(request, "core/set_price.html", {"form": form, "today": today, "price_history": price_history})


# ---------------------------------------------------------------------
# Purchases (requirements #2, #4, #8, #9)
# ---------------------------------------------------------------------

@login_required
def purchase_list(request):
    purchases = Purchase.objects.select_related("client").all()[:200]
    return render(request, "core/purchase_list.html", {"purchases": purchases})


@login_required
def purchase_create(request):
    if request.method == "POST":
        form = PurchaseForm(request.POST)
        formset = PurchaseBagFormSet(request.POST, instance=Purchase())
        expense_formset = PurchaseExpenseFormSet(request.POST, instance=Purchase())
        if form.is_valid() and formset.is_valid() and expense_formset.is_valid():
            # Which grades actually have bags in this submission? Only look
            # at forms that weren't left blank / marked for deletion.
            grades_present = {
                f.cleaned_data.get("grade", "A")
                for f in formset.forms
                if f.cleaned_data and not f.cleaned_data.get("DELETE") and f.cleaned_data.get("weight_kg")
            }
            price_errors = []
            if "A" in grades_present and not form.cleaned_data.get("live_price") and not form.cleaned_data.get(
                "manual_price_per_quintal"
            ):
                price_errors.append("Enter today's Type A price (live price or manual) — you have Type A bags.")
            if "B" in grades_present and form.cleaned_data.get("price_type_b_per_quintal") is None:
                price_errors.append("Enter a Type B price — you have Type B bags in this purchase.")
            if "C" in grades_present and form.cleaned_data.get("price_type_c_per_quintal") is None:
                price_errors.append("Enter a Type C price — you have Type C bags in this purchase.")

            if price_errors:
                for error in price_errors:
                    form.add_error(None, error)
            else:
                with transaction.atomic():
                    purchase = form.save(commit=False)
                    if not purchase.client_id:
                        purchase.client = Client.objects.create(
                            name=form.cleaned_data["new_client_name"].strip(),
                            phone=form.cleaned_data.get("new_client_phone", "").strip(),
                        )
                    purchase.save()
                    formset.instance = purchase
                    formset.save()
                    expense_formset.instance = purchase
                    for expense in expense_formset.save(commit=False):
                        expense.related_purchase = purchase
                        expense.date = purchase.date
                        expense.save()
                    purchase.recalculate()
                messages.success(request, f"Purchase #{purchase.pk} saved. Net payable: Rs.{purchase.net_payable}")
                return redirect("core:purchase_detail", pk=purchase.pk)
    else:
        today_price = LivePrice.latest_for(timezone.localdate())
        initial = {"live_price": today_price.pk} if today_price else {}
        form = PurchaseForm(initial=initial)
        formset = PurchaseBagFormSet(instance=Purchase())
        expense_formset = PurchaseExpenseFormSet(instance=Purchase())
    return render(
        request,
        "core/purchase_form.html",
        {"form": form, "formset": formset, "expense_formset": expense_formset},
    )

@login_required
def purchase_detail(request, pk):
    purchase = get_object_or_404(Purchase.objects.select_related("client", "live_price"), pk=pk)
    return render(request, "core/purchase_detail.html", {"purchase": purchase})


# ---------------------------------------------------------------------
# Sales (requirement #5)
# ---------------------------------------------------------------------

@login_required
def sale_list(request):
    sales = Sale.objects.select_related("buyer").all()[:200]
    return render(request, "core/sale_list.html", {"sales": sales})


@login_required
def sale_create(request):
    if request.method == "POST":
        form = SaleForm(request.POST)
        if form.is_valid():
            sale = form.save()
            messages.success(request, f"Sale #{sale.pk} saved. Amount: Rs.{sale.amount}")
            return redirect("core:sale_list")
    else:
        form = SaleForm()
    return render(request, "core/sale_form.html", {"form": form})


# ---------------------------------------------------------------------
# Expenses (requirement #6)
# ---------------------------------------------------------------------

@login_required
def expense_list(request):
    expenses = Expense.objects.all()[:200]
    return render(request, "core/expense_list.html", {"expenses": expenses})


@login_required
def expense_create(request):
    if request.method == "POST":
        form = ExpenseForm(request.POST)
        if form.is_valid():
            expense = form.save()
            messages.success(request, "Expense recorded.")
            return redirect("core:expense_list")
    else:
        form = ExpenseForm()
    return render(request, "core/expense_form.html", {"form": form})


# ---------------------------------------------------------------------
# Reports (requirements #2, #3, #7)
# ---------------------------------------------------------------------

SECTION_REPORT_FUNCS = {
    "purchases": services.purchase_report,
    "sales": services.sale_report,
    "profit_loss": services.profit_report,
}


@login_required
def report_daily(request):
    day_str = request.GET.get("date")
    day = date.fromisoformat(day_str) if day_str else timezone.localdate()
    section = request.GET.get("section", "purchases")
    report = SECTION_REPORT_FUNCS.get(section, services.purchase_report)(day, day)
    date_qs = f"date={day.isoformat()}"
    return render(
        request,
        "core/report.html",
        {
            "report": report,
            "title": f"Daily report - {day}",
            "mode": "daily",
            "day": day,
            "section": section,
            "tab_urls": {name: f"?{date_qs}&section={name}" for name in SECTION_REPORT_FUNCS},
        },
    )


@login_required
def report_monthly(request):
    year = int(request.GET.get("year", timezone.localdate().year))
    month = int(request.GET.get("month", timezone.localdate().month))
    section = request.GET.get("section", "purchases")
    first_day = date(year, month, 1)
    last_day = date(year, month, calendar.monthrange(year, month)[1])
    report = SECTION_REPORT_FUNCS.get(section, services.purchase_report)(first_day, last_day)
    date_qs = f"year={year}&month={month}"
    return render(
        request,
        "core/report.html",
        {
            "report": report,
            "title": f"Monthly report - {first_day:%B %Y}",
            "mode": "monthly",
            "year": year,
            "month": month,
            "section": section,
            "tab_urls": {name: f"?{date_qs}&section={name}" for name in SECTION_REPORT_FUNCS},
        },
    )


@login_required
def report_custom(request):
    report = None
    section = request.GET.get("section", "purchases")
    if request.method == "GET" and request.GET.get("date_from"):
        form = DateRangeForm(request.GET)
        if form.is_valid():
            date_from = form.cleaned_data["date_from"]
            date_to = form.cleaned_data["date_to"]
            report = SECTION_REPORT_FUNCS.get(section, services.purchase_report)(date_from, date_to)
            date_qs = f"date_from={date_from.isoformat()}&date_to={date_to.isoformat()}"
        else:
            date_qs = ""
    else:
        form = DateRangeForm()
        date_qs = ""
    return render(
        request,
        "core/report_custom.html",
        {
            "form": form,
            "report": report,
            "section": section,
            "tab_urls": {name: f"?{date_qs}&section={name}" for name in SECTION_REPORT_FUNCS} if date_qs else {},
        },
    )


# ---------------------------------------------------------------------
# Clients / Buyers (simple CRUD, create-only for brevity)
# ---------------------------------------------------------------------

@login_required
def client_list(request):
    if request.method == "POST":
        form = ClientForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect("core:client_list")
    else:
        form = ClientForm()
    return render(request, "core/client_list.html", {"form": form, "clients": Client.objects.all()})


@login_required
def buyer_list(request):
    if request.method == "POST":
        form = BuyerForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect("core:buyer_list")
    else:
        form = BuyerForm()
    return render(request, "core/buyer_list.html", {"form": form, "buyers": Buyer.objects.all()})

#-------------------------------------------------
#Daily Investment
#--------------------------------------------------

@login_required
def investment_add(request):
    if request.method == "POST":
        form = InvestmentForm(request.POST)
        if form.is_valid():
            investment = form.save(commit=False)
            investment.date = timezone.localdate()
            investment.save()
            messages.success(
                request,
                f"Investment of Rs.{investment.amount} added. "
                f"Remaining balance: Rs.{services.investment_balance()}",
            )
            return redirect("core:dashboard")
    else:
        form = InvestmentForm()
    context = {
        "form": form,
        "recent_investments": Investment.objects.all()[:15],
        "balance": services.investment_balance(),
    }
    return render(request, "core/investment_form.html", context)