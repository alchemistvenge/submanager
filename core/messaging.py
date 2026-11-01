from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.forms import PasswordChangeForm
from django.db.models import Q, Count
from django.utils import timezone
from django.http import JsonResponse
from datetime import datetime, timedelta

from .models import User, InternalMessage, Client, MessageAttachment, MessageTemplate, ShiftNote
from .utils import log_action


def _client_ip(request):
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        return x_forwarded_for.split(',')[0]
    return request.META.get('REMOTE_ADDR')


def _parse_mentions(content):
    """Extract @mentions from message content"""
    import re
    mentions = re.findall(r'@(\w+)', content)
    return User.objects.filter(username__in=mentions)


@login_required
def change_password(request):
    """Allow any logged-in user to change their own password"""
    if request.method == 'POST':
        form = PasswordChangeForm(request.user, request.POST)
        if form.is_valid():
            user = form.save()
            update_session_auth_hash(request, user)
            log_action(request.user, 'EDIT', details='Changed own password', ip_address=_client_ip(request))
            messages.success(request, 'Your password was successfully updated!')
            return redirect('staff_dashboard')
    else:
        form = PasswordChangeForm(request.user)
    
    return render(request, 'core/change_password.html', {'form': form})


@login_required
def reset_staff_password(request, user_id):
    """Owner can reset any staff member's password"""
    if not request.user.is_owner:
        messages.error(request, 'Only owners can reset passwords.')
        return redirect('staff_dashboard')
    
    target_user = get_object_or_404(User, pk=user_id)
    
    if request.method == 'POST':
        new_password = request.POST.get('new_password', '')
        confirm_password = request.POST.get('confirm_password', '')
        
        if not new_password:
            messages.error(request, 'Password cannot be empty.')
        elif new_password != confirm_password:
            messages.error(request, 'Passwords do not match.')
        elif len(new_password) < 8:
            messages.error(request, 'Password must be at least 8 characters.')
        else:
            target_user.set_password(new_password)
            target_user.save()
            log_action(
                request.user, 'EDIT',
                details=f'Reset password for {target_user.username}',
                ip_address=_client_ip(request)
            )
            messages.success(request, f'Password for {target_user.username} has been reset.')
            return redirect('staff_management')
    
    return render(request, 'core/reset_password.html', {'target_user': target_user})


@login_required
def message_inbox(request):
    """Enhanced inbox with filters, search, and status tracking"""
    # Get filter parameters
    status_filter = request.GET.get('status', 'all')
    type_filter = request.GET.get('type', 'all')
    priority_filter = request.GET.get('priority', 'all')
    search_query = request.GET.get('q', '')
    show_overdue = request.GET.get('overdue', '') == 'true'
    
    # Base queryset
    received = InternalMessage.objects.filter(
        Q(recipient=request.user) | Q(is_broadcast=True)
    ).select_related('sender', 'client', 'parent')
    
    # Apply filters
    if status_filter and status_filter != 'all':
        received = received.filter(status=status_filter)
    if type_filter and type_filter != 'all':
        received = received.filter(message_type=type_filter)
    if priority_filter and priority_filter != 'all':
        received = received.filter(priority=priority_filter)
    if show_overdue:
        received = received.filter(due_date__lt=timezone.now(), status__in=['OPEN', 'IN_PROGRESS'])
    if search_query:
        received = received.filter(
            Q(subject__icontains=search_query) | 
            Q(content__icontains=search_query) |
            Q(client__full_name__icontains=search_query)
        )
    
    # Mark messages as read when viewing inbox
    InternalMessage.objects.filter(
        recipient=request.user,
        is_read=False
    ).update(is_read=True, read_at=timezone.now())
    
    # Get sent messages
    sent = InternalMessage.objects.filter(sender=request.user).select_related('recipient', 'client')
    
    # Get open issues count
    open_issues = InternalMessage.objects.filter(
        recipient=request.user,
        status__in=['OPEN', 'IN_PROGRESS'],
        parent__isnull=True
    ).count()
    
    context = {
        'received_messages': received,
        'sent_messages': sent,
        'status_filter': status_filter,
        'type_filter': type_filter,
        'priority_filter': priority_filter,
        'search_query': search_query,
        'show_overdue': show_overdue,
        'open_issues': open_issues,
        'status_choices': InternalMessage.STATUS_CHOICES,
        'type_choices': InternalMessage.MESSAGE_TYPES,
        'priority_choices': InternalMessage.PRIORITY_CHOICES,
    }
    
    return render(request, 'core/message_inbox.html', context)


