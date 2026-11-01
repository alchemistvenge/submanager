import re
from django import forms
from .models import Subscription, Client


class StaffLoginForm(forms.Form):
    username = forms.CharField(
        max_length=150,
        widget=forms.TextInput(attrs={'placeholder': 'Username'})
    )
    password = forms.CharField(
        widget=forms.PasswordInput(attrs={'placeholder': 'Password'})
    )


class ClientRegistrationForm(forms.Form):
    full_name = forms.CharField(
        max_length=200,
        label="Full name",
    )

    whatsapp_number = forms.CharField(
        max_length=20,
        label="WhatsApp number",
        help_text="Include + and country code. Example: +14155550123",
    )

    email = forms.EmailField(
        required=False,
        label="Email address",
        help_text="For receiving QR codes and reminders (optional but recommended)",
    )

    profile_photo = forms.ImageField(
        required=False,
        label="Profile photo",
    )

    plan_type = forms.ChoiceField(
        choices=Subscription.PLAN_CHOICES,
        label="Subscription plan",
    )

    def clean_whatsapp_number(self):
        number = self.cleaned_data["whatsapp_number"].strip()
        number = re.sub(r"[\s\-\(\)]", "", number)
        if not re.fullmatch(r"\+[0-9]{8,15}", number):
            raise forms.ValidationError(
                "Enter a valid WhatsApp number: + followed by 8 to 15 digits."
            )
        return number
    
    def clean_email(self):
        email = self.cleaned_data.get("email", "").strip().lower()
        if email:
            existing = Client.objects.filter(email=email)
            # Exclude current client if updating
            if hasattr(self, '_current_whatsapp') and self._current_whatsapp:
                existing = existing.exclude(whatsapp_number=self._current_whatsapp)
            if existing.exists():
                raise forms.ValidationError(
                    "This email is already registered to another client."
                )
        return email


class ClientPortalEmailForm(forms.Form):
    """Form for client portal - enter email to receive PIN"""
    email = forms.EmailField(
        label="Your email address",
        help_text="We'll send a 6-digit verification code to this email",
        widget=forms.EmailInput(attrs={'placeholder': 'you@example.com'})
    )
    
    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        try:
            Client.objects.get(email=email)
        except Client.DoesNotExist:
            raise forms.ValidationError(
                "This email is not registered in our system. Please contact the front desk."
            )
        return email
