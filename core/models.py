from decimal import Decimal

from django.db import models
from django.urls import reverse
from django.utils import timezone

UNIT_CHOICES = [
    ("KG", "Kilogram"),
    ("QTL", "Quintal (100 kg)"),
]


class Client(models.Model):
    """A farmer / seller we buy cotton from."""

    name = models.CharField(max_length=150)
    phone = models.CharField(max_length=20, blank=True)
    address = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class Buyer(models.Model):
    """An industry / ginning mill / trader we sell cotton to."""

    name = models.CharField(max_length=150)
    industry_name = models.CharField(max_length=150, blank=True)
    phone = models.CharField(max_length=20, blank=True)
    address = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class LivePrice(models.Model):
    """
    One price record per day (per source). Price is always stored
    per QUINTAL internally so KG conversions are consistent everywhere.
    """

    SOURCE_CHOICES = [
        ("LIVE", "Fetched Live"),
        ("MANUAL", "Manual Entry"),
    ]

    date = models.DateField(default=timezone.now)
    price_per_quintal = models.DecimalField(max_digits=10, decimal_places=2)
    source = models.CharField(max_length=10, choices=SOURCE_CHOICES, default="MANUAL")
    fetched_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-date", "-fetched_at"]

    def __str__(self):
        return f"{self.date} - Rs.{self.price_per_quintal}/qtl ({self.get_source_display()})"

    @classmethod
    def latest_for(cls, date):
        """Latest price known on or before a given date."""
        return cls.objects.filter(date__lte=date).order_by("-date", "-fetched_at").first()


class CashCuttingRule(models.Model):
    """
    'Kata' / cash-cutting deduction applied on the gross purchase amount.
    Example from spec: Rs.50 deducted per Rs.1000 => 5.00 percent.
    """

    name = models.CharField(max_length=100, default="Default Cash Cutting")
    rate_percent = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal("5.00"),
        help_text="Deduction percentage on gross purchase amount (e.g. 5.00 = Rs.50 per Rs.1000).",
    )
    is_active = models.BooleanField(default=True)
    effective_from = models.DateField(default=timezone.now)

    class Meta:
        ordering = ["-effective_from"]

    def __str__(self):
        return f"{self.name} ({self.rate_percent}%)"

    @classmethod
    def active_default(cls):
        return cls.objects.filter(is_active=True).order_by("-effective_from").first()


