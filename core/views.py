from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib.auth import login, logout, authenticate
from django.contrib import messages
from django.db import transaction
from django.db.models import Sum, Count, Q
from django.utils import timezone
from django.http import JsonResponse, HttpResponse
from django.views.decorators.csrf import csrf_exempt
from datetime import timedelta, datetime
import json
import csv

from .models import Client, Subscription, AccessPass, User, AuditLog, ClientPIN
from .forms import ClientRegistrationForm, StaffLoginForm
from .services import generate_dynamic_qr_pass, send_client_pin
from .decorators import owner_only, can_register_clients, can_scan_qr, staff_only
from .utils import log_action
from .pagination import paginate


def get_client_ip(request):
    """Get the client's IP address"""
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        ip = x_forwarded_for.split(',')[0]
    else:
        ip = request.META.get('REMOTE_ADDR')
    return ip


# ===== AUTHENTICATION VIEWS =====

def staff_login(request):
    """Custom login view for staff"""
    if request.method == 'POST':
        form = StaffLoginForm(request.POST)
        if form.is_valid():
            username = form.cleaned_data['username']
            password = form.cleaned_data['password']
            user = authenticate(request, username=username, password=password)
            
            if user is not None:
                login(request, user)
                log_action(user, 'LOGIN', ip_address=get_client_ip(request))
                messages.success(request, f"Welcome back, {user.username}!")
                return redirect('staff_dashboard')
            else:
                messages.error(request, "Invalid username or password.")
    else:
        form = StaffLoginForm()
    
    return render(request, 'core/staff_login.html', {'form': form})


def staff_logout(request):
    """Logout view with audit logging"""
    if request.user.is_authenticated:
        log_action(request.user, 'LOGOUT', ip_address=get_client_ip(request))
    logout(request)
    messages.success(request, "You have been logged out.")
    return redirect('login')


# ===== DASHBOARD VIEWS =====

@staff_only
def staff_dashboard(request):
    """Main dashboard - shows different content based on role"""
    now = timezone.now()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    
    context = {
        'now': now,
        'today_start': today_start,
    }
    
    # Financial metrics (only for OWNER)
    if request.user.can_see_financials:
        today_revenue = Subscription.objects.filter(
            start_date__gte=today_start
        ).aggregate(total=Sum('amount_paid'))['total'] or 0
        
        week_start = today_start - timedelta(days=now.weekday())
        week_revenue = Subscription.objects.filter(
            start_date__gte=week_start
        ).aggregate(total=Sum('amount_paid'))['total'] or 0
        
        month_start = today_start.replace(day=1)
        month_revenue = Subscription.objects.filter(
            start_date__gte=month_start
        ).aggregate(total=Sum('amount_paid'))['total'] or 0
        
        context.update({
            'today_revenue': today_revenue,
            'week_revenue': week_revenue,
            'month_revenue': month_revenue,
        })
    
    # Customer metrics (for all staff)
    if request.user.can_view_all_clients or request.user.is_owner or request.user.is_manager:
        total_customers = Client.objects.count()
        active_customers = Client.objects.filter(
            subscriptions__expiry_date__gt=now
        ).distinct().count()
        
        context.update({
            'total_customers': total_customers,
            'active_customers': active_customers,
        })
    
    # Recent activity (for all staff)
    recent_registrations = Subscription.objects.select_related('client').order_by('-start_date')[:10]
    context['recent_registrations'] = recent_registrations
    
    return render(request, 'core/staff_dashboard.html', context)


# ===== CLIENT MANAGEMENT VIEWS =====

