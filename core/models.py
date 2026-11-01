from django.db import models
from django.utils import timezone
from django.contrib.auth.models import AbstractUser
from datetime import timedelta, datetime
import random
import string


class User(AbstractUser):
    """Custom user model with role-based permissions"""
    
    ROLE_CHOICES = [
        ('OWNER', 'Owner (Full Access)'),
        ('MANAGER', 'Manager (No Financials)'),
        ('RECEPTIONIST', 'Receptionist (Register Only)'),
        ('SECURITY', 'Security Guard (Scan Only)'),
    ]
    
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default='RECEPTIONIST')
    phone_number = models.CharField(max_length=20, blank=True)
    can_view_all_clients = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    
    def __str__(self):
        return f"{self.username} ({self.get_role_display()})"
    
    @property
    def is_owner(self):
        return self.role == 'OWNER'
    
    @property
    def is_manager(self):
        return self.role == 'MANAGER'
    
    @property
    def is_receptionist(self):
        return self.role == 'RECEPTIONIST'
    
    @property
    def is_security(self):
        return self.role == 'SECURITY'
    
    @property
    def can_see_financials(self):
        return self.role in ['OWNER']
    
    @property
    def can_register_clients(self):
        return self.role in ['OWNER', 'MANAGER', 'RECEPTIONIST']
    
    @property
    def can_scan_qr(self):
        return True
    
    def get_unread_message_count(self):
        return InternalMessage.objects.filter(
            recipient=self,
            is_read=False
        ).count()
    
    def get_open_issues_count(self):
        return InternalMessage.objects.filter(
            recipient=self,
            status__in=['OPEN', 'IN_PROGRESS'],
            parent__isnull=True
        ).count()


class Client(models.Model):
    full_name = models.CharField(max_length=200)
    whatsapp_number = models.CharField(
        max_length=20, 
        unique=True, 
        help_text="Include country code, e.g., +1234567890"
    )
    email = models.EmailField(
        blank=True, 
        null=True,
        help_text="Email address for QR codes and reminders"
    )
    profile_photo = models.ImageField(
        upload_to='client_photos/', 
        blank=True, 
        null=True
    )
    is_active = models.BooleanField(default=True)
    is_banned = models.BooleanField(default=False)
    ban_reason = models.TextField(blank=True)
    tags = models.CharField(max_length=500, blank=True, help_text="Comma-separated tags: VIP, Problematic, New")
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='registered_clients')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.full_name
    
    @property
    def current_subscription(self):
        return self.subscriptions.filter(
            expiry_date__gt=timezone.now()
        ).order_by('-expiry_date').first()
    
    @property
    def is_subscribed(self):
        return self.current_subscription is not None
    
    @property
    def has_email(self):
        return bool(self.email)


class ClientNote(models.Model):
    """Multiple notes per client"""
    client = models.ForeignKey(Client, on_delete=models.CASCADE, related_name='notes')
    author = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='client_notes')
    content = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['-created_at']
    
    def __str__(self):
        return f"Note by {self.author.username if self.author else 'Unknown'} on {self.client.full_name}"