@login_required
def send_message(request):
    """Send a message with all enhanced features"""
    if request.method == 'POST':
        recipient_id = request.POST.get('recipient_id')
        message_type = request.POST.get('message_type', 'GENERAL')
        subject = request.POST.get('subject', '').strip()
        content = request.POST.get('content', '').strip()
        client_id = request.POST.get('client_id')
        priority = request.POST.get('priority', 'NORMAL')
        due_date_str = request.POST.get('due_date')
        is_broadcast = request.POST.get('is_broadcast') == 'on'
        template_id = request.POST.get('template_id')
        
        if not subject or not content:
            messages.error(request, 'Subject and message are required.')
            return redirect('send_message')
        
        # Determine recipient
        recipient = None
        if recipient_id and not is_broadcast:
            recipient = get_object_or_404(User, pk=recipient_id)
        
        # Get client if specified
        client = None
        if client_id:
            client = get_object_or_404(Client, pk=client_id)
        
        # Parse due date
        due_date = None
        if due_date_str:
            try:
                due_date = timezone.make_aware(datetime.strptime(due_date_str, '%Y-%m-%dT%H:%M'))
            except ValueError:
                pass
        
        # Get template if used
        template = None
        if template_id:
            template = get_object_or_404(MessageTemplate, pk=template_id)
        
        # Create message
        message_obj = InternalMessage.objects.create(
            sender=request.user,
            recipient=recipient,
            client=client,
            message_type=message_type,
            subject=subject,
            content=content,
            priority=priority,
            due_date=due_date,
            is_broadcast=is_broadcast,
            template_used=template
        )
        
        # Handle mentions
        mentioned_users = _parse_mentions(content)
        message_obj.mentions.set(mentioned_users)
        
        # Handle attachments
        files = request.FILES.getlist('attachments')
        for file in files:
            MessageAttachment.objects.create(
                message=message_obj,
                file=file,
                filename=file.name,
                file_type=file.content_type,
                file_size=file.size,
                uploaded_by=request.user
            )
        
        log_action(
            request.user, 'EDIT',
            details=f'Sent message: {subject}',
            ip_address=_client_ip(request)
        )
        
        messages.success(request, 'Message sent successfully.')
        return redirect('message_inbox')
    
    # Get available recipients
    recipients = User.objects.exclude(id=request.user.id)
    
    # Get optional client ID from query params
    client_id = request.GET.get('client_id')
    client = None
    if client_id:
        client = get_object_or_404(Client, pk=client_id)
    
    # Get templates
    templates = MessageTemplate.objects.filter(is_active=True)
    
    context = {
        'recipients': recipients,
        'client': client,
        'message_types': InternalMessage.MESSAGE_TYPES,
        'priority_choices': InternalMessage.PRIORITY_CHOICES,
        'templates': templates,
    }
    
    return render(request, 'core/send_message.html', context)


@login_required
def view_message(request, message_id):
    """View a specific message with threading"""
    message_obj = get_object_or_404(
        InternalMessage.objects.select_related('sender', 'recipient', 'client', 'parent'),
        pk=message_id
    )
    
    # Permission check
    can_view = (
        message_obj.sender == request.user or
        message_obj.recipient == request.user or
        message_obj.is_broadcast or
        request.user in message_obj.mentions.all() or
        request.user.is_owner or
        request.user.is_manager
    )
    
    if not can_view:
        messages.error(request, 'You do not have permission to view this message.')
        return redirect('message_inbox')
    
    # Mark as read if recipient is viewing
    if message_obj.recipient == request.user and not message_obj.is_read:
        message_obj.is_read = True
        message_obj.read_at = timezone.now()
        message_obj.save()
    
    # Get replies (thread)
    replies = message_obj.replies.select_related('sender').order_by('created_at')
    
    # Get attachments
    attachments = message_obj.attachments.all()
    
    context = {
        'message_obj': message_obj,
        'replies': replies,
        'attachments': attachments,
    }
    
    return render(request, 'core/view_message.html', context)