@can_register_clients
def register_client(request):
    """Register a new client or extend existing subscription"""
    if request.method == "POST":
        form = ClientRegistrationForm(request.POST, request.FILES)

        if form.is_valid():
            now = timezone.now()
            with transaction.atomic():
                number = form.cleaned_data["whatsapp_number"]
                name = form.cleaned_data["full_name"]
                email = form.cleaned_data.get("email", "").strip().lower()  # ✅ NEW: Get email
                photo = form.cleaned_data.get("profile_photo")
                plan_type = form.cleaned_data["plan_type"]

                # FIND the client first
                client = Client.objects.filter(whatsapp_number=number).first()

                if client is None:
                    # ✅ FIXED: Now includes email field
                    client = Client.objects.create(
                        full_name=name,
                        whatsapp_number=number,
                        email=email,  # ✅ NEW: Save email
                        created_by=request.user,
                    )
                    log_action(request.user, 'REGISTER', client=client, 
                             details=f"New client registered with email: {email or 'None'}", 
                             ip_address=get_client_ip(request))
                else:
                    # Update existing client
                    client.full_name = name
                    if email:  # Only update if new email provided
                        client.email = email
                    if photo:
                        client.profile_photo = photo
                    client.save()
                    log_action(request.user, 'EDIT', client=client, 
                             details=f"Client details updated", ip_address=get_client_ip(request))

                # EXTENSION LOGIC
                latest_active_sub = client.subscriptions.filter(
                    expiry_date__gt=now
                ).order_by('-expiry_date').first()

                if latest_active_sub:
                    base_date = latest_active_sub.expiry_date
                    new_expiry = Subscription(
                        client=client,
                        plan_type=plan_type
                    ).calculate_expiry_from_date(base_date)
                else:
                    new_expiry = None

                # Create the new subscription
                subscription = Subscription.objects.create(
                    client=client,
                    plan_type=plan_type,
                    expiry_date=new_expiry,
                    created_by=request.user,
                )

                # Generate QR code and send email
                access_pass = generate_dynamic_qr_pass(subscription, send_email=True)

            return redirect(
                "registration_success",
                subscription_id=subscription.pk,
            )

    else:
        form = ClientRegistrationForm()

    return render(request, "core/register.html", {
        "form": form,
        "prices": Subscription.PRICE_MAP,
    })


@login_required
def registration_success(request, subscription_id):
    """Show success page after registration"""
    subscription = get_object_or_404(
        Subscription.objects.select_related("client"),
        pk=subscription_id,
    )
    
    # Get the most recent access pass for this subscription
    latest_pass = subscription.access_passes.order_by('-generated_at').first()
    
    context = {
        "subscription": subscription,
        "latest_pass": latest_pass,
    }
    
    return render(request, "core/registration_success.html", context)


@staff_only
def client_search(request):
    """Search and filter clients"""
    query = request.GET.get('q', '')
    status_filter = request.GET.get('status', 'all')
    plan_filter = request.GET.get('plan', 'all')
    
    clients = Client.objects.all()
    
    # ✅ FIXED: Now searches by email too
    if query:
        clients = clients.filter(
            Q(full_name__icontains=query) | 
            Q(whatsapp_number__icontains=query) |
            Q(email__icontains=query)  # ✅ NEW: Search by email
        )
    
    if status_filter == 'active':
        clients = clients.filter(subscriptions__expiry_date__gt=timezone.now()).distinct()
    elif status_filter == 'expired':
        clients = clients.exclude(subscriptions__expiry_date__gt=timezone.now()).distinct()
    
    if plan_filter and plan_filter != 'all':
        clients = clients.filter(subscriptions__plan_type=plan_filter).distinct()
    
    # Order by most recently updated
    clients = clients.order_by('-updated_at')
    
    # Paginate
    pagination = paginate(request, clients, per_page=20)
    
    context = {
        'query': query,
        'status_filter': status_filter,
        'plan_filter': plan_filter,
        **pagination,
    }
    
    return render(request, 'core/client_search.html', context)


@staff_only
def client_detail(request, client_id):
    """View detailed client information"""
    client = get_object_or_404(Client, pk=client_id)
    
    # Check if user has permission to view this client
    if not (request.user.can_view_all_clients or request.user.is_owner or request.user.is_manager):
        messages.error(request, "You don't have permission to view this client.")
        return redirect('staff_dashboard')
    
    subscriptions = client.subscriptions.order_by('-start_date')
    access_passes = AccessPass.objects.filter(subscription__client=client).order_by('-generated_at')[:20]
    
    log_action(request.user, 'VIEW', client=client, ip_address=get_client_ip(request))
    
    context = {
        'client': client,
        'subscriptions': subscriptions,
        'access_passes': access_passes,
    }
    
    return render(request, 'core/client_detail.html', context)


# ===== SCANNER VIEWS =====

@can_scan_qr
def scanner_view(request):
    """QR code scanner interface"""
    return render(request, "core/scanner.html")