class InternalMessage(models.Model):
    """Enhanced internal messaging system"""
    MESSAGE_TYPES = [
        ('PERSONAL', 'Personal Message'),
        ('COMPLAINT', 'Client Complaint'),
        ('GENERAL', 'General Inquiry'),
        ('ANNOUNCEMENT', 'Broadcast Announcement'),
        ('SHIFT_NOTE', 'Shift Handover Note'),
    ]
    
    STATUS_CHOICES = [
        ('OPEN', 'Open'),
        ('IN_PROGRESS', 'In Progress'),
        ('RESOLVED', 'Resolved'),
        ('CLOSED', 'Closed'),
    ]
    
    PRIORITY_CHOICES = [
        ('LOW', 'Low'),
        ('NORMAL', 'Normal'),
        ('HIGH', 'High'),
        ('URGENT', 'Urgent'),
    ]
    
    sender = models.ForeignKey(User, on_delete=models.CASCADE, related_name='sent_messages')
    recipient = models.ForeignKey(User, on_delete=models.CASCADE, related_name='received_messages', null=True, blank=True)
    client = models.ForeignKey(Client, on_delete=models.SET_NULL, null=True, blank=True, related_name='messages')
    parent = models.ForeignKey('self', on_delete=models.CASCADE, null=True, blank=True, related_name='replies')
    is_broadcast = models.BooleanField(default=False)
    
    message_type = models.CharField(max_length=20, choices=MESSAGE_TYPES, default='GENERAL')
    subject = models.CharField(max_length=200)
    content = models.TextField()
    
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='OPEN')
    priority = models.CharField(max_length=20, choices=PRIORITY_CHOICES, default='NORMAL')
    
    is_read = models.BooleanField(default=False)
    read_at = models.DateTimeField(null=True, blank=True)
    is_pinned = models.BooleanField(default=False)
    due_date = models.DateTimeField(null=True, blank=True)
    
    mentions = models.ManyToManyField(User, related_name='mentioned_in_messages', blank=True)
    template_used = models.ForeignKey('MessageTemplate', on_delete=models.SET_NULL, null=True, blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['-is_pinned', '-created_at']
    
    def __str__(self):
        return f"{self.sender.username} → {self.recipient.username if self.recipient else 'All'}: {self.subject}"
    
    @property
    def is_overdue(self):
        if self.due_date and self.status not in ['RESOLVED', 'CLOSED']:
            return timezone.now() > self.due_date
        return False
    
    @property
    def reply_count(self):
        return self.replies.count()


class MessageAttachment(models.Model):
    message = models.ForeignKey(InternalMessage, on_delete=models.CASCADE, related_name='attachments')
    file = models.FileField(upload_to='message_attachments/%Y/%m/')
    filename = models.CharField(max_length=255)
    file_type = models.CharField(max_length=50)
    file_size = models.IntegerField()
    uploaded_at = models.DateTimeField(auto_now_add=True)
    uploaded_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    
    def __str__(self):
        return f"{self.filename} on {self.message.subject}"
    
    @property
    def is_image(self):
        return self.file_type.startswith('image')
    
    @property
    def size_display(self):
        if self.file_size < 1024:
            return f"{self.file_size} B"
        elif self.file_size < 1024 * 1024:
            return f"{self.file_size / 1024:.1f} KB"
        else:
            return f"{self.file_size / (1024 * 1024):.1f} MB"


class MessageTemplate(models.Model):
    name = models.CharField(max_length=100)
    category = models.CharField(max_length=50, choices=[
        ('COMPLAINT', 'Client Complaint'),
        ('GENERAL', 'General'),
        ('SHIFT', 'Shift Handover'),
        ('MAINTENANCE', 'Maintenance'),
    ])
    subject_template = models.CharField(max_length=200)
    content_template = models.TextField()
    default_priority = models.CharField(max_length=20, choices=InternalMessage.PRIORITY_CHOICES, default='NORMAL')
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['category', 'name']
    
    def __str__(self):
        return f"{self.name} ({self.category})"


class ShiftNote(models.Model):
    SHIFT_CHOICES = [
        ('MORNING', 'Morning (6AM - 2PM)'),
        ('AFTERNOON', 'Afternoon (2PM - 10PM)'),
        ('NIGHT', 'Night (10PM - 6AM)'),
    ]
    
    author = models.ForeignKey(User, on_delete=models.CASCADE, related_name='shift_notes')
    shift = models.CharField(max_length=20, choices=SHIFT_CHOICES)
    shift_date = models.DateField()
    notes = models.TextField()
    incidents = models.TextField(blank=True)
    handover_notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['-shift_date', '-created_at']
    
    def __str__(self):
        return f"{self.author.username} - {self.shift} - {self.shift_date}"


class Subscription(models.Model):
    PLAN_CHOICES = [
        ('DAILY', 'Daily (Expires Midnight)'),
        ('WEEKLY', 'Weekly (7 Days)'),
        ('MONTHLY', 'Monthly (30 Days)'),
    ]

    PRICE_MAP = {
        'DAILY': 10.00,
        'WEEKLY': 50.00,
        'MONTHLY': 150.00,
    }

    DURATION_MAP = {
        'DAILY': 1,
        'WEEKLY': 7,
        'MONTHLY': 30,
    }

    client = models.ForeignKey(Client, on_delete=models.CASCADE, related_name='subscriptions')
    plan_type = models.CharField(max_length=10, choices=PLAN_CHOICES)
    start_date = models.DateTimeField(auto_now_add=True)
    expiry_date = models.DateTimeField(blank=True, null=True)
    amount_paid = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='created_subscriptions')

    def calculate_expiry_from_now(self):
        now = timezone.localtime()
        expiry = now.replace(hour=23, minute=59, second=59, microsecond=0)
        days_to_add = self.DURATION_MAP.get(self.plan_type, 0)
        expiry = expiry + timedelta(days=days_to_add)
        return expiry

    def calculate_expiry_from_date(self, base_date):
        base_date_only = base_date.date()
        days_to_add = self.DURATION_MAP.get(self.plan_type, 0)
        expiry_date = base_date_only + timedelta(days=days_to_add)
        expiry = datetime.combine(
            expiry_date, 
            datetime.max.time().replace(hour=23, minute=59, second=59, microsecond=0)
        )
        expiry = timezone.make_aware(expiry, timezone.get_current_timezone())
        return expiry

    def save(self, *args, **kwargs):
        if self._state.adding:
            if not self.expiry_date:
                self.expiry_date = self.calculate_expiry_from_now()
            self.amount_paid = self.PRICE_MAP.get(self.plan_type, 0.00)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.client.full_name} - {self.plan_type}"

    @property
    def is_active(self):
        return timezone.now() <= self.expiry_date


