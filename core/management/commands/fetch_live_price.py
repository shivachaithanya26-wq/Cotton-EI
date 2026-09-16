from decimal import Decimal, InvalidOperation

from django.core.management.base import BaseCommand, CommandError

from core.services import get_or_create_today_price


class Command(BaseCommand):
    help = (
        "Fetch (or record) today's cotton price. Tries the live source "
        "configured in core/services.py first; if that returns nothing, "
        "pass --manual-price to store a manual value, or it will fall "
        "back to the previous day's price.\n\n"
        "Schedule this daily, e.g. with cron:\n"
        "  0 9 * * * /path/to/venv/bin/python /path/to/manage.py fetch_live_price"
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--manual-price",
            type=str,
            default=None,
            help="Fallback price per quintal to use if live fetch fails.",
        )

    def handle(self, *args, **options):
        manual_price = None
        if options["manual_price"]:
            try:
                manual_price = Decimal(options["manual_price"])
            except InvalidOperation:
                raise CommandError("--manual-price must be a number, e.g. 7000.00")

        price = get_or_create_today_price(manual_price=manual_price)
        self.stdout.write(
            self.style.SUCCESS(
                f"Price for {price.date}: Rs.{price.price_per_quintal}/quintal (source: {price.source})"
            )
        )