class TareRule(models.Model):
    """Per-bag weight deduction (packing/moisture allowance)."""

    name = models.CharField(max_length=100, default="Default Bag Tare")
    weight_per_bag_kg = models.DecimalField(
        max_digits=6,
        decimal_places=3,
        default=Decimal("0.500"),
        help_text="Weight deducted per bag in KG (e.g. 0.5 for 500 g).",
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["-id"]

    def __str__(self):
        return f"{self.name} ({self.weight_per_bag_kg} kg/bag)"

    @classmethod
    def active_default(cls):
        return cls.objects.filter(is_active=True).order_by("-id").first()


class Purchase(models.Model):
    """
    One purchase transaction from a client, made up of one or more bags
    weighed individually. All derived fields are computed by
    core.services.calculate_purchase() and are not hand-editable.
    """

    date = models.DateField(default=timezone.now)
    client = models.ForeignKey(Client, on_delete=models.PROTECT, related_name="purchases")
    unit = models.CharField(max_length=3, choices=UNIT_CHOICES, default="QTL")

    live_price = models.ForeignKey(
        LivePrice, on_delete=models.PROTECT, null=True, blank=True,
        help_text="Leave blank to use the manual price below instead.",
    )
    manual_price_per_quintal = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True,
        help_text="Used only if no live price is selected above.",
    )

    # cash_cutting_rule = models.ForeignKey(CashCuttingRule, on_delete=models.PROTECT, null=True, blank=True)
    # tare_rule = models.ForeignKey(TareRule, on_delete=models.PROTECT, null=True, blank=True)

    cash_cutting_rule = models.ForeignKey(CashCuttingRule, on_delete=models.PROTECT, null=True, blank=True, help_text="Leave blank if entering a custom rate below.") 
    tare_rule = models.ForeignKey(TareRule, on_delete=models.PROTECT, null=True, blank=True, help_text="Leave blank if entering a custom tare below.") 
    custom_cash_cutting_rate_percent = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True, help_text="Custom cash-cutting % for this purchase only.") 
    custom_tare_per_bag_kg = models.DecimalField(max_digits=6, decimal_places=3, null=True, blank=True, help_text="Custom tare (kg per bag) for this purchase only.")

    # ---- computed / derived fields (set by services.calculate_purchase) ----
    gross_weight_kg = models.DecimalField(max_digits=10, decimal_places=3, default=0, editable=False)
    num_bags = models.PositiveIntegerField(default=0, editable=False)
    tare_weight_kg = models.DecimalField(max_digits=10, decimal_places=3, default=0, editable=False)
    net_weight_kg = models.DecimalField(max_digits=10, decimal_places=3, default=0, editable=False)

    price_used_per_quintal = models.DecimalField(max_digits=10, decimal_places=2, default=0, editable=False)
    gross_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0, editable=False)
    cash_cutting_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0, editable=False)
    net_payable = models.DecimalField(max_digits=12, decimal_places=2, default=0, editable=False)

    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-date", "-created_at"]

    def __str__(self):
        return f"Purchase #{self.pk} - {self.client} - {self.date}"

    def get_absolute_url(self):
        return reverse("core:purchase_detail", args=[self.pk])

    def recalculate(self, save=True):
        from .services import calculate_purchase

        calculate_purchase(self)
        if save:
            self.save()


class PurchaseBag(models.Model):
    """Individual bag weighed at intake, entered one at a time."""

    purchase = models.ForeignKey(Purchase, on_delete=models.CASCADE, related_name="bags")
    bag_number = models.PositiveIntegerField()
    weight_kg = models.DecimalField(max_digits=8, decimal_places=3)

    class Meta:
        ordering = ["bag_number"]
        unique_together = ("purchase", "bag_number")

    def __str__(self):
        return f"Bag {self.bag_number} - {self.weight_kg} kg"


class Sale(models.Model):
    """A sale of cotton to a buyer/industry."""

    date = models.DateField(default=timezone.now)
    buyer = models.ForeignKey(Buyer, on_delete=models.PROTECT, related_name="sales")
    unit = models.CharField(max_length=3, choices=UNIT_CHOICES, default="QTL")
    quantity = models.DecimalField(max_digits=10, decimal_places=3)
    price_per_unit = models.DecimalField(max_digits=10, decimal_places=2)
    amount = models.DecimalField(max_digits=12, decimal_places=2, editable=False, default=0)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-date", "-created_at"]

    def save(self, *args, **kwargs):
        self.amount = (self.quantity or Decimal("0")) * (self.price_per_unit or Decimal("0"))
        super().save(*args, **kwargs)

    def __str__(self):
        return f"Sale #{self.pk} - {self.buyer} - {self.date}"


class Expense(models.Model):
    """Extra costs: cash-while-buying, labour, transport, shop rent, etc."""

    CATEGORY_CHOICES = [
        ("CASH_EXTRA", "Extra Cash Given (purchase/delivery)"),
        ("LABOUR", "Labour Cost"),
        ("TRANSPORT", "Vehicle / Transport Rent"),
        ("SHOP_RENT", "Shop Rent"),
        ("LOADING", "Loading / Unloading"),
        ("OTHER", "Other"),
    ]

    date = models.DateField(default=timezone.now)
    category = models.CharField(max_length=15, choices=CATEGORY_CHOICES)
    description = models.CharField(max_length=255, blank=True)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    related_purchase = models.ForeignKey(
        Purchase, on_delete=models.SET_NULL, null=True, blank=True, related_name="extra_costs"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-date", "-created_at"]

    def __str__(self):
        return f"{self.get_category_display()} - Rs.{self.amount} ({self.date})"
