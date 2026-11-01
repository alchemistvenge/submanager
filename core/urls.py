from django.urls import path
from . import views
from . import client_management as cm
from . import messaging

urlpatterns = [
    # Authentication
    path("login/", views.staff_login, name="login"),
    path("logout/", views.staff_logout, name="logout"),

    # Dashboard
    path("", views.staff_dashboard, name="staff_dashboard"),

    # Password Management
    path("password/change/", messaging.change_password, name="change_password"),
    path("staff/<int:user_id>/reset-password/", messaging.reset_staff_password, name="reset_staff_password"),

    # Client Management
    path("register/", views.register_client, name="register"),
    path("register/success/<int:subscription_id>/", views.registration_success, name="registration_success"),
    path("clients/", views.client_search, name="client_search"),
    path("clients/<int:client_id>/", cm.client_profile, name="client_detail"),
    path("clients/<int:client_id>/new-pass/", cm.regenerate_pass, name="regenerate_pass"),

    # Scanner
    path("scanner/", views.scanner_view, name="scanner_view"),
    path("api/scan/", views.scan_qr_api, name="scan_qr_api"),

    # Reports & Logs (Owner Only)
    path("reports/revenue/", views.revenue_report, name="revenue_report"),
    path("audit-logs/", views.audit_logs, name="audit_logs"),

    # Staff Management (Owner Only)
    path("staff/", views.staff_management, name="staff_management"),
    path("staff/create/", views.staff_create, name="staff_create"),
    path("staff/<int:user_id>/edit/", views.staff_edit, name="staff_edit"),
    path("staff/<int:user_id>/delete/", views.staff_delete, name="staff_delete"),

    # Export (Owner Only)
    path("export/clients/", views.export_clients_csv, name="export_clients_csv"),
    path("export/revenue/", views.export_revenue_csv, name="export_revenue_csv"),

    # Receipt
    path("receipt/<int:subscription_id>/", views.print_receipt, name="print_receipt"),

    # Messaging System
    path("messages/", messaging.message_inbox, name="message_inbox"),
    path("messages/send/", messaging.send_message, name="send_message"),
    path("messages/<int:message_id>/", messaging.view_message, name="view_message"),
    path("messages/<int:message_id>/reply/", messaging.reply_message, name="reply_message"),
    path("messages/<int:message_id>/status/", messaging.update_message_status, name="update_message_status"),
    path("messages/<int:message_id>/pin/", messaging.pin_message, name="pin_message"),
    path("messages/<int:message_id>/forward/", messaging.forward_message, name="forward_message"),
    path("messages/bulk/", messaging.bulk_actions, name="bulk_actions"),
    path("messages/broadcast/", messaging.send_broadcast, name="send_broadcast"),
    path("messages/analytics/", messaging.message_analytics, name="message_analytics"),
    
    # Shift Notes
    path("shift-notes/", messaging.shift_notes_list, name="shift_notes_list"),
    path("shift-notes/new/", messaging.shift_note_create, name="shift_note_create"),
    path("shift-notes/<int:note_id>/", messaging.shift_note_view, name="shift_note_view"),
    
    # Templates
    path("templates/", messaging.template_list, name="template_list"),
    path("templates/new/", messaging.template_create, name="template_create"),

    # Client Self-Service Portal (Public)
    path("portal/", views.client_portal, name="client_portal"),
    path("portal/send-pin/", views.client_portal_send_pin, name="client_portal_send_pin"),
    path("portal/verify/", views.client_portal_verify, name="client_portal_verify"),
    path("portal/dashboard/", views.client_dashboard, name="client_dashboard"),
    path("portal/logout/", views.client_portal_logout, name="client_portal_logout"),
]