@csrf_exempt
def scan_qr_api(request):
    """API endpoint for QR code validation"""
    if request.method == "POST":
        try:
            data = json.loads(request.body)
            scanned_data = data.get("qr_data", "")
            
            if not scanned_data.startswith("SUB:") or "|TOKEN:" not in scanned_data:
                return JsonResponse({"status": "error", "reason": "Invalid QR Code Format"}, status=400)

            token_string = scanned_data.split("|TOKEN:")[1]

            try:
                access_pass = AccessPass.objects.select_related('subscription__client').get(token_string=token_string)
            except AccessPass.DoesNotExist:
                return JsonResponse({"status": "error", "reason": "QR Code Not Found in Database"}, status=404)

            # Check if QR token expired (24-hour rule)
            if timezone.now() > access_pass.expires_at:
                return JsonResponse({"status": "error", "reason": "QR Code Expired. Please request a new one on WhatsApp."}, status=403)

            # Check if subscription is active
            subscription = access_pass.subscription
            if not subscription.is_active:
                return JsonResponse({
                    "status": "error", 
                    "reason": f"Subscription Expired on {subscription.expiry_date.strftime('%b %d, %Y')}"
                }, status=403)

            # Check if client is banned
            client = subscription.client
            if client.is_banned:
                return JsonResponse({
                    "status": "error",
                    "reason": f"CLIENT BANNED: {client.ban_reason}"
                }, status=403)

            # SUCCESS
            photo_url = client.profile_photo.url if client.profile_photo else None
            
            # Log the scan
            if request.user.is_authenticated:
                log_action(request.user, 'SCAN', client=client, 
                         details=f"QR scan successful", ip_address=get_client_ip(request))
            
            return JsonResponse({
                "status": "success",
                "client_name": client.full_name,
                "plan": subscription.get_plan_type_display(),
                "photo_url": photo_url,
                "expires": subscription.expiry_date.strftime("%b %d, %Y at %H:%M")
            })

        except json.JSONDecodeError:
            return JsonResponse({"status": "error", "reason": "Invalid Request"}, status=400)
            
    return JsonResponse({"status": "error", "reason": "Method Not Allowed"}, status=405)


# ===== FINANCIAL REPORTS (OWNER ONLY) =====

@owner_only
def revenue_report(request):
    """Custom date range revenue report - only for owners"""
    if request.method == "POST":
        start_date = request.POST.get('start_date')
        end_date = request.POST.get('end_date')
        
        if start_date and end_date:
            start = timezone.make_aware(
                datetime.strptime(start_date, '%Y-%m-%d')
            )
            end = timezone.make_aware(
                datetime.strptime(end_date, '%Y-%m-%d').replace(hour=23, minute=59, second=59)
            )
            
            subscriptions = Subscription.objects.filter(
                start_date__range=(start, end)
            ).select_related('client')
            
            total_revenue = subscriptions.aggregate(total=Sum('amount_paid'))['total'] or 0
            
            breakdown = subscriptions.values('plan_type').annotate(
                count=Count('id'),
                total=Sum('amount_paid')
            ).order_by('plan_type')
            
            context = {
                'start_date': start_date,
                'end_date': end_date,
                'total_revenue': total_revenue,
                'breakdown': breakdown,
                'subscriptions': subscriptions,
                'has_results': True,
            }
            
            return render(request, 'core/revenue_report.html', context)
    
    return render(request, 'core/revenue_report.html', {'has_results': False})


# ===== AUDIT LOGS (OWNER ONLY) =====

@owner_only
def audit_logs(request):
    """View all staff actions - only for owners"""
    logs = AuditLog.objects.select_related('user', 'client').all()
    
    # Optional filters
    action_filter = request.GET.get('action', 'all')
    user_filter = request.GET.get('user', 'all')
    
    if action_filter and action_filter != 'all':
        logs = logs.filter(action=action_filter)
    if user_filter and user_filter != 'all':
        logs = logs.filter(user_id=user_filter)
    
    pagination = paginate(request, logs, per_page=50)
    
    # Get unique users for filter dropdown
    users = User.objects.filter(audit_logs__isnull=False).distinct()
    
    context = {
        'action_filter': action_filter,
        'user_filter': user_filter,
        'users': users,
        'actions': AuditLog.ACTION_CHOICES,
        **pagination,
    }
    
    return render(request, 'core/audit_logs.html', context)


