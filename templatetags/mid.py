from django import template

register = template.Library()

@register.filter
def mid_url(mid):
    return mid.url()
