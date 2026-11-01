from django.shortcuts import redirect
from django.contrib import messages
from functools import wraps


def owner_only(view_func):
    """Only allow OWNER role to access this view"""
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect('login')
        if not request.user.is_owner:
            messages.error(request, "You don't have permission to access this page.")
            return redirect('staff_dashboard')
        return view_func(request, *args, **kwargs)
    return wrapper


def can_register_clients(view_func):
    """Allow OWNER, MANAGER, or RECEPTIONIST"""
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect('login')
        if not request.user.can_register_clients:
            messages.error(request, "You don't have permission to register clients.")
            return redirect('staff_dashboard')
        return view_func(request, *args, **kwargs)
    return wrapper


def can_scan_qr(view_func):
    """Allow OWNER, MANAGER, or SECURITY"""
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect('login')
        if not request.user.can_scan_qr:
            messages.error(request, "You don't have permission to scan QR codes.")
            return redirect('staff_dashboard')
        return view_func(request, *args, **kwargs)
    return wrapper


def staff_only(view_func):
    """Allow any authenticated staff member"""
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect('login')
        return view_func(request, *args, **kwargs)
    return wrapper