# ===== STAFF MANAGEMENT (OWNER ONLY) =====

@owner_only
def staff_management(request):
    """View and manage all staff members"""
    staff_users = User.objects.exclude(id=request.user.id).order_by('-date_joined')
    pagination = paginate(request, staff_users, per_page=20)
    
    context = {
        **pagination,
    }
    return render(request, 'core/staff_management.html', context)


@owner_only
def staff_create(request):
    """Create a new staff member"""
    if request.method == 'POST':
        username = request.POST.get('username')
        password = request.POST.get('password')
        role = request.POST.get('role')
        phone_number = request.POST.get('phone_number', '')
        can_view_all_clients = request.POST.get('can_view_all_clients') == 'on'
        
        if User.objects.filter(username=username).exists():
            messages.error(request, "Username already exists.")
            return redirect('staff_management')
        
        user = User.objects.create_user(
            username=username,
            password=password,
            role=role,
            phone_number=phone_number,
            can_view_all_clients=can_view_all_clients
        )
        
        log_action(request.user, 'EDIT', details=f"Created new staff member: {username} ({role})", ip_address=get_client_ip(request))
        messages.success(request, f"Staff member '{username}' created successfully.")
        return redirect('staff_management')
    
    return render(request, 'core/staff_create.html')


@owner_only
def staff_edit(request, user_id):
    """Edit an existing staff member's permissions"""
    user_to_edit = get_object_or_404(User, pk=user_id)
    
    if request.method == 'POST':
        new_role = request.POST.get('role')
        user_to_edit.role = new_role
        
        user_to_edit.phone_number = request.POST.get('phone_number', '')
        user_to_edit.can_view_all_clients = request.POST.get('can_view_all_clients') == 'on'
        
        new_password = request.POST.get('password')
        if new_password:
            user_to_edit.set_password(new_password)
        
        user_to_edit.save()
        
        log_action(request.user, 'EDIT', 
                  details=f"Edited staff member: {user_to_edit.username} (Role: {new_role})", 
                  ip_address=get_client_ip(request))
        
        messages.success(request, f"Staff member '{user_to_edit.username}' updated successfully.")
        return redirect('staff_management')
    
    context = {
        'user_to_edit': user_to_edit,
    }
    return render(request, 'core/staff_edit.html', context)


@owner_only
def staff_delete(request, user_id):
    """Delete a staff member"""
    if request.method == 'POST':
        user_to_delete = get_object_or_404(User, pk=user_id)
        
        if user_to_delete.id == request.user.id:
            messages.error(request, "You cannot delete your own account.")
            return redirect('staff_management')
        
        username = user_to_delete.username
        user_to_delete.delete()
        
        log_action(request.user, 'EDIT', details=f"Deleted staff member: {username}", ip_address=get_client_ip(request))
        messages.success(request, f"Staff member '{username}' deleted.")
        
    return redirect('staff_management')


# ===== EXPORT VIEWS =====

@owner_only
def export_clients_csv(request):
    """Export all clients to CSV"""
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="clients_{datetime.now().strftime("%Y%m%d")}.csv"'
    
    writer = csv.writer(response)
    writer.writerow(['Name', 'WhatsApp', 'Email', 'Status', 'Current Plan', 'Expiry Date', 'Tags', 'Created'])
    
    clients = Client.objects.all().order_by('-created_at')
    
    for client in clients:
        current_sub = client.current_subscription
        status = 'Active' if client.is_subscribed else 'Expired'
        plan = current_sub.get_plan_type_display() if current_sub else 'None'
        expiry = current_sub.expiry_date.strftime('%Y-%m-%d %H:%M') if current_sub else ''
        
        writer.writerow([
            client.full_name,
            client.whatsapp_number,
            client.email or '',
            status,
            plan,
            expiry,
            client.tags,
            client.created_at.strftime('%Y-%m-%d %H:%M')
        ])
    
    return response


