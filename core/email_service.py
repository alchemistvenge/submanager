import logging
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.conf import settings
from django.utils.html import strip_tags

logger = logging.getLogger(__name__)


def send_welcome_email(client, subscription, access_pass):
    """Send welcome email with QR code attached"""
    if not client.email:
        logger.warning(f"No email for client {client.full_name}, skipping welcome email")
        return False
    
    try:
        subject = f"Welcome to SubManager! Your {subscription.get_plan_type_display()} is active"
        
        html_content = render_to_string('core/emails/welcome.html', {
            'client': client,
            'subscription': subscription,
            'access_pass': access_pass,
            'qr_url': f"{settings.BASE_URL}/media/qrcodes/pass_{access_pass.id}.png",
            'portal_url': f"{settings.BASE_URL}/portal/",
        })
        
        text_content = strip_tags(html_content)
        
        email = EmailMultiAlternatives(
            subject=subject,
            body=text_content,
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=[client.email],
        )
        
        email.attach_alternative(html_content, "text/html")
        
        # Attach QR code image
        qr_path = f"{settings.MEDIA_ROOT}/qrcodes/pass_{access_pass.id}.png"
        email.attach_file(qr_path, mimetype='image/png')
        
        email.send()
        
        logger.info(f"✅ Welcome email sent to {client.email}")
        return True
        
    except Exception as e:
        logger.error(f"❌ Failed to send welcome email to {client.email}: {e}")
        return False


def send_qr_code_email(client, access_pass, subscription):
    """Send a fresh QR code to the client"""
    if not client.email:
        logger.warning(f"No email for client {client.full_name}, skipping QR email")
        return False
    
    try:
        subject = f"Your Access Pass - {subscription.get_plan_type_display()}"
        
        html_content = render_to_string('core/emails/qr_code.html', {
            'client': client,
            'access_pass': access_pass,
            'subscription': subscription,
            'qr_url': f"{settings.BASE_URL}/media/qrcodes/pass_{access_pass.id}.png",
        })
        
        text_content = strip_tags(html_content)
        
        email = EmailMultiAlternatives(
            subject=subject,
            body=text_content,
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=[client.email],
        )
        
        email.attach_alternative(html_content, "text/html")
        
        qr_path = f"{settings.MEDIA_ROOT}/qrcodes/pass_{access_pass.id}.png"
        email.attach_file(qr_path, mimetype='image/png')
        
        email.send()
        
        logger.info(f"✅ QR code email sent to {client.email}")
        return True
        
    except Exception as e:
        logger.error(f"❌ Failed to send QR email to {client.email}: {e}")
        return False


def send_pin_email(client, pin_code):
    """Send PIN verification email"""
    if not client.email:
        logger.warning(f"No email for client {client.full_name}, skipping PIN email")
        return False
    
    try:
        subject = "Your SubManager Verification Code"
        
        html_content = render_to_string('core/emails/pin.html', {
            'client': client,
            'pin_code': pin_code,
        })
        
        text_content = strip_tags(html_content)
        
        email = EmailMultiAlternatives(
            subject=subject,
            body=text_content,
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=[client.email],
        )
        
        email.attach_alternative(html_content, "text/html")
        email.send()
        
        logger.info(f"✅ PIN email sent to {client.email}")
        return True
        
    except Exception as e:
        logger.error(f"❌ Failed to send PIN email to {client.email}: {e}")
        return False


def send_reminder_email(client, days_until_expiry):
    """Send expiration reminder email"""
    if not client.email:
        logger.warning(f"No email for client {client.full_name}, skipping reminder")
        return False
    
    subscription = client.current_subscription
    if not subscription:
        return False
    
    try:
        if days_until_expiry <= 1:
            subject = "⚠️ URGENT: Your subscription expires tomorrow!"
            urgency = 'urgent'
        elif days_until_expiry <= 3:
            subject = f"Reminder: {days_until_expiry} days left on your subscription"
            urgency = 'warning'
        else:
            subject = f"Your subscription expires in {days_until_expiry} days"
            urgency = 'info'
        
        html_content = render_to_string('core/emails/reminder.html', {
            'client': client,
            'subscription': subscription,
            'days_until_expiry': days_until_expiry,
            'urgency': urgency,
            'portal_url': f"{settings.BASE_URL}/portal/",
        })
        
        text_content = strip_tags(html_content)
        
        email = EmailMultiAlternatives(
            subject=subject,
            body=text_content,
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=[client.email],
        )
        
        email.attach_alternative(html_content, "text/html")
        email.send()
        
        logger.info(f"✅ {days_until_expiry}-day reminder sent to {client.email}")
        return True
        
    except Exception as e:
        logger.error(f"❌ Failed to send reminder to {client.email}: {e}")
        return False