@login_required
def reply_message(request, message_id):
    """Reply to a message (threading)"""
    parent = get_object_or_404(InternalMessage, pk=message_id)
    
    if request.method == 'POST':
        content = request.POST.get('content', '').strip()
        
        if not content:
            messages.error(request, 'Reply cannot be empty.')
            return redirect('view_message', message_id=parent.pk)
        
        # Create reply
        reply = InternalMessage.objects.create(
            sender=request.user,
            recipient=parent.sender,  # Reply goes to original sender
            parent=parent,
            client=parent.client,
            message_type=parent.message_type,
            subject=f"Re: {parent.subject}",
            content=content,
            priority=parent.priority,
        )
        
        # Handle mentions
        mentioned_users = _parse_mentions(content)
        reply.mentions.set(mentioned_users)
        
        # Handle attachments
        files = request.FILES.getlist('attachments')
        for file in files:
            MessageAttachment.objects.create(
                message=reply,
                file=file,
                filename=file.name,
                file_type=file.content_type,
                file_size=file.size,
                uploaded_by=request.user
            )
        
        messages.success(request, 'Reply sent.')
        return redirect('view_message', message_id=parent.pk)
    
    return redirect('view_message', message_id=parent.pk)


@login_required
def update_message_status(request, message_id):
    """Update message status (Open, In Progress, Resolved, Closed)"""
    message_obj = get_object_or_404(InternalMessage, pk=message_id)
    
    # Only recipient or owner/manager can update status
    if not (
        message_obj.recipient == request.user or
        request.user.is_owner or
        request.user.is_manager
    ):
        messages.error(request, 'You do not have permission to update this message.')
        return redirect('view_message', message_id=message_obj.pk)
    
    if request.method == 'POST':
        new_status = request.POST.get('status')
        if new_status in dict(InternalMessage.STATUS_CHOICES):
            message_obj.status = new_status
            message_obj.save()
            messages.success(request, f'Message marked as {new_status}.')
    
    return redirect('view_message', message_id=message_obj.pk)


@login_required
def pin_message(request, message_id):
    """Pin or unpin a message"""
    message_obj = get_object_or_404(InternalMessage, pk=message_id)
    
    # Only recipient or owner/manager can pin
    if not (
        message_obj.recipient == request.user or
        request.user.is_owner or
        request.user.is_manager
    ):
        messages.error(request, 'You do not have permission to pin this message.')
        return redirect('view_message', message_id=message_obj.pk)
    
    message_obj.is_pinned = not message_obj.is_pinned
    message_obj.save()
    
    action = 'pinned' if message_obj.is_pinned else 'unpinned'
    messages.success(request, f'Message {action}.')
    
    return redirect('view_message', message_id=message_obj.pk)


@login_required
def forward_message(request, message_id):
    """Forward a message to another staff member"""
    original = get_object_or_404(InternalMessage, pk=message_id)
    
    if request.method == 'POST':
        recipient_id = request.POST.get('recipient_id')
        forward_content = request.POST.get('forward_content', '').strip()
        
        if not recipient_id:
            messages.error(request, 'Please select a recipient.')
            return redirect('view_message', message_id=original.pk)
        
        recipient = get_object_or_404(User, pk=recipient_id)
        
        # Create forwarded message
        forwarded = InternalMessage.objects.create(
            sender=request.user,
            recipient=recipient,
            client=original.client,
            message_type=original.message_type,
            subject=f"Fwd: {original.subject}",
            content=f"---------- Forwarded message ----------\n"
                    f"From: {original.sender.username}\n"
                    f"Date: {original.created_at.strftime('%b %d, %Y %H:%M')}\n"
                    f"Subject: {original.subject}\n\n"
                    f"{original.content}\n"
                    f"----------------------------------------\n\n"
                    f"{forward_content}",
            priority=original.priority,
        )
        
        messages.success(request, f'Message forwarded to {recipient.username}.')
        return redirect('message_inbox')
    
    recipients = User.objects.exclude(id=request.user.id)
    
    context = {
        'original': original,
        'recipients': recipients,
    }
    
    return render(request, 'core/forward_message.html', context)