@owner_only
def export_revenue_csv(request):
    """Export revenue report to CSV"""
    start_date = request.GET.get('start')
    end_date = request.GET.get('end')
    
    if not start_date or not end_date:
        messages.error(request, "Please provide start and end dates.")
        return redirect('revenue_report')
    
    start = timezone.make_aware(datetime.strptime(start_date, '%Y-%m-%d'))
    end = timezone.make_aware(datetime.strptime(end_date, '%Y-%m-%d').replace(hour=23, minute=59, second=59))
    
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="revenue_{start_date}_to_{end_date}.csv"'
    
    writer = csv.writer(response)
    writer.writerow(['Date', 'Client Name', 'WhatsApp', 'Email', 'Plan', 'Amount Paid'])
    
    subscriptions = Subscription.objects.filter(
        start_date__range=(start, end)
    ).select_related('client').order_by('-start_date')
    
    for sub in subscriptions:
        writer.writerow([
            sub.start_date.strftime('%Y-%m-%d %H:%M'),
            sub.client.full_name,
            sub.client.whatsapp_number,
            sub.client.email or '',
            sub.get_plan_type_display(),
            f"${sub.amount_paid}"
        ])
    
    return response


@login_required
def print_receipt(request, subscription_id):
    """Print-friendly receipt for a subscription"""
    subscription = get_object_or_404(
        Subscription.objects.select_related('client'),
        pk=subscription_id
    )
    
    context = {
        'subscription': subscription,
    }
    
    return render(request, 'core/receipt.html', context)


# ===== CLIENT SELF-SERVICE PORTAL =====

def client_portal(request):
    """Entry point for client self-service portal"""
    return render(request, 'core/client_portal.html')


def client_portal_send_pin(request):
    """Send PIN to client's email"""
    if request.method == 'POST':
        email = request.POST.get('email', '').strip().lower()
        
        try:
            client = Client.objects.get(email=email)
            
            # Generate PIN
            pin_obj = ClientPIN.generate_pin(client)
            
            # Send PIN via email
            send_client_pin(client, pin_obj.pin_code)
            
            # Store client ID in session for verification
            request.session['pending_client_id'] = client.id
            
            messages.success(request, f"Verification code sent to {email}. Check your inbox!")
            return redirect('client_portal_verify')
            
        except Client.DoesNotExist:
            messages.error(request, "This email is not registered in our system.")
            return redirect('client_portal')
    
    return redirect('client_portal')


def client_portal_verify(request):
    """Verify PIN and grant access to client dashboard"""
    client_id = request.session.get('pending_client_id')
    
    if not client_id:
        messages.error(request, "Please request a PIN first.")
        return redirect('client_portal')
    
    if request.method == 'POST':
        pin_code = request.POST.get('pin_code', '').strip()
        
        try:
            pin_obj = ClientPIN.objects.get(
                client_id=client_id,
                pin_code=pin_code,
                is_used=False
            )
            
            if not pin_obj.is_valid:
                messages.error(request, "PIN has expired. Please request a new one.")
                return redirect('client_portal')
            
            # Mark PIN as used
            pin_obj.is_used = True
            pin_obj.save()
            
            # Grant access
            request.session['client_portal_access'] = client_id
            del request.session['pending_client_id']
            
            return redirect('client_dashboard')
            
        except ClientPIN.DoesNotExist:
            messages.error(request, "Invalid PIN. Please try again.")
    
    return render(request, 'core/client_portal_verify.html')


def client_dashboard(request):
    """Client's personal dashboard"""
    client_id = request.session.get('client_portal_access')
    
    if not client_id:
        messages.error(request, "Please verify your identity first.")
        return redirect('client_portal')
    
    client = get_object_or_404(Client, pk=client_id)
    
    # Get current active subscription
    current_sub = client.current_subscription
    
    # Get latest access pass for current subscription
    latest_pass = None
    if current_sub:
        latest_pass = current_sub.access_passes.filter(
            expires_at__gt=timezone.now()
        ).order_by('-generated_at').first()
    
    # Get subscription history
    subscriptions = client.subscriptions.order_by('-start_date')[:10]
    
    context = {
        'client': client,
        'current_subscription': current_sub,
        'latest_pass': latest_pass,
        'subscriptions': subscriptions,
    }
    
    return render(request, 'core/client_dashboard.html', context)


def client_portal_logout(request):
    """Logout from client portal"""
    if 'client_portal_access' in request.session:
        del request.session['client_portal_access']
    
    messages.success(request, "You have been logged out.")
    return redirect('client_portal')