class AccessPass(models.Model):
    subscription = models.ForeignKey(Subscription, on_delete=models.CASCADE, related_name='access_passes')
    token_string = models.CharField(max_length=255, unique=True)
    generated_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(blank=True, null=True)
    is_used = models.BooleanField(default=False)

    def save(self, *args, **kwargs):
        if self._state.adding:
            self.expires_at = timezone.now() + timedelta(hours=24)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"Pass for {self.subscription.client.full_name}"


class AuditLog(models.Model):
    ACTION_CHOICES = [
        ('REGISTER', 'Registered Client'),
        ('SCAN', 'Scanned QR Code'),
        ('VIEW', 'Viewed Client'),
        ('EDIT', 'Edited Client'),
        ('BAN', 'Banned Client'),
        ('UNBAN', 'Unbanned Client'),
        ('LOGIN', 'Logged In'),
        ('LOGOUT', 'Logged Out'),
    ]
    
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='audit_logs')
    action = models.CharField(max_length=20, choices=ACTION_CHOICES)
    client = models.ForeignKey(Client, on_delete=models.SET_NULL, null=True, blank=True)
    details = models.TextField(blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    timestamp = models.DateTimeField(auto_now_add=True)
    
    def __str__(self):
        return f"{self.user.username} - {self.get_action_display()} - {self.timestamp}"
    
    class Meta:
        ordering = ['-timestamp']


class ClientPIN(models.Model):
    """Temporary PIN for client self-service portal verification"""
    client = models.ForeignKey(Client, on_delete=models.CASCADE, related_name='pins')
    pin_code = models.CharField(max_length=6)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    is_used = models.BooleanField(default=False)
    
    def __str__(self):
        return f"PIN for {self.client.full_name} - {self.pin_code}"
    
    @property
    def is_valid(self):
        return not self.is_used and timezone.now() <= self.expires_at
    
    @classmethod
    def generate_pin(cls, client):
        pin = ''.join(random.choices(string.digits, k=6))
        return cls.objects.create(
            client=client,
            pin_code=pin,
            expires_at=timezone.now() + timedelta(minutes=10)
        )