@login_required
def bulk_actions(request):
    """Perform bulk actions on messages"""
    if request.method == 'POST':
        action = request.POST.get('action')
        message_ids = request.POST.getlist('message_ids')
        
        if not message_ids:
            messages.error(request, 'No messages selected.')
            return redirect('message_inbox')
        
        messages_qs = InternalMessage.objects.filter(id__in=message_ids, recipient=request.user)
        
        if action == 'mark_read':
            messages_qs.update(is_read=True, read_at=timezone.now())
            messages.success(request, f'{messages_qs.count()} messages marked as read.')
        elif action == 'delete':
            count = messages_qs.count()
            messages_qs.delete()
            messages.success(request, f'{count} messages deleted.')
        elif action == 'archive':
            messages_qs.update(status='CLOSED')
            messages.success(request, f'{messages_qs.count()} messages archived.')
        
        return redirect('message_inbox')
    
    return redirect('message_inbox')


@login_required
def send_broadcast(request):
    """Send a broadcast announcement to all staff"""
    if not (request.user.is_owner or request.user.is_manager):
        messages.error(request, 'Only owners and managers can send broadcasts.')
        return redirect('message_inbox')
    
    if request.method == 'POST':
        subject = request.POST.get('subject', '').strip()
        content = request.POST.get('content', '').strip()
        priority = request.POST.get('priority', 'NORMAL')
        
        if not subject or not content:
            messages.error(request, 'Subject and content are required.')
            return redirect('send_broadcast')
        
        # Create broadcast
        broadcast = InternalMessage.objects.create(
            sender=request.user,
            message_type='ANNOUNCEMENT',
            subject=subject,
            content=content,
            priority=priority,
            is_broadcast=True,
        )
        
        # Handle mentions
        mentioned_users = _parse_mentions(content)
        broadcast.mentions.set(mentioned_users)
        
        messages.success(request, 'Broadcast sent to all staff.')
        return redirect('message_inbox')
    
    context = {
        'priority_choices': InternalMessage.PRIORITY_CHOICES,
    }
    
    return render(request, 'core/send_broadcast.html', context)


@login_required
def message_analytics(request):
    """View messaging analytics and statistics"""
    if not (request.user.is_owner or request.user.is_manager):
        messages.error(request, 'You do not have permission to view analytics.')
        return redirect('message_inbox')
    
    # Date range (last 30 days by default)
    days = int(request.GET.get('days', 30))
    start_date = timezone.now() - timedelta(days=days)
    
    # Total messages
    total_messages = InternalMessage.objects.filter(created_at__gte=start_date).count()
    
    # Messages by type
    messages_by_type = InternalMessage.objects.filter(
        created_at__gte=start_date
    ).values('message_type').annotate(count=Count('id')).order_by('-count')
    
    # Messages by priority
    messages_by_priority = InternalMessage.objects.filter(
        created_at__gte=start_date
    ).values('priority').annotate(count=Count('id')).order_by('-count')
    
    # Status breakdown
    status_breakdown = InternalMessage.objects.filter(
        created_at__gte=start_date
    ).values('status').annotate(count=Count('id'))
    
    # Most active senders
    active_senders = InternalMessage.objects.filter(
        created_at__gte=start_date
    ).values('sender__username').annotate(
        count=Count('id')
    ).order_by('-count')[:10]
    
    # Overdue messages
    overdue_count = InternalMessage.objects.filter(
        due_date__lt=timezone.now(),
        status__in=['OPEN', 'IN_PROGRESS']
    ).count()
    
    context = {
        'days': days,
        'total_messages': total_messages,
        'messages_by_type': messages_by_type,
        'messages_by_priority': messages_by_priority,
        'status_breakdown': status_breakdown,
        'active_senders': active_senders,
        'overdue_count': overdue_count,
    }
    
    return render(request, 'core/message_analytics.html', context)


