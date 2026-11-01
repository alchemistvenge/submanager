from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.utils import timezone

from .models import Client, Subscription, AccessPass, AuditLog, ClientNote
from .decorators import staff_only, can_register_clients
from .services import generate_dynamic_qr_pass
from .utils import log_action


def _client_ip(request):
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        return x_forwarded_for.split(',')[0]
    return request.META.get('REMOTE_ADDR')


def _can_manage(user):
    """Only Owner, Manager, or users explicitly granted client access."""
    return (
        user.is_authenticated
        and (user.is_owner or user.is_manager or user.can_view_all_clients)
    )


@staff_only
def client_profile(request, client_id):
    """Full client profile with notes, tags, ban controls and history."""
    client = get_object_or_404(Client, pk=client_id)
    can_manage = _can_manage(request.user)

    if request.method == 'POST':
        action = request.POST.get('action')

        if action == 'add_note' and can_manage:
            content = request.POST.get('note_content', '').strip()
            if content:
                ClientNote.objects.create(
                    client=client,
                    author=request.user,
                    content=content
                )
                log_action(
                    request.user, 'EDIT', client=client,
                    details=f'Added note: {content[:50]}...',
                    ip_address=_client_ip(request)
                )
                messages.success(request, 'Note added successfully.')
            else:
                messages.error(request, 'Note cannot be empty.')

        elif action == 'tags' and can_manage:
            client.tags = request.POST.get('tags', '').strip()
            client.save()
            log_action(
                request.user, 'EDIT', client=client,
                details=f'Updated tags: {client.tags}',
                ip_address=_client_ip(request)
            )
            messages.success(request, 'Tags saved.')

        elif action == 'ban' and can_manage:
            reason = request.POST.get('ban_reason', '').strip()
            if not reason:
                messages.error(request, 'You must provide a reason for the ban.')
            else:
                client.is_banned = True
                client.ban_reason = reason
                client.save()
                log_action(
                    request.user, 'BAN', client=client,
                    details=reason, ip_address=_client_ip(request)
                )
                messages.success(request, f'{client.full_name} has been BANNED.')

        elif action == 'unban' and can_manage:
            client.is_banned = False
            client.ban_reason = ''
            client.save()
            log_action(
                request.user, 'UNBAN', client=client,
                details='Ban removed by staff', ip_address=_client_ip(request)
            )
            messages.success(request, f'{client.full_name} has been UNBANNED.')

        return redirect('client_detail', client_id=client.pk)

    # Build context
    subscriptions = client.subscriptions.order_by('-start_date')[:20]
    raw_passes = AccessPass.objects.filter(
        subscription__client=client
    ).select_related('subscription').order_by('-generated_at')[:10]
    
    notes = client.notes.select_related('author').all()

    now = timezone.now()
    pass_list = []
    for p in raw_passes:
        pass_list.append({
            'id': p.id,
            'generated_at': p.generated_at,
            'expires_at': p.expires_at,
            'is_valid': now <= p.expires_at and p.subscription.is_active,
            'plan': p.subscription.get_plan_type_display(),
        })

    recent_scans = AuditLog.objects.filter(client=client, action='SCAN')[:10]

    context = {
        'client': client,
        'can_manage': can_manage,
        'can_see_financials': request.user.can_see_financials,
        'can_register': request.user.can_register_clients,
        'current_subscription': client.current_subscription,
        'subscriptions': subscriptions,
        'pass_list': pass_list,
        'recent_scans': recent_scans,
        'notes': notes,
    }

    return render(request, 'core/client_detail.html', context)


@staff_only
@can_register_clients
def regenerate_pass(request, client_id):
    """Issue a fresh 24-hour dynamic QR pass for an active client and email it"""
    if request.method != 'POST':
        return redirect('client_detail', client_id=client_id)

    client = get_object_or_404(Client, pk=client_id)

    if client.is_banned:
        messages.error(request, 'Cannot issue a pass to a banned client.')
        return redirect('client_detail', client_id=client.pk)

    subscription = client.current_subscription

    if not subscription:
        messages.error(request, 'No active subscription. Please register a payment first.')
        return redirect('client_detail', client_id=client.pk)

    # Generate pass and send email
    access_pass = generate_dynamic_qr_pass(subscription, send_email=True)

    log_action(
        request.user, 'EDIT', client=client,
        details=f'Generated fresh QR pass and emailed to {client.email or "no email"}',
        ip_address=_client_ip(request)
    )
    
    if client.email:
        messages.success(request, f'Fresh QR code generated and emailed to {client.email}.')
    else:
        messages.warning(request, 'QR code generated but client has no email on file.')

    return redirect('client_detail', client_id=client.pk)
