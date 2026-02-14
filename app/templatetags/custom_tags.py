from django import template
register = template.Library()

@register.filter
def to(value, end):
    return range(value, end + 1)

@register.filter
def get_item(dictionary, key):
    """Allow dictionary lookup in templates."""
    if isinstance(dictionary, dict):
        return dictionary.get(key, "")
    return ""

@register.filter
def discount_percent(price, sale_price):
    """Calculate discount percentage: {{ product.price|discount_percent:product.sale_price }}"""
    try:
        price = float(price)
        sale_price = float(sale_price)
        if price > 0 and sale_price < price:
            return int(round((price - sale_price) / price * 100))
    except (ValueError, TypeError):
        pass
    return 0