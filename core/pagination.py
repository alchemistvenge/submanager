from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger


def paginate(request, queryset, per_page=20):
    """
    Paginate a queryset based on the request's 'page' parameter.
    Returns a page object with useful context for templates.
    """
    paginator = Paginator(queryset, per_page)
    page_number = request.GET.get('page')
    
    try:
        page = paginator.page(page_number)
    except PageNotAnInteger:
        page = paginator.page(1)
    except EmptyPage:
        page = paginator.page(paginator.num_pages)
    
    # Build page range with ellipsis for long lists
    page_range = paginator.page_range
    if paginator.num_pages > 10:
        current = page.number
        start = max(1, current - 2)
        end = min(paginator.num_pages, current + 2)
        page_range = range(start, end + 1)
    
    return {
        'page': page,
        'paginator': paginator,
        'page_range': page_range,
        'total_count': paginator.count,
    }
