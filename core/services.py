import qrcode
import uuid
import os
from django.conf import settings
from django.utils import timezone
from .models import AccessPass, Subscription, ClientPIN
from .email_service import send_welcome_email, send_qr_code_email, send_pin_email, send_reminder_email


def generate_dynamic_qr_pass(subscription: Subscription, send_email: bool = True) -> AccessPass:
    """Generates a unique, 24-hour Dynamic QR Code and sends it via email"""
    unique_token = str(uuid.uuid4())
    
    access_pass = AccessPass.objects.create(
        subscription=subscription,
        token_string=unique_token
    )
    
    qr_data = f"SUB:{subscription.id}|TOKEN:{unique_token}"
    
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=10,
        border=4,
    )
    qr.add_data(qr_data)
    qr.make(fit=True)
    
    img = qr.make_image(fill_color="black", back_color="white")
    
    filename = f"pass_{access_pass.id}.png"
    filepath = os.path.join(settings.MEDIA_ROOT, 'qrcodes')
    os.makedirs(filepath, exist_ok=True)
    
    full_path = os.path.join(filepath, filename)
    img.save(full_path)
    
    client = subscription.client
    plan_display = subscription.get_plan_type_display()
    
    if send_email and client.email:
        # Send welcome email with QR attached
        success = send_welcome_email(client, subscription, access_pass)
        if success:
            print(f"✅ Welcome email with QR code sent to {client.email}")
        else:
            print(f"⚠️ Failed to send email to {client.email}")
    else:
        # Log for debugging
        print("\n" + "="*60)
        if not client.email:
            print(f"⚠️ No email for {client.full_name} - QR code generated but not sent")
        else:
            print("📧 [EMAIL SKIPPED - send_email=False]")
        print(f"Client: {client.full_name}")
        print(f"Plan: {plan_display}")
        print(f"QR Code: {settings.BASE_URL}/media/qrcodes/{filename}")
        print("="*60 + "\n")
    
    return access_pass


def send_client_pin(client, pin_code: str):
    """Send PIN to client via email"""
    if client.email:
        success = send_pin_email(client, pin_code)
        if success:
            print(f"✅ PIN email sent to {client.email}")
        else:
            print(f"⚠️ Failed to send PIN email to {client.email}")
    else:
        print(f"⚠️ No email for {client.full_name} - cannot send PIN")


def send_reminder(client, days_until_expiry: int):
    """Send expiration reminder via email"""
    if not client.email:
        print(f"⚠️ No email for {client.full_name} - skipping reminder")
        return False
    
    return send_reminder_email(client, days_until_expiry)
