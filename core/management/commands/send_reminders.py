from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import timedelta
from core.models import Subscription
from core.email_service import send_reminder_email


class Command(BaseCommand):
    help = 'Sends expiration reminder emails to clients (7 days, 3 days, and 1 day before expiry)'

    def handle(self, *args, **kwargs):
        self.stdout.write(self.style.HTTP_INFO("🚀 Starting automated reminder check..."))
        
        # Get today's date in local time
        today = timezone.localtime().date()
        
        # Define the target dates we care about (1, 3, and 7 days from today)
        target_dates = [
            (1, today + timedelta(days=1)),
            (3, today + timedelta(days=3)),
            (7, today + timedelta(days=7)),
        ]
        
        total_sent = 0
        total_skipped = 0
        
        for days_until, target_date in target_dates:
            self.stdout.write(f"\n📅 Checking for subscriptions expiring in {days_until} day(s) (on {target_date})...")
            
            # Find all subscriptions expiring on this exact date
            # We use __date to extract just the date part of the datetime field
            expiring_subs = Subscription.objects.filter(expiry_date__date=target_date)
            
            if not expiring_subs.exists():
                self.stdout.write(self.style.WARNING("  No subscriptions found for this date."))
                continue
            
            for sub in expiring_subs:
                client = sub.client
                
                # Skip if the client has no email address
                if not client.email:
                    self.stdout.write(self.style.WARNING(f"  ⚠️ Skipped: {client.full_name} (No email address)"))
                    total_skipped += 1
                    continue
                
                self.stdout.write(f"  📧 Sending {days_until}-day reminder to {client.email} ({client.full_name})...")
                
                # Trigger the email service
                success = send_reminder_email(client, days_until)
                
                if success:
                    self.stdout.write(self.style.SUCCESS("    ✅ Sent successfully"))
                    total_sent += 1
                else:
                    self.stdout.write(self.style.ERROR("    ❌ Failed to send"))
        
        # Final Summary
        self.stdout.write("\n" + "="*60)
        self.stdout.write(self.style.SUCCESS(f"🎉 Reminder process complete!"))
        self.stdout.write(self.style.SUCCESS(f"   Emails Sent: {total_sent}"))
        if total_skipped > 0:
            self.stdout.write(self.style.WARNING(f"   Skipped (No Email): {total_skipped}"))
        self.stdout.write("="*60 + "\n")
