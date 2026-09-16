from django.contrib import admin

from .models import (
    Buyer,
    CashCuttingRule,
    Client,
    Expense,
    LivePrice,
    Purchase,
    PurchaseBag,
    Sale,
    TareRule,
)


@admin.register(Client)
class ClientAdmin(admin.ModelAdmin):
    list_display = ("name", "phone", "created_at")
    search_fields = ("name", "phone")


@admin.register(Buyer)
class BuyerAdmin(admin.ModelAdmin):
    list_display = ("name", "industry_name", "phone", "created_at")
    search_fields = ("name", "industry_name")


@admin.register(LivePrice)
class LivePriceAdmin(admin.ModelAdmin):
    list_display = ("date", "price_per_quintal", "source", "fetched_at")
    list_filter = ("source",)
    ordering = ("-date",)


@admin.register(CashCuttingRule)
class CashCuttingRuleAdmin(admin.ModelAdmin):
    list_display = ("name", "rate_percent", "is_active", "effective_from")


@admin.register(TareRule)
class TareRuleAdmin(admin.ModelAdmin):
    list_display = ("name", "weight_per_bag_kg", "is_active")


class PurchaseBagInline(admin.TabularInline):
    model = PurchaseBag
    extra = 3


@admin.register(Purchase)
class PurchaseAdmin(admin.ModelAdmin):
    list_display = (
        "id", "date", "client", "unit", "num_bags", "net_weight_kg",
        "price_used_per_quintal", "gross_amount", "cash_cutting_amount", "net_payable",
    )
    list_filter = ("date", "unit")
    search_fields = ("client__name",)
    inlines = [PurchaseBagInline]
    readonly_fields = (
        "gross_weight_kg", "num_bags", "tare_weight_kg", "net_weight_kg",
        "price_used_per_quintal", "gross_amount", "cash_cutting_amount", "net_payable",
    )

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)

    def save_related(self, request, form, formsets, change):
        super().save_related(request, form, formsets, change)
        form.instance.recalculate()


@admin.register(Sale)
class SaleAdmin(admin.ModelAdmin):
    list_display = ("id", "date", "buyer", "unit", "quantity", "price_per_unit", "amount")
    list_filter = ("date", "unit")
    search_fields = ("buyer__name",)


@admin.register(Expense)
class ExpenseAdmin(admin.ModelAdmin):
    list_display = ("id", "date", "category", "amount", "description")
    list_filter = ("category", "date")
