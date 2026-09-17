from django import forms
from django.forms import inlineformset_factory

from .models import Buyer, Client, Expense, LivePrice, Purchase, PurchaseBag, Sale, Investment


class DateRangeForm(forms.Form):
    date_from = forms.DateField(widget=forms.DateInput(attrs={"type": "date"}))
    date_to = forms.DateField(widget=forms.DateInput(attrs={"type": "date"}))


class TodayPriceForm(forms.ModelForm):
    class Meta:
        model = LivePrice
        fields = ["price_per_quintal"]
        widgets = {
            "price_per_quintal": forms.NumberInput(attrs={"step": "0.01", "class": "form-control"}),
        }


class PurchaseForm(forms.ModelForm):
    # Optional inline "new client" fields — if the client dropdown is left
    # blank, these are used to create a Client on the fly.
    new_client_name = forms.CharField(
        required=False, max_length=150,
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "e.g. Ramesh Farmer"}),
        label="Or add a new client — Name",
    )
    new_client_phone = forms.CharField(
        required=False, max_length=20,
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "Optional"}),
        label="New client — Phone",
    )

    class Meta:
        model = Purchase
        fields = [
            "date",
            "client",
            "unit",
            "live_price",
            "manual_price_per_quintal",
            "cash_cutting_rule",
            "tare_rule",
            "custom_cash_cutting_rate_percent",
            "custom_tare_per_bag_kg",
            "notes",
        ]
        widgets = {
            "date": forms.DateInput(attrs={"type": "date", "class": "form-control"}),
            "client": forms.Select(attrs={"class": "form-select"}),
            "unit": forms.Select(attrs={"class": "form-select"}),
            "live_price": forms.Select(attrs={"class": "form-select"}),
            "manual_price_per_quintal": forms.NumberInput(attrs={"step": "0.01", "class": "form-control"}),
            "cash_cutting_rule": forms.Select(attrs={"class": "form-select"}),
            "tare_rule": forms.Select(attrs={"class": "form-select"}),
            "custom_cash_cutting_rate_percent": forms.NumberInput(
                attrs={"step": "0.01", "class": "form-control", "placeholder": "e.g. 5.00"}
            ),
            "custom_tare_per_bag_kg": forms.NumberInput(
                attrs={"step": "0.001", "class": "form-control", "placeholder": "e.g. 0.500"}
            ),
            "notes": forms.Textarea(attrs={"rows": 2, "class": "form-control"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["client"].required = False

    def clean(self):
        cleaned_data = super().clean()
        client = cleaned_data.get("client")
        new_client_name = cleaned_data.get("new_client_name", "").strip()
        if not client and not new_client_name:
            raise forms.ValidationError(
                "Select an existing client, or enter a name in 'Or add a new client' below."
            )
        if client and new_client_name:
            raise forms.ValidationError(
                "Choose either an existing client OR fill in the new-client fields — not both."
            )
        return cleaned_data

class PurchaseBagForm(forms.ModelForm):
    class Meta:
        model = PurchaseBag
        fields = ["bag_number", "weight_kg"]
        widgets = {
            "bag_number": forms.NumberInput(attrs={"class": "form-control", "min": 1}),
            "weight_kg": forms.NumberInput(attrs={"class": "form-control", "step": "0.001", "min": 0}),
        }


# Requirement #9: bags are entered one at a time -> use a formset so the
# interface can show "Bag 1", "Bag 2", "Bag 3" ... rows with an "add another"
# control, all attached to a single Purchase.
PurchaseBagFormSet = inlineformset_factory(
    Purchase,
    PurchaseBag,
    form=PurchaseBagForm,
    extra=3,
    can_delete=True,
)

class PurchaseExpenseForm(forms.ModelForm):
     class Meta:
         model = Expense
         fields = ['category', 'description', 'amount'] 
         widgets = { 
            'category': forms.Select(attrs={'class': 'form-select'}), 
            'description': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Optional'}),
            'amount': forms.NumberInput(attrs={'step': '0.01', 'class': 'form-control', 'min': 0}), 
            } 
PurchaseExpenseFormSet = inlineformset_factory( Purchase, Expense, form=PurchaseExpenseForm, fk_name='related_purchase', extra=2, can_delete=True, )

class SaleForm(forms.ModelForm):
    class Meta:
        model = Sale
        fields = ["date", "buyer", "unit", "quantity", "price_per_unit", "notes"]
        widgets = {
            "date": forms.DateInput(attrs={"type": "date", "class": "form-control"}),
            "buyer": forms.Select(attrs={"class": "form-select"}),
            "unit": forms.Select(attrs={"class": "form-select"}),
            "quantity": forms.NumberInput(attrs={"step": "0.001", "class": "form-control"}),
            "price_per_unit": forms.NumberInput(attrs={"step": "0.01", "class": "form-control"}),
            "notes": forms.Textarea(attrs={"rows": 2, "class": "form-control"}),
        }


class ExpenseForm(forms.ModelForm):
    class Meta:
        model = Expense
        fields = ["date", "category", "description", "amount", "related_purchase"]
        widgets = {
            "date": forms.DateInput(attrs={"type": "date", "class": "form-control"}),
            "category": forms.Select(attrs={"class": "form-select"}),
            "description": forms.TextInput(attrs={"class": "form-control"}),
            "amount": forms.NumberInput(attrs={"step": "0.01", "class": "form-control"}),
            "related_purchase": forms.Select(attrs={"class": "form-select"}),
        }


class ClientForm(forms.ModelForm):
    class Meta:
        model = Client
        fields = ["name", "phone", "address"]
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-control"}),
            "phone": forms.TextInput(attrs={"class": "form-control"}),
            "address": forms.Textarea(attrs={"rows": 2, "class": "form-control"}),
        }


class BuyerForm(forms.ModelForm):
    class Meta:
        model = Buyer
        fields = ["name", "industry_name", "phone", "address"]
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-control"}),
            "industry_name": forms.TextInput(attrs={"class": "form-control"}),
            "phone": forms.TextInput(attrs={"class": "form-control"}),
            "address": forms.Textarea(attrs={"rows": 2, "class": "form-control"}),
        }


class InvestmentForm(forms.ModelForm): 
    class Meta: 
        model = Investment 
        fields = ['amount', 'notes'] 
        widgets = { 
            'amount': forms.NumberInput(attrs={'step': '0.01', 'class': 'form-control', 'autofocus': True}), 
            'notes': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Optional'}), 
            } 