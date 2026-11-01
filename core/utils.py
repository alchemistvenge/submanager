from .models import AuditLog


def log_action(user, action, client=None, details="", ip_address=None):
    """Log a staff action for audit trail"""
    AuditLog.objects.create(
        user=user,
        action=action,
        client=client,
        details=details,
        ip_address=ip_address
    )