@login_required
def shift_notes_list(request):
    """View all shift notes"""
    notes = ShiftNote.objects.select_related('author').all()
    
    # Filter by date
    date_filter = request.GET.get('date')
    if date_filter:
        try:
            filter_date = datetime.strptime(date_filter, '%Y-%m-%d').date()
            notes = notes.filter(shift_date=filter_date)
        except ValueError:
            pass
    
    context = {
        'notes': notes,
        'date_filter': date_filter,
    }
    
    return render(request, 'core/shift_notes_list.html', context)


@login_required
def shift_note_create(request):
    """Create a new shift note"""
    if request.method == 'POST':
        shift = request.POST.get('shift')
        shift_date = request.POST.get('shift_date')
        notes = request.POST.get('notes', '').strip()
        incidents = request.POST.get('incidents', '').strip()
        handover = request.POST.get('handover_notes', '').strip()
        
        if not shift or not shift_date or not notes:
            messages.error(request, 'Shift, date, and notes are required.')
            return redirect('shift_note_create')
        
        try:
            date_obj = datetime.strptime(shift_date, '%Y-%m-%d').date()
        except ValueError:
            messages.error(request, 'Invalid date format.')
            return redirect('shift_note_create')
        
        ShiftNote.objects.create(
            author=request.user,
            shift=shift,
            shift_date=date_obj,
            notes=notes,
            incidents=incidents,
            handover_notes=handover
        )
        
        log_action(
            request.user, 'EDIT',
            details=f'Created shift note for {shift} on {shift_date}',
            ip_address=_client_ip(request)
        )
        
        messages.success(request, 'Shift note created successfully.')
        return redirect('shift_notes_list')
    
    context = {
        'shift_choices': ShiftNote.SHIFT_CHOICES,
    }
    
    return render(request, 'core/shift_note_create.html', context)


@login_required
def shift_note_view(request, note_id):
    """View a specific shift note"""
    note = get_object_or_404(ShiftNote.objects.select_related('author'), pk=note_id)
    return render(request, 'core/shift_note_view.html', {'note': note})


@login_required
def template_list(request):
    """View and manage message templates"""
    if not (request.user.is_owner or request.user.is_manager):
        messages.error(request, 'Only owners and managers can manage templates.')
        return redirect('message_inbox')
    
    templates = MessageTemplate.objects.all()
    
    context = {
        'templates': templates,
    }
    
    return render(request, 'core/template_list.html', context)


@login_required
def template_create(request):
    """Create a new message template"""
    if not (request.user.is_owner or request.user.is_manager):
        messages.error(request, 'Only owners and managers can create templates.')
        return redirect('message_inbox')
    
    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        category = request.POST.get('category', 'GENERAL')
        subject_template = request.POST.get('subject_template', '').strip()
        content_template = request.POST.get('content_template', '').strip()
        default_priority = request.POST.get('default_priority', 'NORMAL')
        
        if not name or not subject_template or not content_template:
            messages.error(request, 'Name, subject, and content are required.')
            return redirect('template_create')
        
        MessageTemplate.objects.create(
            name=name,
            category=category,
            subject_template=subject_template,
            content_template=content_template,
            default_priority=default_priority,
            created_by=request.user
        )
        
        messages.success(request, 'Template created successfully.')
        return redirect('template_list')
    
    context = {
        'categories': MessageTemplate._meta.get_field('category').choices,
        'priority_choices': InternalMessage.PRIORITY_CHOICES,
    }
    
    return render(request, 'core/template_create.html', context)