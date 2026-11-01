from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.utils import timezone
from .models import (
    Client, Subscription, AccessPass, User, AuditLog, 
    ClientPIN, ClientNote, InternalMessage, MessageAttachment, 
    MessageTemplate, ShiftNote
)


# ===== CUSTOM USER ADMIN =====
@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display = ('username', 'email', 'role', 'phone_number', 'can_view_all_clients', 'is_active', 'date_joined')
    list_filter = ('role', 'is_active', 'can_view_all_clients', 'date_joined')
    search_fields = ('username', 'email', 'phone_number')
    ordering = ('-date_joined',)
    
    fieldsets = (
        (None, {'fields': ('username', 'password')}),
        ('Personal info', {'fields': ('first_name', 'last_name', 'email', 'phone_number')}),
        ('Permissions', {'fields': ('role', 'can_view_all_clients', 'is_active', 'is_staff', 'is_superuser', 'groups', 'user_permissions')}),
        ('Important dates', {'fields': ('last_login', 'date_joined')}),
    )
    
    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': ('username', 'password1', 'password2', 'role', 'phone_number', 'can_view_all_clients', 'is_active', 'is_staff'),
        }),
    )


# ===== CLIENT NOTE INLINE =====
class ClientNoteInline(admin.TabularInline):
    model = ClientNote
    extra = 1
    readonly_fields = ('author', 'created_at')
    fields = ('content', 'author', 'created_at')
    
    def save_model(self, request, obj, form, change):
        # Auto-fill the author if it's a new note
        if not obj.author and request.user.is_authenticated:
            obj.author = request.user
        super().save_model(request, obj, form, change)


# ===== CLIENT ADMIN =====
@admin.register(Client)
class ClientAdmin(admin.ModelAdmin):
    list_display = ('full_name', 'whatsapp_number', 'email', 'is_subscribed', 'is_banned', 'created_at')
    list_filter = ('is_active', 'is_banned', 'created_at')
    search_fields = ('full_name', 'whatsapp_number', 'email', 'tags')
    readonly_fields = ('created_at', 'updated_at')
    inlines = [ClientNoteInline]  # <-- This allows adding notes directly on the client page
    
    fieldsets = (
        ('Client Information', {
            'fields': ('full_name', 'whatsapp_number', 'email', 'profile_photo')
        }),
        ('Status & Moderation', {
            'fields': ('is_active', 'is_banned', 'ban_reason')
        }),
        ('Internal Metadata', {
            'fields': ('tags', 'created_by', 'created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    
    def is_subscribed(self, obj):
        return obj.is_subscribed
    is_subscribed.boolean = True
    is_subscribed.short_description = 'Has Active Sub'
    
    actions = ['ban_clients', 'unban_clients']
    
    def ban_clients(self, request, queryset):
        count = queryset.update(is_banned=True, ban_reason='Banned by admin')
        self.message_user(request, f'{count} clients banned.')
    ban_clients.short_description = 'Ban selected clients'
    
    def unban_clients(self, request, queryset):
        count = queryset.update(is_banned=False, ban_reason='')
        self.message_user(request, f'{count} clients unbanned.')
    unban_clients.short_description = 'Unban selected clients'


# ===== SUBSCRIPTION ADMIN =====
@admin.register(Subscription)
class SubscriptionAdmin(admin.ModelAdmin):
    list_display = ('client', 'plan_type', 'start_date', 'expiry_date', 'amount_paid', 'is_active')
    list_filter = ('plan_type', 'start_date', 'expiry_date')
    search_fields = ('client__full_name', 'client__whatsapp_number', 'client__email')
    readonly_fields = ('start_date',)
    raw_id_fields = ('client', 'created_by')
    
    def is_active(self, obj):
        return obj.is_active
    is_active.boolean = True
    is_active.short_description = 'Currently Active'


# ===== ACCESS PASS ADMIN =====
@admin.register(AccessPass)
class AccessPassAdmin(admin.ModelAdmin):
    list_display = ('subscription', 'generated_at', 'expires_at', 'is_used', 'is_valid')
    list_filter = ('is_used', 'generated_at')
    search_fields = ('subscription__client__full_name', 'token_string')
    readonly_fields = ('generated_at', 'expires_at')
    raw_id_fields = ('subscription',)
    
    def is_valid(self, obj):
        return timezone.now() <= obj.expires_at
    is_valid.boolean = True
    is_valid.short_description = 'Valid Now'


# ===== AUDIT LOG ADMIN =====
@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ('timestamp', 'user', 'action', 'client', 'ip_address')
    list_filter = ('action', 'timestamp', 'user')
    search_fields = ('user__username', 'client__full_name', 'details')
    readonly_fields = ('timestamp',)
    raw_id_fields = ('user', 'client')
    
    def has_add_permission(self, request):
        return False
    
    def has_change_permission(self, request, obj=None):
        return False


# ===== CLIENT PIN ADMIN =====
@admin.register(ClientPIN)
class ClientPINAdmin(admin.ModelAdmin):
    list_display = ('client', 'pin_code', 'created_at', 'expires_at', 'is_used', 'is_valid')
    list_filter = ('is_used', 'created_at')
    search_fields = ('client__full_name', 'client__whatsapp_number', 'client__email', 'pin_code')
    readonly_fields = ('created_at', 'expires_at')
    raw_id_fields = ('client',)
    
    def is_valid(self, obj):
        return obj.is_valid
    is_valid.boolean = True
    is_valid.short_description = 'Valid Now'
    
    def has_add_permission(self, request):
        return False
    
    def has_change_permission(self, request, obj=None):
        return False


# ===== INTERNAL MESSAGE ADMIN =====
@admin.register(InternalMessage)
class InternalMessageAdmin(admin.ModelAdmin):
    list_display = ('created_at', 'sender', 'recipient', 'subject', 'message_type', 'status', 'priority')
    list_filter = ('message_type', 'status', 'priority', 'created_at')
    search_fields = ('subject', 'content', 'sender__username', 'recipient__username')
    readonly_fields = ('created_at', 'updated_at', 'read_at')
    raw_id_fields = ('sender', 'recipient', 'client', 'parent')


# ===== MESSAGE TEMPLATE ADMIN =====
@admin.register(MessageTemplate)
class MessageTemplateAdmin(admin.ModelAdmin):
    list_display = ('name', 'category', 'default_priority', 'is_active', 'created_by')
    list_filter = ('category', 'is_active')
    search_fields = ('name', 'subject_template', 'content_template')


# ===== SHIFT NOTE ADMIN =====
@admin.register(ShiftNote)
class ShiftNoteAdmin(admin.ModelAdmin):
    list_display = ('shift_date', 'shift', 'author', 'created_at')
    list_filter = ('shift', 'shift_date')
    search_fields = ('author__username', 'notes', 'incidents')
    readonly_fields = ('created_at',)
    raw_id_fields = ('author',)
