from django.urls import path

from . import views

app_name = "core"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("price/set/", views.set_today_price, name="set_today_price"),

    path("purchases/", views.purchase_list, name="purchase_list"),
    path("purchases/new/", views.purchase_create, name="purchase_create"),
    path("purchases/<int:pk>/", views.purchase_detail, name="purchase_detail"),

    path("sales/", views.sale_list, name="sale_list"),
    path("sales/new/", views.sale_create, name="sale_create"),

    path("expenses/", views.expense_list, name="expense_list"),
    path("expenses/new/", views.expense_create, name="expense_create"),

    path("reports/daily/", views.report_daily, name="report_daily"),
    path("reports/monthly/", views.report_monthly, name="report_monthly"),
    path("reports/custom/", views.report_custom, name="report_custom"),

    path("clients/", views.client_list, name="client_list"),
    path("buyers/", views.buyer_list, name="buyer_list"),
]
