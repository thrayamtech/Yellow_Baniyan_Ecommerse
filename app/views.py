from django.shortcuts import render, redirect
from django.contrib import messages
from django.contrib.auth.hashers import make_password, check_password
from . import db
import re
import os
from django.conf import settings
from django.http import JsonResponse
from django.core.mail import send_mail
from django.conf import settings
import random, string
from django.contrib.auth.hashers import make_password
from django.utils.crypto import get_random_string
from django.core.files.storage import FileSystemStorage
from datetime import datetime
from django.shortcuts import get_object_or_404
from math import ceil
from django.core.paginator import Paginator
from django.utils.html import strip_tags
import pandas as pd
from io import BytesIO
from django.http import HttpResponse
from django.views.decorators.http import require_POST
from django.views.decorators.csrf import ensure_csrf_cookie, csrf_protect
from django.views.decorators.cache import cache_control
import logging
from decimal import Decimal
from django.utils.safestring import mark_safe
from django.urls import reverse
from PIL import Image
from django.core.exceptions import ValidationError



logger = logging.getLogger(__name__)


# Normalize phone numbers
def normalize_phone(raw):
    """Keep only digits (works for +91, spaces, etc.)"""
    return re.sub(r"\D", "", raw or "")

def get_cart_count(user_id):
    """Return total number of items in user's cart"""
    result = db.selectone(
        "SELECT COALESCE(SUM(quantity), 0) AS count FROM cart WHERE user_id=%s",
        (user_id,)
    )
    return result["count"] if result else 0

def get_wishlist_count(user_id):
    result = db.selectone(
        "SELECT COUNT(*) AS count FROM wishlist WHERE user_id=%s", (user_id,)
    )
    return result["count"] if result else 0

def is_user_vip(user_id):
    """Check if user has VIP status"""
    if not user_id:
        return False
    user = db.selectone("SELECT is_vip FROM users WHERE id=%s", (user_id,))
    return bool(user and user.get("is_vip"))


@cache_control(no_cache=True, must_revalidate=True, no_store=True)
def index(request):
    carousels = db.selectall("SELECT * FROM carousel_images ORDER BY id DESC")
    categories = db.selectall("SELECT * FROM categories ORDER BY id DESC")
    brands = db.selectall("SELECT * FROM brands WHERE is_active=1 ORDER BY id DESC")

    user_id = request.session.get("user_id")
    vip = is_user_vip(user_id)
    vip_filter = "" if vip else "AND (p.is_vip = 0 OR p.is_vip IS NULL)"

    # fetch top 8 most viewed, then fallback to latest 8 if none
    most_viewed = db.selectall(f"""
        SELECT p.id, p.title, p.price, p.sale_price, p.stock,
            (SELECT image FROM product_images WHERE product_id=p.id LIMIT 1) AS main_image,
            COUNT(DISTINCT v.user_id) AS view_count
        FROM product_views v
        JOIN products p ON v.product_id = p.id
        WHERE p.approved=1 AND p.pending_approval=0 AND p.disapproved=0 AND p.is_active=1 AND p.stock > 0
        {vip_filter}
        GROUP BY p.id
        ORDER BY view_count DESC
        LIMIT 8
    """)

    if not most_viewed:
        most_viewed = db.selectall(f"""
            SELECT p.id, p.title, p.price, p.sale_price, p.stock,
                (SELECT image FROM product_images WHERE product_id=p.id LIMIT 1) AS main_image
            FROM products p
            WHERE p.approved=1 AND p.pending_approval=0 AND p.disapproved=0 AND p.is_active=1 AND p.stock > 0
            {vip_filter}
            ORDER BY p.id DESC
            LIMIT 8
        """)


    def chunk_list(data, chunk_size):
        return [data[i:i + chunk_size] for i in range(0, len(data), chunk_size)]

    category_groups = chunk_list(categories, 10)
    first_10_categories = categories[:10]

    return render(request, "index.html", {
        "carousels": carousels,
        "categories": categories,
        "brands": brands,
        "category_groups": category_groups,
        "first_10_categories": first_10_categories,
        "most_viewed": most_viewed,
        "cart_count": get_cart_count(request.session["user_id"]) if "user_id" in request.session else 0,
        "wishlist_count": get_wishlist_count(request.session["user_id"]) if "user_id" in request.session else 0
    })


def about(request):
    return render(request, 'about.html',{"cart_count": get_cart_count(request.session["user_id"]) if "user_id" in request.session else 0,
                                         "wishlist_count": get_wishlist_count(request.session["user_id"]) if "user_id" in request.session else 0})

def contact(request):
    return render(request, 'contact.html',{"cart_count": get_cart_count(request.session["user_id"]) if "user_id" in request.session else 0,
                                           "wishlist_count": get_wishlist_count(request.session["user_id"]) if "user_id" in request.session else 0})

def user_categories(request):
    categories = db.selectall("SELECT * FROM categories ORDER BY id DESC")
    return render(request, 'usercategories.html', {"categories": categories, "cart_count": get_cart_count(request.session["user_id"]) if "user_id" in request.session else 0,
                                                   "wishlist_count": get_wishlist_count(request.session["user_id"]) if "user_id" in request.session else 0})
@cache_control(no_cache=True, must_revalidate=True, no_store=True)


def shop_all(request):
    """Display all products with category + subcategory sidebar"""
    user_id = request.session.get("user_id")
    vip = is_user_vip(user_id)
    vip_filter = "" if vip else "AND (p.is_vip = 0 OR p.is_vip IS NULL)"

    categories = db.selectall("SELECT * FROM categories ORDER BY name ASC")
    subcategories = db.selectall("SELECT * FROM subcategories ORDER BY name ASC")
    brands = db.selectall("SELECT * FROM brands ORDER BY name ASC")

    # Filter logic (optional)
    cat_id = request.GET.get("cat")
    sub_id = request.GET.get("sub")

    query = f"""
        SELECT p.*,
               c.name AS category_name,
               s.name AS subcategory_name,
               b.name AS brand_name,
               (SELECT image FROM product_images WHERE product_id=p.id LIMIT 1) AS main_image
        FROM products p
        LEFT JOIN categories c ON p.category_id=c.id
        LEFT JOIN subcategories s ON p.subcategory_id=s.id
        LEFT JOIN brands b ON p.brand_id=b.id
        WHERE p.approved=1 AND p.pending_approval=0 AND p.disapproved=0 AND p.is_active=1 AND p.stock > 0
        AND (b.is_active=1 OR b.is_active IS NULL)
        {vip_filter}
    """

    params = []
    if cat_id:
        query += " AND p.category_id=%s"
        params.append(cat_id)
    if sub_id:
        query += " AND p.subcategory_id=%s"
        params.append(sub_id)

    query += " ORDER BY p.id DESC"
    products = db.selectall(query, tuple(params))

    total = len(products)

    return render(request, "shop-all.html", {
        "categories": categories,
        "subcategories": subcategories,
        "brands": brands,
        "products": products,
        "total": total,
        "cart_count": get_cart_count(user_id) if user_id else 0,
        "wishlist_count": get_wishlist_count(user_id) if user_id else 0,
    })


def category_products(request, category_id):
    # ✅ Get category
    category = db.selectone("SELECT * FROM categories WHERE id=%s", (category_id,))
    if not category:
        messages.error(request, "Category not found.")
        return redirect("index")

    user_id = request.session.get("user_id")
    vip = is_user_vip(user_id)
    vip_filter = "" if vip else "AND (p.is_vip = 0 OR p.is_vip IS NULL)"

    # ✅ Fetch subcategories for sidebar filter
    subcategories = db.selectall("SELECT * FROM subcategories WHERE category_id=%s ORDER BY name ASC", (category_id,))
    brands = db.selectall("SELECT * FROM brands ORDER BY name ASC")

    # ✅ Sorting logic
    sort = request.GET.get("sort", "")
    order_by = "p.id DESC"
    if sort == "price_low":
        order_by = "p.price ASC"
    elif sort == "price_high":
        order_by = "p.price DESC"

    # ✅ Filter by selected subcategory
    sub_id = request.GET.get("sub")
    subcategory_filter = ""
    params = [category_id]
    if sub_id:
        subcategory_filter = "AND p.subcategory_id=%s"
        params.append(sub_id)

    # ✅ Pagination setup
    page = int(request.GET.get("page", 1))
    limit = int(request.GET.get("limit", 12))
    offset = (page - 1) * limit

    # ✅ Count total products
    count_row = db.selectone(f"""
        SELECT COUNT(*) AS count
        FROM products p
        LEFT JOIN brands b ON p.brand_id = b.id
        WHERE p.category_id=%s
        AND p.approved=1
        AND p.pending_approval=0
        AND p.disapproved=0
        AND p.is_active=1
        AND p.stock > 0
        AND (b.is_active=1 OR b.is_active IS NULL)
        {vip_filter}
        {subcategory_filter}
    """, params)

    total = count_row["count"] if count_row else 0

    # ✅ Fetch paginated products
    products = db.selectall(f"""
        SELECT p.*,
            c.name AS category_name,
            s.name AS subcategory_name,
            b.name AS brand_name,
            (SELECT image FROM product_images WHERE product_id=p.id LIMIT 1) AS main_image
        FROM products p
        LEFT JOIN categories c ON p.category_id=c.id
        LEFT JOIN subcategories s ON p.subcategory_id=s.id
        LEFT JOIN brands b ON p.brand_id=b.id
        WHERE p.category_id=%s
        AND p.approved=1
        AND p.pending_approval=0
        AND p.disapproved=0
        AND p.is_active=1
        AND p.stock > 0
        AND (b.is_active=1 OR b.is_active IS NULL)
        {vip_filter}
        {subcategory_filter}
        ORDER BY {order_by}
        LIMIT %s OFFSET %s
    """, params + [limit, offset])

    total_pages = (total + limit - 1) // limit

    # ✅ Categories for navbar
    categories_all = db.selectall("SELECT * FROM categories ORDER BY name ASC")

    context = {
        "category": category,
        "categories_all": categories_all,
        "subcategories": subcategories,
        "brands": brands,
        "products": products,
        "page": page,
        "total_pages": total_pages,
        "total": total,
        "sort": sort,
        "limit": limit,
    }
    user_id = request.session.get("user_id")

    return render(request, "shop-grid.html", {
        "cart_count": get_cart_count(user_id) if user_id else 0,
        "wishlist_count": get_wishlist_count(user_id) if user_id else 0,
        **context
    })



from django.http import JsonResponse

def signup(request):
    if request.method == "POST":
        fname = request.POST.get("formSignupfname")
        lname = request.POST.get("formSignuplname")
        email = request.POST.get("formSignupEmail")
        phone = normalize_phone(request.POST.get("formSignupPhone"))
        password = request.POST.get("formSignupPassword")

        if not (email or phone):
            messages.error(request, "Please provide an email or phone number.")
            return redirect("signup")

        # Check if user exists
        existing = db.selectone("SELECT * FROM users WHERE email=%s OR phone=%s", (email, phone))
        if existing:
            messages.error(request, "Email or Phone Number already exists.")
            return redirect("signup")

        hashed_pwd = make_password(password)
        db.insert(
            "INSERT INTO users (first_name, last_name, email, phone, password) VALUES (%s,%s,%s,%s,%s)",
            (fname, lname, email, phone, hashed_pwd)
        )
        messages.success(request, "Account created successfully! Please login.")
        return redirect("userlogin")

    return render(request, 'signup.html')  

from django.contrib import messages

def userlogin(request):
    if request.method == "POST":
        # Check if request is AJAX
        is_ajax = request.headers.get('x-requested-with') == 'XMLHttpRequest'

        identifier = request.POST.get("formSigninEmail", "").strip()
        password = request.POST.get("formSigninPassword", "").strip()
        phone = normalize_phone(identifier)

        user = None
        if "@" in identifier:
            user = db.selectone("SELECT * FROM users WHERE email=%s", (identifier,))
        elif phone.isdigit():
            user = db.selectone("SELECT * FROM users WHERE phone=%s", (phone,))
        else:
            if is_ajax:
                return JsonResponse({"status": "error", "message": "Please enter a valid email or phone number."})
            messages.error(request, "Please enter a valid email or phone number.")
            return redirect("userlogin")

        if user and check_password(password, user["password"]):
            request.session["user_id"] = user["id"]
            request.session["user_name"] = user["first_name"] + " " + user["last_name"]

            if is_ajax:
                return JsonResponse({"status": "success", "message": f"Welcome back, {user['first_name']}!"})
            
            messages.success(request, f"Welcome back, {user['first_name']}!")
            return redirect("index")
        else:
            if is_ajax:
                return JsonResponse({"status": "error", "message": "Invalid email/phone or password."})
            messages.error(request, "Invalid email/phone or password.")
            return redirect("userlogin")

    return render(request, "signin.html")

@cache_control(no_cache=True, must_revalidate=True, no_store=True)
def userlogout(request):
    # clear old messages
    storage = messages.get_messages(request)
    storage.used = True

    request.session.flush()
    messages.success(request, "You have been logged out.")
    return redirect("userlogin")


def user_forgot_password(request):
    if request.method == "POST":
        email = request.POST.get("email", "").strip()
        user = db.selectone("SELECT * FROM users WHERE email=%s", (email,))

        if not user:
            messages.error(request, "No account found with that email.")
            return redirect("user-forgot-password")

        otp = ''.join(random.choices(string.digits, k=6))
        request.session['user_reset_email'] = email
        request.session['user_reset_otp'] = otp

        try:
            send_mail(
                subject="Password Reset OTP - Yellow Banyan",
                message=f"Your OTP for password reset is: {otp}\n\nThis code is valid for this session only. Do not share it with anyone.",
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[email],
                fail_silently=False,
            )
            messages.success(request, "OTP sent to your email. Please check your inbox.")
            return redirect("user-reset-verify")
        except Exception as e:
            messages.error(request, "Error sending email. Please try again later.")
            print(e)
            return redirect("user-forgot-password")

    return render(request, "forgot-password.html")


def user_reset_verify(request):
    if request.method == "POST":
        otp = request.POST.get("otp", "").strip()
        new_password = request.POST.get("new_password", "").strip()
        confirm_password = request.POST.get("confirm_password", "").strip()

        session_otp = request.session.get("user_reset_otp")
        email = request.session.get("user_reset_email")

        if not session_otp or not email:
            messages.error(request, "Session expired. Please restart the reset process.")
            return redirect("user-forgot-password")

        if otp != session_otp:
            messages.error(request, "Invalid OTP.")
            return redirect("user-reset-verify")

        if new_password != confirm_password:
            messages.error(request, "Passwords do not match.")
            return redirect("user-reset-verify")

        if len(new_password) < 6:
            messages.error(request, "Password must be at least 6 characters.")
            return redirect("user-reset-verify")

        hashed_pwd = make_password(new_password)
        db.update("UPDATE users SET password=%s WHERE email=%s", (hashed_pwd, email))

        request.session.pop("user_reset_email", None)
        request.session.pop("user_reset_otp", None)

        messages.success(request, "Password reset successful! You can now log in.")
        return redirect("userlogin")

    return render(request, "user_reset_verify.html")


from django.views.decorators.csrf import csrf_exempt

@csrf_exempt
def add_to_cart(request, product_id):
    """Add product to cart (login required)"""
    if "user_id" not in request.session:
        return JsonResponse({"status": "login_required"})

    user_id = request.session["user_id"]
    qty = int(request.POST.get("quantity", 1))

    # ✅ Check if product exists
    product = db.selectone("SELECT * FROM products WHERE id=%s", (product_id,))
    if not product:
        return JsonResponse({"status": "error", "message": "Product not found."})

    # Block non-VIP users from adding VIP products
    if product.get("is_vip") and not is_user_vip(user_id):
        return JsonResponse({"status": "error", "message": "This product is available for VIP members only."})

    # ✅ Check if already in cart → update qty
    existing = db.selectone(
        "SELECT * FROM cart WHERE user_id=%s AND product_id=%s",
        (user_id, product_id)
    )

    if existing:
        db.update("UPDATE cart SET quantity = quantity + %s WHERE id=%s", (qty, existing["id"]))
        return JsonResponse({"status": "updated", "cart_count": get_cart_count(user_id), "message": "Quantity updated in your cart."})
    else:
        db.insert("INSERT INTO cart (user_id, product_id, quantity) VALUES (%s,%s,%s)",
                  (user_id, product_id, qty))
        return JsonResponse({"status": "added", "cart_count": get_cart_count(user_id), "message": "Product added to your cart."})



def cart(request):
    """Show user's cart"""
    if "user_id" not in request.session:
        messages.warning(request, "Please login to view your cart.")
        return redirect("userlogin")

    user_id = request.session["user_id"]

    items = db.selectall("""
        SELECT c.id AS cart_id, p.id AS product_id, p.title, p.price, p.sale_price,
               (SELECT image FROM product_images WHERE product_id=p.id LIMIT 1) AS image,
               c.quantity
        FROM cart c
        JOIN products p ON c.product_id = p.id
        WHERE c.user_id=%s
    """, (user_id,))

    # 👉  Compute total per item so Django can render it
    for item in items:
        price = item["sale_price"] or item["price"]
        item["total_price"] = price * item["quantity"]

    subtotal = sum(item["total_price"] for item in items)
    total = subtotal

    return render(request, "shop-cart.html", {
        "items": items,
        "subtotal": subtotal,
        "total": total,
        "cart_count": get_cart_count(request.session["user_id"]) if "user_id" in request.session else 0,
        "wishlist_count": get_wishlist_count(user_id) if user_id else 0,
    })

@csrf_exempt
def update_cart_quantity(request, cart_id):
    """Update or remove cart item"""
    if "user_id" not in request.session:
        return JsonResponse({"status": "login_required"})

    user_id = request.session["user_id"]
    qty = int(request.POST.get("quantity", 1))

    if qty <= 0:
        # remove item if qty=0
        db.delete("DELETE FROM cart WHERE id=%s AND user_id=%s", (cart_id, user_id))
        return JsonResponse({"status": "removed"})

    db.update("UPDATE cart SET quantity=%s WHERE id=%s AND user_id=%s", (qty, cart_id, user_id))
    return JsonResponse({"status": "updated"})

@csrf_exempt
def apply_promo(request):
    """Apply promo discount"""
    promo = request.POST.get("promo", "").strip().lower()
    subtotal = float(request.POST.get("subtotal", 0))

    discounts = {"save10": 0.10, "welcome20": 0.20, "free50": 0.50}

    if promo not in discounts:
        return JsonResponse({"status": "invalid", "message": "Invalid promo code."})

    discount = subtotal * discounts[promo]
    total = subtotal - discount
    return JsonResponse({
        "status": "success",
        "discount": discount,
        "total": total
    })

@require_POST
@cache_control(no_cache=True, must_revalidate=True, no_store=True)
def cart_demo_payment(request):
    """Simulate payment for all cart items + SuperCoin logic"""
    if "user_id" not in request.session:
        return redirect("userlogin")

    user_id = request.session["user_id"]

    # 🛒 Get all cart items
    items = db.selectall("""
        SELECT c.id AS cart_id, p.id AS product_id, p.price, p.sale_price, c.quantity
        FROM cart c
        JOIN products p ON c.product_id = p.id
        WHERE c.user_id=%s
    """, (user_id,))

    if not items:
        messages.warning(request, "Your cart is empty.")
        return redirect("cart")

    # 🧾 Calculate total
    total_amount = 0
    for item in items:
        price = item["sale_price"] or item["price"]
        total_amount += price * item["quantity"]

    # 🪙 Fetch user’s available coins
    total_coins = db.selectone("SELECT COALESCE(SUM(coins_earned), 0) AS total FROM rewards WHERE user_id=%s", (user_id,))
    available = total_coins["total"]

    # 🪙 Handle coin usage
    use_coins = request.POST.get("use_coins", "off") == "on"
    discount = 0
    if use_coins and available > 0:
        discount = min(int(total_amount), available)
        total_amount -= discount
        db.insert(
            "INSERT INTO rewards (user_id, coins_earned, source) VALUES (%s, %s, %s)",
            (user_id, -discount, f"Used {discount} coins for cart discount"),
        )

    # Get selected shipping address
    address_id = request.POST.get("address_id")

    # Generate a group ID to link all items from this cart checkout
    order_group = f"GRP-{int(datetime.now().timestamp())}-{get_random_string(4)}"

    order_ids = []
    for item in items:
        item_price = item["sale_price"] or item["price"]
        total_item_price = item_price * item["quantity"]

        order_id = db.insert_return_id("""
            INSERT INTO orders (user_id, product_id, total_amount, payment_status, created_at, order_group, address_id)
            VALUES (%s, %s, %s, %s, NOW(), %s, %s)
        """, (user_id, item["product_id"], total_item_price, "success", order_group, address_id))
        order_ids.append(order_id)

    # ✅ Send combined HTML emails for all orders
    try:
        send_order_emails_html(user_id, order_ids)
    except Exception as e:
        print("Order email send failed (cart_demo_payment):", e)

    # 🎁 Reward new coins (1 coin per ₹100 spent)
    earned = int(total_amount // 100)
    if earned > 0:
        db.insert(
            "INSERT INTO rewards (user_id, coins_earned, source) VALUES (%s, %s, %s)",
            (user_id, earned, f"Earned from cart purchase ₹{total_amount}"),
        )

    # 🧹 Clear cart after successful order
    db.delete("DELETE FROM cart WHERE user_id=%s", (user_id,))

    issue_rewards_from_active_template(user_id, total_amount)

    messages.success(
        request,
        f"✅ Order placed for all cart items! You used {discount} coins and earned {earned} new SuperCoins.",
    )
    return redirect("order-details")

@cache_control(no_cache=True, must_revalidate=True, no_store=True)
def wishlist(request):
    """Display wishlist items"""
    if "user_id" not in request.session:
        return redirect("userlogin")

    user_id = request.session["user_id"]

    items = db.selectall("""
        SELECT 
            w.product_id, 
            p.title, 
            p.price, 
            p.sale_price,
            p.stock,
            (SELECT image FROM product_images WHERE product_id=p.id LIMIT 1) AS main_image
        FROM wishlist w
        JOIN products p ON w.product_id = p.id
        WHERE w.user_id=%s
        ORDER BY w.id DESC
    """, (user_id,))

    return render(request, "shop-wishlist.html", {
        "items": items,
        "cart_count": get_cart_count(user_id),
        "wishlist_count": get_wishlist_count(user_id),
    })


@csrf_exempt
def wishlist_add_to_cart(request, product_id):
    """Move wishlist product to cart"""
    if "user_id" not in request.session:
        return JsonResponse({"status": "login_required"})

    user_id = request.session["user_id"]

    # check stock
    product = db.selectone("SELECT * FROM products WHERE id=%s", (product_id,))
    if not product:
        return JsonResponse({"status": "error", "message": "Product not found."})
    if product["stock"] <= 0:
        return JsonResponse({"status": "out_of_stock", "message": "This product is out of stock."})

    # Add to cart or update qty
    existing = db.selectone("SELECT * FROM cart WHERE user_id=%s AND product_id=%s", (user_id, product_id))
    if existing:
        db.update("UPDATE cart SET quantity = quantity + 1 WHERE id=%s", (existing["id"],))
    else:
        db.insert("INSERT INTO cart (user_id, product_id, quantity) VALUES (%s, %s, 1)", (user_id, product_id))

    # remove from wishlist
    db.delete("DELETE FROM wishlist WHERE user_id=%s AND product_id=%s", (user_id, product_id))

    return JsonResponse({"status": "moved", "message": "Item moved to cart."})
    
@csrf_exempt
def add_to_wishlist(request, product_id):
    """Add product to wishlist (login required)"""
    if "user_id" not in request.session:
        return JsonResponse({"status": "login_required"})

    user_id = request.session["user_id"]

    # ✅ Check if product exists
    product = db.selectone("SELECT * FROM products WHERE id=%s", (product_id,))
    if not product:
        return JsonResponse({"status": "error", "message": "Product not found."})

    # ✅ Check if already in wishlist
    existing = db.selectone("SELECT * FROM wishlist WHERE user_id=%s AND product_id=%s", (user_id, product_id))
    if existing:
        return JsonResponse({"status": "exists", "message": "Product already in your wishlist."})

    # ✅ Add to wishlist
    db.insert("INSERT INTO wishlist (user_id, product_id) VALUES (%s,%s)", (user_id, product_id))
    return JsonResponse({"status": "added", "message": "Added to your wishlist!"})


@csrf_exempt
def remove_from_wishlist(request, product_id):
    """Remove item from wishlist"""
    if "user_id" not in request.session:
        return JsonResponse({"status": "login_required"})

    user_id = request.session["user_id"]
    db.delete("DELETE FROM wishlist WHERE user_id=%s AND product_id=%s", (user_id, product_id))
    return JsonResponse({"status": "removed", "message": "Removed from your wishlist."})

def view_product(request, id):
    user_id = request.session.get("user_id")
    vip = is_user_vip(user_id)

    product = db.selectone("""
    SELECT p.*,
           c.name AS category_name,
           s.name AS subcategory_name,
           b.name AS brand_name,
           a.username AS admin_name,
           a.organization AS admin_org,
           (SELECT image FROM product_images WHERE product_id = p.id LIMIT 1) AS main_image
    FROM products p
    LEFT JOIN categories c ON p.category_id = c.id
    LEFT JOIN subcategories s ON p.subcategory_id = s.id
    LEFT JOIN brands b ON p.brand_id = b.id
    LEFT JOIN adminusers a ON p.admin_id = a.id
    WHERE p.id=%s
""", (id,))

    # Block non-VIP users from viewing VIP products
    if product and product.get("is_vip") and not vip:
        messages.error(request, "This product is available for VIP members only.")
        return redirect("index")

    images = db.selectall("SELECT * FROM product_images WHERE product_id=%s", (id,))
    attributes = db.selectall("SELECT * FROM product_attributes WHERE product_id=%s", (id,))
    # ✅ Group attributes in pairs for display (2 per row)
    grouped_attrs = []
    for i in range(0, len(attributes), 2):
        pair = attributes[i:i+2]
        grouped_attrs.append(pair)
    if user_id:
        # Only count one view per user per product
        already_viewed = db.selectone("""
            SELECT id FROM product_views
            WHERE user_id=%s AND product_id=%s
        """, (user_id, id))
        if not already_viewed:
            db.insert("""
                INSERT INTO product_views (user_id, product_id) VALUES (%s, %s)
            """, (user_id, id))

    

    # ✅ Related products (same category, exclude this one)
    vip_filter = "" if vip else "AND (p.is_vip = 0 OR p.is_vip IS NULL)"
    related_products = db.selectall(f"""
        SELECT p.*,
               (SELECT image FROM product_images WHERE product_id=p.id LIMIT 1) AS main_image,
               c.name AS category_name,
               s.name AS subcategory_name,
               b.name AS brand_name
        FROM products p
        LEFT JOIN categories c ON p.category_id=c.id
        LEFT JOIN subcategories s ON p.subcategory_id=s.id
        LEFT JOIN brands b ON p.brand_id=b.id
        WHERE p.category_id=%s AND p.id != %s AND p.approved=1 AND p.stock > 0
        {vip_filter}
        LIMIT 4
    """, (product["category_id"], id))
    
        # ✅ Fetch average rating and review count
    rating_info = db.selectone("""
        SELECT 
            ROUND(AVG(rating),1) AS avg_rating,
            COUNT(*) AS total_reviews
        FROM product_reviews
        WHERE product_id=%s
    """, (id,))

    avg_rating = rating_info["avg_rating"] or 0
    total_reviews = rating_info["total_reviews"] or 0
        
        # ✅ Fetch product reviews
    reviews = db.selectall("""
        SELECT r.*, u.first_name AS user_name 
        FROM product_reviews r
        JOIN users u ON r.user_id=u.id
        WHERE r.product_id=%s
        ORDER BY r.created_at DESC
    """, (id,))

    return render(request, "shop-single.html", {
        "product": product,
        "images": images,
        "attributes": attributes,
        "grouped_attrs": grouped_attrs,
        "related_products": related_products,
        "reviews": reviews,
        "avg_rating": avg_rating,
        "total_reviews": total_reviews,
        "cart_count": get_cart_count(request.session["user_id"]) if "user_id" in request.session else 0,
        "wishlist_count": get_wishlist_count(request.session["user_id"]) if "user_id" in request.session else 0,
    })
    
    

@cache_control(no_cache=True, must_revalidate=True, no_store=True)
def rate_product(request, order_id):
    """Allow rating only for purchased products"""
    if "user_id" not in request.session:
        return redirect("userlogin")

    user_id = request.session["user_id"]

    # ✅ Verify order belongs to logged-in user
    order = db.selectone("""
        SELECT 
            o.id, 
            o.product_id, 
            p.title,
            (SELECT image FROM product_images WHERE product_id = p.id LIMIT 1) AS main_image
        FROM orders o
        JOIN products p ON o.product_id = p.id
        WHERE o.id = %s AND o.user_id = %s
    """, (order_id, user_id))

    if not order:
        messages.error(request, "You cannot rate this order.")
        return redirect("order-details")

    # ✅ Check existing review
    review = db.selectone("""
        SELECT * FROM product_reviews WHERE user_id=%s AND product_id=%s
    """, (user_id, order["product_id"]))

    if request.method == "POST":
        rating = int(request.POST.get("rating", 0))
        comment = request.POST.get("comment", "").strip()
        image_file = request.FILES.get("review_image")
        review_image_path = None

        # ✅ Handle optional image upload
        if image_file:
            fs = FileSystemStorage(location="media/review_images/")
            filename = fs.save(image_file.name, image_file)
            review_image_path = f"review_images/{filename}"

        # ✅ Insert or update review
        if review:
            db.update("""
                UPDATE product_reviews 
                SET rating=%s, comment=%s, review_image=%s, updated_at=NOW()
                WHERE user_id=%s AND product_id=%s
            """, (rating, comment, review_image_path or review.get("review_image"), user_id, order["product_id"]))
            messages.success(request, "Your review has been updated.")
        else:
            db.insert("""
                INSERT INTO product_reviews (user_id, product_id, rating, comment, review_image)
                VALUES (%s, %s, %s, %s, %s)
            """, (user_id, order["product_id"], rating, comment, review_image_path))
            messages.success(request, "Thank you for reviewing this product!")

        return redirect("order-details")

    return render(request, "user/rate-product.html", {
        "order": order,
        "review": review
    })

    
from colorthief import ColorThief
from PIL import Image
import os

def extract_dominant_color(image_path):
    try:
        full_path = os.path.join(settings.MEDIA_ROOT, image_path)
        color_thief = ColorThief(full_path)
        dominant_color = color_thief.get_color(quality=1)
        return '#%02x%02x%02x' % dominant_color
    except Exception:
        return '#0d6efd'  # fallback


@cache_control(no_cache=True, must_revalidate=True, no_store=True)
def brands(request):
    if "admin_id" not in request.session:
        return redirect("adminlogin")

    admin_id = request.session["admin_id"]
    admin = db.selectone("SELECT * FROM adminusers WHERE id=%s", (admin_id,))

    if not admin:
        messages.error(request, "Invalid admin.")
        return redirect("adminlogin")

    # 🧑‍💻 Normal Admin Mode
    if not admin["is_superadmin"]:
        brands = db.selectall("""
            SELECT b.*, 
                (SELECT COUNT(*) FROM products p WHERE p.brand_id=b.id AND p.admin_id=%s) AS product_count,
                (SELECT SUM(o.total_amount) FROM orders o 
                    JOIN products p ON o.product_id=p.id 
                    WHERE p.brand_id=b.id AND p.admin_id=%s) AS total_sales,
                (SELECT COUNT(*) FROM product_views v 
                    JOIN products p ON v.product_id=p.id 
                    WHERE p.brand_id=b.id AND p.admin_id=%s) AS total_views
            FROM brands b
            WHERE b.admin_id=%s
            ORDER BY total_sales DESC, total_views DESC
        """, (admin_id, admin_id, admin_id, admin_id))

        # Analytics summary
        total_brands = len(brands)
        total_sales = sum([b.get("total_sales") or 0 for b in brands])
        total_views = sum([b.get("total_views") or 0 for b in brands])
        top_sales = sorted(brands, key=lambda x: (x.get("total_sales") or 0), reverse=True)[:3]
        top_views = sorted(brands, key=lambda x: (x.get("total_views") or 0), reverse=True)[:3]

        return render(request, "superadmin/brands.html", {
            "admin": admin,
            "brands": brands,
            "normal_mode": True,
            "total_brands": total_brands,
            "total_sales": total_sales,
            "total_views": total_views,
            "top_sales": top_sales,
            "top_views": top_views
        })

    # 👑 Superadmin Mode
    selected_admin = request.GET.get("admin_filter")
    admin_list = db.selectall("SELECT id, username FROM adminusers WHERE is_superadmin=0 ORDER BY username ASC")

        # 👑 Superadmin → fetch only their own brands (admin_id)
    super_brands = db.selectall("""
        SELECT b.*, 
            (SELECT COUNT(*) FROM products p WHERE p.brand_id=b.id) AS product_count,
            (SELECT SUM(o.total_amount) FROM orders o 
                JOIN products p ON o.product_id=p.id 
                WHERE p.brand_id=b.id) AS total_sales,
            (SELECT COUNT(*) FROM product_views v 
                JOIN products p ON v.product_id=p.id 
                WHERE p.brand_id=b.id) AS total_views
        FROM brands b
        WHERE b.admin_id=%s
        ORDER BY total_sales DESC, total_views DESC
    """, (admin_id,))


    # Normal admin brands (filter if needed)
    filter_query = ""
    params = []
    if selected_admin:
        filter_query = "AND a.id=%s"
        params.append(selected_admin)

    normal_admin_brands = db.selectall(f"""
        SELECT b.*, 
               a.username AS admin_name,
               (SELECT COUNT(*) FROM products p WHERE p.brand_id=b.id) AS product_count,
               (SELECT SUM(o.total_amount) FROM orders o 
                    JOIN products p ON o.product_id=p.id 
                    WHERE p.brand_id=b.id) AS total_sales,
               (SELECT COUNT(*) FROM product_views v 
                    JOIN products p ON v.product_id=p.id 
                    WHERE p.brand_id=b.id) AS total_views
        FROM brands b
        JOIN adminusers a ON a.id = b.admin_id
        WHERE a.is_superadmin = 0 {filter_query}
        ORDER BY a.username ASC, b.name ASC
    """, tuple(params))

    # Combined analytics
    all_brands = (super_brands or []) + (normal_admin_brands or [])
    total_brands = len(all_brands)
    total_sales = sum([b.get("total_sales") or 0 for b in all_brands])
    total_views = sum([b.get("total_views") or 0 for b in all_brands])
    top_sales = sorted(all_brands, key=lambda x: (x.get("total_sales") or 0), reverse=True)[:3]
    top_views = sorted(all_brands, key=lambda x: (x.get("total_views") or 0), reverse=True)[:3]

    return render(request, "superadmin/brands.html", {
        "admin": admin,
        "super_brands": super_brands,
        "normal_admin_brands": normal_admin_brands,
        "admin_list": admin_list,
        "selected_admin": selected_admin,
        "normal_mode": False,
        "total_brands": total_brands,
        "total_sales": total_sales,
        "total_views": total_views,
        "top_sales": top_sales,
        "top_views": top_views
    })



    
@cache_control(no_cache=True, must_revalidate=True, no_store=True)
def brand_products(request, brand_id):
    """Show all products of a specific brand, with category and subcategory filters."""
    # ✅ Fetch brand
    brand = db.selectone("SELECT * FROM brands WHERE id=%s", (brand_id,))
    if not brand or not brand["is_active"]:
        messages.error(request, "This brand is currently unavailable.")
        return redirect("index")

    user_id = request.session.get("user_id")
    vip = is_user_vip(user_id)
    vip_filter = "" if vip else "AND (p.is_vip = 0 OR p.is_vip IS NULL)"

    if user_id:
        db.insert("""
            INSERT INTO brand_visits (user_id, brand_id) VALUES (%s, %s)
        """, (user_id, brand_id))

    # ✅ Sidebar data
    categories = db.selectall("SELECT * FROM categories ORDER BY name ASC")
    subcategories = db.selectall("SELECT * FROM subcategories ORDER BY name ASC")

    # ✅ Get filters safely
    category_filter = request.GET.get("category")
    subcategory_filter = request.GET.get("sub")

    # ✅ Build base SQL
    sql = f"""
        SELECT
            p.*,
            c.name AS category_name,
            s.name AS subcategory_name,
            b.name AS brand_name,
            (SELECT image FROM product_images WHERE product_id = p.id LIMIT 1) AS main_image
        FROM products p
        LEFT JOIN categories c ON p.category_id = c.id
        LEFT JOIN subcategories s ON p.subcategory_id = s.id
        LEFT JOIN brands b ON p.brand_id = b.id
        WHERE p.brand_id = %s
        AND p.approved = 1
        AND p.is_active = 1
        AND p.stock > 0
        AND (b.is_active = 1 OR b.is_active IS NULL)
        {vip_filter}
    """
    params = [brand_id]

    # ✅ Add filters if present
    if category_filter:
        sql += " AND p.category_id = %s"
        params.append(category_filter)
    if subcategory_filter:
        sql += " AND p.subcategory_id = %s"
        params.append(subcategory_filter)

    sql += " ORDER BY p.id DESC"
    products = db.selectall(sql, tuple(params))

    # ✅ Determine active filters (optional, safe)
    active_category = None
    active_subcategory = None

    if category_filter:
        active_category = db.selectone("SELECT * FROM categories WHERE id=%s", (category_filter,))
    if subcategory_filter:
        active_subcategory = db.selectone("SELECT * FROM subcategories WHERE id=%s", (subcategory_filter,))

    return render(request, "brand-products.html", {
        "brand": brand,
        "theme_color": brand.get("theme_color", "#0d6efd"),
        "categories": categories or [],
        "subcategories": subcategories or [],
        "products": products or [],
        "total": len(products) if products else 0,
        "active_category": active_category,
        "active_subcategory": active_subcategory,
        "cart_count": get_cart_count(user_id) if user_id else 0,
        "wishlist_count": get_wishlist_count(user_id) if user_id else 0,
    })
    
@cache_control(no_cache=True, must_revalidate=True, no_store=True)
def brand_analytics(request):
    if "admin_id" not in request.session:
        return redirect("adminlogin")

    # ✅ Superadmin check
    admin = db.selectone("SELECT * FROM adminusers WHERE id=%s", (request.session["admin_id"],))
    if not admin or not admin["is_superadmin"]:
        messages.error(request, "Access denied. Super admin only.")
        return redirect("admin-home")

    # ✅ Filters
    start_date = request.GET.get("start_date")
    end_date = request.GET.get("end_date")
    brand_id = request.GET.get("brand_id")

    # ✅ Fetch all brands (for dropdown)
    all_brands = db.selectall("SELECT id, name FROM brands ORDER BY name ASC")

    # ✅ Get selected brand name (for header display)
    selected_brand_name = None
    if brand_id:
        brand_obj = db.selectone("SELECT name FROM brands WHERE id=%s", (brand_id,))
        if brand_obj:
            selected_brand_name = brand_obj["name"]

    # ✅ Brand visit summary (left side)
    date_filter_sql = ""
    params = []
    if start_date and end_date:
        date_filter_sql = "WHERE DATE(bv.visited_at) BETWEEN %s AND %s"
        params.extend([start_date, end_date])
    elif start_date:
        date_filter_sql = "WHERE DATE(bv.visited_at) >= %s"
        params.append(start_date)
    elif end_date:
        date_filter_sql = "WHERE DATE(bv.visited_at) <= %s"
        params.append(end_date)

    brand_stats = db.selectall(f"""
        SELECT 
            b.id AS brand_id,
            b.name AS brand_name,
            b.image,
            b.theme_color,
            COUNT(DISTINCT bv.user_id) AS total_visitors
        FROM brands b
        LEFT JOIN brand_visits bv ON b.id = bv.brand_id
        {date_filter_sql}
        GROUP BY b.id, b.name, b.image, b.theme_color
        ORDER BY total_visitors DESC
    """, tuple(params))



    # ✅ Product views (right side)
    product_filter_sql = ""
    product_params = []

    if brand_id:
        product_filter_sql += "WHERE p.brand_id = %s"
        product_params.append(brand_id)

    if start_date and end_date:
        product_filter_sql += " AND " if brand_id else "WHERE "
        product_filter_sql += "DATE(pv.viewed_at) BETWEEN %s AND %s"
        product_params.extend([start_date, end_date])
    elif start_date:
        product_filter_sql += " AND " if brand_id else "WHERE "
        product_filter_sql += "DATE(pv.viewed_at) >= %s"
        product_params.append(start_date)
    elif end_date:
        product_filter_sql += " AND " if brand_id else "WHERE "
        product_filter_sql += "DATE(pv.viewed_at) <= %s"
        product_params.append(end_date)

    product_rows = db.selectall(f"""
        SELECT 
            b.id AS brand_id,
            b.name AS brand_name,
            b.theme_color,
            p.id AS product_id,
            p.title AS product_title,
            COUNT(DISTINCT pv.user_id) AS total_views
        FROM products p
        LEFT JOIN product_views pv ON p.id = pv.product_id
        LEFT JOIN brands b ON p.brand_id = b.id
        {product_filter_sql}
        GROUP BY b.id, b.name, b.theme_color, p.id, p.title
        ORDER BY total_views DESC
    """, tuple(product_params))


    # ✅ Group products by brand
    products_by_brand = {}
    for row in product_rows:
        brand = row["brand_name"] or "Unknown Brand"
        if brand not in products_by_brand:
            products_by_brand[brand] = []
        products_by_brand[brand].append(row)

    # ✅ Render
    return render(request, "superadmin/brand-analytics.html", {
        "brand_stats": brand_stats,
        "products_by_brand": products_by_brand,
        "all_brands": all_brands,
        "selected_brand": brand_id,
        "selected_brand_name": selected_brand_name,
        "start_date": start_date or "",
        "end_date": end_date or "",
    })




# user views
@cache_control(no_cache=True, must_revalidate=True, no_store=True)
def profile(request):
    if "user_id" not in request.session:
        return redirect("userlogin")

    # fetch user record
    user = db.selectone("SELECT id, first_name, last_name, email, phone FROM users WHERE id=%s", (request.session["user_id"],))
    if not user:
        messages.error(request, "User not found. Please login again.")
        request.session.flush()
        return redirect("userlogin")

    return render(request, 'user/account-settings.html', {"user": user, "cart_count": get_cart_count(request.session["user_id"]) if "user_id" in request.session else 0,
                                                          "wishlist_count": get_wishlist_count(request.session["user_id"]) if "user_id" in request.session else 0})


@require_POST
@cache_control(no_cache=True, must_revalidate=True, no_store=True)
def update_profile(request):
    if "user_id" not in request.session:
        return redirect("userlogin")

    user_id = request.session["user_id"]
    first_name = request.POST.get("first_name", "").strip()
    last_name = request.POST.get("last_name", "").strip()
    email = request.POST.get("email", "").strip()
    phone_raw = request.POST.get("phone", "").strip()
    phone = normalize_phone(phone_raw)

    # validate email/phone uniqueness (exclude current user)
    if email:
        existing = db.selectone("SELECT id FROM users WHERE email=%s AND id!=%s", (email, user_id))
        if existing:
            messages.error(request, "Email already in use by another account.")
            return redirect("profile")

    if phone:
        existing = db.selectone("SELECT id FROM users WHERE phone=%s AND id!=%s", (phone, user_id))
        if existing:
            messages.error(request, "Phone already in use by another account.")
            return redirect("profile")

    db.update("""
        UPDATE users
        SET first_name=%s, last_name=%s, email=%s, phone=%s
        WHERE id=%s
    """, (first_name, last_name, email, phone, user_id))

    # update session display name
    request.session["user_name"] = f"{first_name} {last_name}".strip()
    messages.success(request, "Profile updated successfully.")
    return redirect("profile")


@require_POST
@cache_control(no_cache=True, must_revalidate=True, no_store=True)
def change_password(request):
    if "user_id" not in request.session:
        return redirect("userlogin")

    user_id = request.session["user_id"]
    current_password = request.POST.get("current_password", "").strip()
    new_password = request.POST.get("new_password", "").strip()
    confirm_password = request.POST.get("confirm_password", "").strip()

    if not new_password or not confirm_password:
        messages.error(request, "Please enter the new password and confirmation.")
        return redirect("profile")

    if new_password != confirm_password:
        messages.error(request, "New password and confirmation do not match.")
        return redirect("profile")

    user = db.selectone("SELECT * FROM users WHERE id=%s", (user_id,))
    if not user or not check_password(current_password, user["password"]):
        messages.error(request, "Current password is incorrect.")
        return redirect("profile")

    hashed = make_password(new_password)
    db.update("UPDATE users SET password=%s WHERE id=%s", (hashed, user_id))
    messages.success(request, "Password updated successfully.")
    return redirect("profile")


@require_POST
@cache_control(no_cache=True, must_revalidate=True, no_store=True)
def delete_account(request):
    """
    Permanently delete the logged-in user's account.
    Requires current password POSTed as 'current_password'.
    """
    if "user_id" not in request.session:
        return redirect("userlogin")

    user_id = request.session["user_id"]
    current_password = request.POST.get("current_password", "").strip()

    user = db.selectone("SELECT * FROM users WHERE id=%s", (user_id,))
    if not user:
        messages.error(request, "User not found.")
        return redirect("userlogin")

    # verify password
    if not check_password(current_password, user["password"]):
        messages.error(request, "Current password is incorrect.")
        return redirect("profile")

    # Remove related user data (best-effort; adjust table names if you use different ones)
    try:
        db.delete("DELETE FROM cart WHERE user_id=%s", (user_id,))
        db.delete("DELETE FROM addresses WHERE user_id=%s", (user_id,))
        db.delete("DELETE FROM orders WHERE user_id=%s", (user_id,))
        db.delete("DELETE FROM order_items WHERE user_id=%s", (user_id,))  # if you have this
        db.delete("DELETE FROM notifications WHERE user_id=%s", (user_id,))
        db.delete("DELETE FROM wishlist WHERE user_id=%s", (user_id,))
        db.delete("DELETE FROM product_reviews WHERE user_id=%s", (user_id,))
    except Exception:
        # If some of those tables don't exist in your schema, ignore and continue.
        pass

    # Finally delete user row
    db.delete("DELETE FROM users WHERE id=%s", (user_id,))

    # clear session and redirect to home with message
    request.session.flush()
    messages.success(request, "Your account and related data have been deleted.")
    return redirect("index")


@csrf_protect
@cache_control(no_cache=True, must_revalidate=True, no_store=True)
def address(request):
    if "user_id" not in request.session:
        return redirect("userlogin")

    user_id = request.session["user_id"]

    if request.method == "POST":

        addr_id = request.POST.get("address_id")   # <-- declare first

        # ➤ Restrict max 5 addresses (only when adding)
        if not addr_id:
            address_count = db.selectone(
                "SELECT COUNT(*) AS cnt FROM addresses WHERE user_id=%s",
                (user_id,)
            )["cnt"]

            if address_count >= 5:
                messages.error(request, "You can save only 5 addresses. Please delete an old address to add a new one.")
                return redirect("address")

        # now fetch form fields
        first_name = request.POST.get("first_name")
        last_name = request.POST.get("last_name")
        address_line1 = request.POST.get("address_line1")
        address_line2 = request.POST.get("address_line2")
        city = request.POST.get("city")
        state = request.POST.get("state")
        country = request.POST.get("country")
        zip_code = request.POST.get("zip_code")
        phone = request.POST.get("phone")
        is_default = True if request.POST.get("is_default") == "on" else False

        if is_default:
            db.update("UPDATE addresses SET is_default=FALSE WHERE user_id=%s", (user_id,))

        # update
        if addr_id:
            db.update("""
                UPDATE addresses
                SET first_name=%s, last_name=%s, address_line1=%s, address_line2=%s,
                    city=%s, state=%s, country=%s, zip_code=%s, phone=%s, is_default=%s
                WHERE id=%s AND user_id=%s
            """, (
                first_name, last_name, address_line1, address_line2,
                city, state, country, zip_code, phone, is_default,
                addr_id, user_id
            ))
            messages.success(request, "Address updated successfully.")

        else:
            # insert
            db.insert("""
                INSERT INTO addresses
                (user_id, first_name, last_name, address_line1, address_line2,
                city, state, country, zip_code, phone, is_default)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """, (
                user_id, first_name, last_name, address_line1, address_line2,
                city, state, country, zip_code, phone, is_default
            ))
            messages.success(request, "Address added successfully.")

        return redirect("address")


    # ✅ Delete Address
    if request.GET.get("delete"):
        addr_id = request.GET.get("delete")
        db.delete("DELETE FROM addresses WHERE id=%s AND user_id=%s", (addr_id, user_id))
        messages.success(request, "Address deleted successfully.")
        return redirect("address")

    # ✅ Set Default Address
    if request.GET.get("default"):
        addr_id = request.GET.get("default")
        db.update("UPDATE addresses SET is_default=FALSE WHERE user_id=%s", (user_id,))
        db.update("UPDATE addresses SET is_default=TRUE WHERE id=%s AND user_id=%s", (addr_id, user_id))
        messages.success(request, "Default address updated.")
        return redirect("address")

    # ✅ Fetch addresses
    addresses = db.selectall(
        "SELECT * FROM addresses WHERE user_id=%s ORDER BY is_default DESC, id DESC",
        (user_id,)
    )

    # ✅ Editing existing address
    edit_id = request.GET.get("edit")
    edit_address = None
    if edit_id:
        edit_address = db.selectone("SELECT * FROM addresses WHERE id=%s AND user_id=%s", (edit_id, user_id))

    return render(request, "user/account-address.html", {
        "addresses": addresses,
        "edit_address": edit_address,
        "cart_count": get_cart_count(request.session["user_id"]) if "user_id" in request.session else 0,
        "wishlist_count": get_wishlist_count(user_id) if user_id else 0,
    })



@cache_control(no_cache=True, must_revalidate=True, no_store=True)
def order_details(request):
    if "user_id" not in request.session:
        return redirect("userlogin")

    user_id = request.session["user_id"]

    # ✅ Fetch all orders with tracking info
    orders = db.selectall("""
        SELECT 
            o.id AS order_id,
            o.created_at,
            o.total_amount,
            o.payment_status,
            COALESCE(t.status, 'Order Placed') AS tracking_status,
            p.title AS product_title,
            (SELECT image FROM product_images WHERE product_id = p.id LIMIT 1) AS product_image
        FROM orders o
        JOIN products p ON o.product_id = p.id
        LEFT JOIN order_tracking t ON t.order_id = o.id
        WHERE o.user_id=%s
        ORDER BY o.id DESC
    """, (user_id,))

    return render(request, "user/account-orders.html", {
        "orders": orders,
        "cart_count": get_cart_count(request.session["user_id"]) if "user_id" in request.session else 0,
        "wishlist_count": get_wishlist_count(user_id) if user_id else 0,
    })


def payment_method(request):
    return render(request, 'user/account-payment-method.html', {"cart_count": get_cart_count(request.session["user_id"]) if "user_id" in request.session else 0,
                                                                "wishlist_count": get_wishlist_count(request.session["user_id"]) if "user_id" in request.session else 0,})

def search_products(request):
    query = request.GET.get('q', '').strip()
    page = int(request.GET.get('page', 1))
    limit = 30
    offset = (page - 1) * limit

    user_id = request.session.get("user_id")
    vip = is_user_vip(user_id)
    vip_filter = "" if vip else "AND (p.is_vip = 0 OR p.is_vip IS NULL)"

    products = []
    total = 0
    total_pages = 1
    page_numbers = []

    if query:
        # ✅ Count total
        count_row = db.selectone(f"""
            SELECT COUNT(*) AS count
            FROM products p
            WHERE p.title LIKE %s
              AND p.approved = 1
              AND p.pending_approval = 0
              AND p.disapproved = 0
              AND p.stock > 0
              {vip_filter}
        """, [f'%{query}%'])
        total = count_row["count"] if count_row else 0
        total_pages = ceil(total / limit) if total > 0 else 1

        # ✅ Fetch paginated data
        products = db.selectall(f"""
            SELECT
                p.id,
                p.title AS name,
                p.price,
                p.sale_price,
                p.stock,
                (SELECT image FROM product_images WHERE product_id = p.id LIMIT 1) AS image
            FROM products p
            WHERE p.title LIKE %s
              AND p.approved = 1
              AND p.pending_approval = 0
              AND p.disapproved = 0
              AND p.stock > 0
              {vip_filter}
            ORDER BY p.id DESC
            LIMIT %s OFFSET %s
        """, [f'%{query}%', limit, offset])

        # ✅ Create range list for pagination
        page_numbers = list(range(1, total_pages + 1))

    return render(request, 'search_results.html', {
        'query': query,
        'products': products,
        'page': page,
        'total_pages': total_pages,
        'total': total,
        'page_numbers': page_numbers,
        "cart_count": get_cart_count(request.session["user_id"]) if "user_id" in request.session else 0,
        "wishlist_count": get_wishlist_count(request.session["user_id"]) if "user_id" in request.session else 0,
    })

    
    
@cache_control(no_cache=True, must_revalidate=True, no_store=True)
def buy_now(request, product_id):
    """Buy Now checkout page with selectable addresses"""
    if "user_id" not in request.session:
        return redirect("userlogin")

    user_id = request.session["user_id"]

    # ✅ Get product details
    product = db.selectone("""
        SELECT p.*, (SELECT image FROM product_images WHERE product_id=p.id LIMIT 1) AS main_image
        FROM products p WHERE p.id=%s
    """, (product_id,))
    if not product:
        messages.error(request, "Product not found.")
        return redirect("index")

    # Block non-VIP users from buying VIP products
    if product.get("is_vip") and not is_user_vip(user_id):
        messages.error(request, "This product is available for VIP members only.")
        return redirect("index")

    # ✅ Fetch user addresses
    addresses = db.selectall(
        "SELECT * FROM addresses WHERE user_id=%s ORDER BY is_default DESC, id DESC",
        (user_id,)
    )
    selected_id = request.GET.get("address_id")
    if selected_id:
        selected_address = db.selectone(
            "SELECT * FROM addresses WHERE id=%s AND user_id=%s",
            (selected_id, user_id)
        )
    else:
        selected_address = db.selectone(
            "SELECT * FROM addresses WHERE user_id=%s AND is_default=1 LIMIT 1", (user_id,)
        )

    # ✅ Get shipping cost per kg
    ship = db.selectone("SELECT cost_per_kg FROM shipping_settings LIMIT 1")
    cost_per_kg = Decimal(str(ship["cost_per_kg"])) if ship and ship["cost_per_kg"] is not None else Decimal("0")

    # ✅ Calculate shipping fee (weight * cost/kg)
    total_weight = Decimal(str(product.get("weight") or 0))
    shipping_fee = (total_weight * cost_per_kg).quantize(Decimal("0.01"))

    # ✅ Product price
    product_price = Decimal(str(product["sale_price"] or product["price"]))

    # ✅ Total (product + shipping)
    total_price = (product_price + shipping_fee).quantize(Decimal("0.01"))

    # ✅ Fetch total SuperCoins (earned - spent if you track that later)
    coins = db.selectone("""
        SELECT COALESCE(SUM(coins_earned), 0) AS total
        FROM rewards
        WHERE user_id=%s
    """, (user_id,))
    user_coins = int(coins["total"]) if coins else 0

    return render(request, "purchase.html", {
        "product": product,
        "addresses": addresses,
        "default_address": selected_address,
        "user_coins": user_coins,
        "is_cart_checkout": False,
        "shipping_fee": shipping_fee,
        "cost_per_kg": cost_per_kg,
        "total_price": total_price,     # ✅ now template total works
        "subtotal": product_price,      # ✅ used for JS recalculations
        "cart_count": get_cart_count(user_id),
        "wishlist_count": get_wishlist_count(user_id),
    })


@cache_control(no_cache=True, must_revalidate=True, no_store=True)
def cart_checkout(request):
    """Cart checkout → combine all items, total weight, shipping fee, and total"""
    if "user_id" not in request.session:
        return redirect("userlogin")

    user_id = request.session["user_id"]

    # 🛒 Get all cart items (include product weight)
    items = db.selectall("""
        SELECT c.id AS cart_id, p.id AS product_id, p.title, p.price, p.sale_price, p.weight,
               (SELECT image FROM product_images WHERE product_id=p.id LIMIT 1) AS main_image,
               c.quantity
        FROM cart c
        JOIN products p ON c.product_id = p.id
        WHERE c.user_id=%s
    """, (user_id,))

    if not items:
        messages.warning(request, "Your cart is empty.")
        return redirect("cart")

    # 🧮 Calculate subtotal (use Decimal for accuracy)
    subtotal = Decimal("0.00")
    for item in items:
        price = Decimal(str(item["sale_price"] or item["price"]))
        item["total_price"] = (price * Decimal(str(item["quantity"]))).quantize(Decimal("0.01"))
        subtotal += item["total_price"]

    # 🧾 Fetch all addresses for selection
    addresses = db.selectall(
        "SELECT * FROM addresses WHERE user_id=%s ORDER BY is_default DESC, id DESC",
        (user_id,)
    )
    selected_id = request.GET.get("address_id")
    if selected_id:
        default_address = db.selectone(
            "SELECT * FROM addresses WHERE id=%s AND user_id=%s", (selected_id, user_id)
        )
    else:
        default_address = db.selectone(
            "SELECT * FROM addresses WHERE user_id=%s AND is_default=1 LIMIT 1", (user_id,)
        )

    # 🪙 Fetch total SuperCoins
    coins = db.selectone("""
        SELECT COALESCE(SUM(coins_earned), 0) AS total FROM rewards WHERE user_id=%s
    """, (user_id,))
    user_coins = int(coins["total"]) if coins else 0

    # ⚖️ Compute total weight (sum of all products × qty)
    total_weight = Decimal("0.00")
    for item in items:
        weight = Decimal(str(item.get("weight") or 0))
        total_weight += (weight * Decimal(str(item["quantity"])))

    # 🚚 Get cost/kg from superadmin
    ship = db.selectone("SELECT cost_per_kg FROM shipping_settings LIMIT 1")
    cost_per_kg = Decimal(str(ship["cost_per_kg"])) if ship and ship["cost_per_kg"] else Decimal("0")

    # 💸 Calculate shipping
    shipping_fee = (total_weight * cost_per_kg).quantize(Decimal("0.01"))

    # ✅ Total (Subtotal + Shipping)
    total_with_shipping = (subtotal + shipping_fee).quantize(Decimal("0.01"))

    return render(request, "purchase.html", {
        "cart_items": items,
        "subtotal": subtotal,
        "addresses": addresses,
        "default_address": default_address,
        "user_coins": user_coins,
        "shipping_fee": shipping_fee,
        "total_with_shipping": total_with_shipping,
        "cost_per_kg": cost_per_kg,
        "is_cart_checkout": True,
        "cart_count": get_cart_count(user_id),
        "wishlist_count": get_wishlist_count(user_id),
    })


@require_POST
@cache_control(no_cache=True, must_revalidate=True, no_store=True)
def demo_payment(request, product_id):
    """Simulate payment + reward coins + SuperCoin redemption"""
    if "user_id" not in request.session:
        return redirect("userlogin")

    user_id = request.session["user_id"]
    product = db.selectone("SELECT * FROM products WHERE id=%s", (product_id,))
    if not product:
        messages.error(request, "Product not found.")
        return redirect("index")

    amount = product["sale_price"] or product["price"]

    # 🪙 Check user total SuperCoins
    total_coins = db.selectone("SELECT COALESCE(SUM(coins_earned), 0) AS total FROM rewards WHERE user_id=%s", (user_id,))
    available = total_coins["total"]

    # 🧾 Handle coin redemption
    use_coins = request.POST.get("use_coins", "off") == "on"
    discount = 0
    if use_coins and available > 0:
        discount = min(int(amount), available)
        amount -= discount
        db.insert(
            "INSERT INTO rewards (user_id, coins_earned, source) VALUES (%s, %s, %s)",
            (user_id, -discount, f"Used {discount} coins for discount"),
        )

    # Get selected shipping address
    address_id = request.POST.get("address_id")

    order_group = f"GRP-{int(datetime.now().timestamp())}-{get_random_string(4)}"
    order_id = db.insert_return_id("""
        INSERT INTO orders (user_id, product_id, total_amount, payment_status, created_at, order_group, address_id)
        VALUES (%s, %s, %s, %s, NOW(), %s, %s)
    """, (user_id, product_id, amount, "success", order_group, address_id))

    # ✅ Send HTML order email (user + admin + superadmin)
    try:
        send_order_emails_html(user_id, [order_id])
    except Exception as e:
        print("Order email send failed (demo_payment):", e)

    # 🎁 Earn new coins
    earned = int(amount // 100)
    if earned > 0:
        db.insert(
            "INSERT INTO rewards (user_id, coins_earned, source) VALUES (%s, %s, %s)",
            (user_id, earned, f"Earned from purchase ₹{amount}"),
        )

    issue_rewards_from_active_template(user_id, amount)

    # Remove this product from cart if it exists there
    db.delete("DELETE FROM cart WHERE user_id=%s AND product_id=%s", (user_id, product_id))

    messages.success(
        request,
        f"✅ Order placed! You used {discount} coins and earned {earned} new SuperCoins.",
    )
    return redirect("order-details")

@cache_control(no_cache=True, must_revalidate=True, no_store=True)
def rewards(request):
    if "user_id" not in request.session:
        return redirect("userlogin")

    user_id = request.session["user_id"]

    # 🟡 SuperCoins history (existing)
    rewards = db.selectall("""
        SELECT * FROM rewards 
        WHERE user_id=%s AND coins_earned != 0
        ORDER BY created_at DESC
    """, (user_id,))

    total = db.selectone("""
        SELECT COALESCE(SUM(coins_earned), 0) AS total_coins
        FROM rewards WHERE user_id=%s
    """, (user_id,))

    # 🟢 Coupon-type reward (promo rewards)
    user_rewards = db.selectall("""
        SELECT * FROM rewards
        WHERE user_id=%s AND promo_code IS NOT NULL
        ORDER BY created_at DESC
    """, (user_id,))

    return render(request, "user/account-Rewards.html", {
        "rewards": rewards,              # supercoins history
        "total_coins": total["total_coins"],
        "user_rewards": user_rewards,    # coupon rewards
        "cart_count": get_cart_count(user_id),
        "wishlist_count": get_wishlist_count(user_id),
    })



# Admin views

@cache_control(no_cache=True, must_revalidate=True, no_store=True)
def admin_home(request):
    if "admin_id" not in request.session:
        return redirect("adminlogin")

    admin_id = request.session["admin_id"]
    admin = db.selectone("SELECT * FROM adminusers WHERE id=%s", (admin_id,))

    # Pagination params
    order_page = int(request.GET.get("order_page", 1))
    product_page = int(request.GET.get("product_page", 1))
    per_page = 5

    if admin["is_superadmin"]:
        total_sales = db.selectone("SELECT COALESCE(SUM(total_amount), 0) AS amt FROM orders")["amt"]
        total_orders = db.selectone("SELECT COUNT(*) AS c FROM orders")["c"]
        total_admins = db.selectone("SELECT COUNT(*) AS c FROM adminusers")["c"]
        total_products = db.selectone("SELECT COUNT(*) AS c FROM products")["c"]
        total_brands = db.selectone("SELECT COUNT(*) AS c FROM brands")["c"]
        total_customers = db.selectone("SELECT COUNT(*) AS c FROM users")["c"]

        # Top brands
        top_brands = db.selectall("""
            SELECT b.name, COUNT(DISTINCT v.user_id) AS visits
            FROM brands b
            LEFT JOIN brand_visits v ON v.brand_id=b.id
            GROUP BY b.id, b.name
            ORDER BY visits DESC
            LIMIT 5
        """)

        # Trend
        trend = db.selectall("""
            SELECT DATE(created_at) AS d, SUM(total_amount) AS t
            FROM orders
            WHERE created_at >= NOW() - INTERVAL 7 DAY
            GROUP BY DATE(created_at)
            ORDER BY d ASC
        """)
        labels = [row["d"].strftime("%b %d") for row in trend]
        values = [float(row["t"]) for row in trend]

        # Recent Orders & Products (unpaginated first)
        recent_orders_data = db.selectall("""
            SELECT o.id, o.total_amount, o.payment_status, o.created_at, u.first_name, u.last_name
            FROM orders o
            LEFT JOIN users u ON o.user_id = u.id
            ORDER BY o.created_at DESC
        """)
        recent_products_data = db.selectall("""
            SELECT p.title, p.price, p.approved, p.created_at, b.name AS brand_name
            FROM products p
            LEFT JOIN brands b ON p.brand_id = b.id
            ORDER BY p.created_at DESC
        """)

    else:
        total_sales = db.selectone("""
            SELECT COALESCE(SUM(o.total_amount), 0) AS amt
            FROM orders o 
            JOIN products p ON o.product_id = p.id
            WHERE p.admin_id=%s
        """, (admin_id,))["amt"]
        total_orders = db.selectone("""
            SELECT COUNT(*) AS c
            FROM orders o 
            JOIN products p ON o.product_id = p.id
            WHERE p.admin_id=%s
        """, (admin_id,))["c"]
        total_products = db.selectone("SELECT COUNT(*) AS c FROM products WHERE admin_id=%s", (admin_id,))["c"]
        approved_products = db.selectone("SELECT COUNT(*) AS c FROM products WHERE admin_id=%s AND approved=1", (admin_id,))["c"]
        pending_products = db.selectone("SELECT COUNT(*) AS c FROM products WHERE admin_id=%s AND pending_approval=1", (admin_id,))["c"]
        disapproved_products = db.selectone("SELECT COUNT(*) AS c FROM products WHERE admin_id=%s AND disapproved=1", (admin_id,))["c"]

        # Trend
        trend = db.selectall("""
            SELECT DATE(created_at) AS d, COUNT(*) AS c
            FROM products
            WHERE admin_id=%s AND created_at >= NOW() - INTERVAL 7 DAY
            GROUP BY DATE(created_at)
            ORDER BY d ASC
        """, (admin_id,))
        labels = [row["d"].strftime("%b %d") for row in trend]
        values = [row["c"] for row in trend]

        # Recent Orders & Products (unpaginated first)
        recent_orders_data = db.selectall("""
            SELECT o.id, o.total_amount, o.payment_status, o.created_at, u.first_name, u.last_name
            FROM orders o
            JOIN products p ON o.product_id=p.id
            LEFT JOIN users u ON o.user_id=u.id
            WHERE p.admin_id=%s
            ORDER BY o.created_at DESC
        """, (admin_id,))
        recent_products_data = db.selectall("""
            SELECT p.title, p.price, p.approved, p.created_at, b.name AS brand_name
            FROM products p
            LEFT JOIN brands b ON p.brand_id=b.id
            WHERE p.admin_id=%s
            ORDER BY p.created_at DESC
        """, (admin_id,))

    # Paginate Orders & Products
    order_paginator = Paginator(recent_orders_data, per_page)
    product_paginator = Paginator(recent_products_data, per_page)

    recent_orders = order_paginator.get_page(order_page)
    recent_products = product_paginator.get_page(product_page)

    context = {
        "admin": admin,
        "total_sales": total_sales,
        "total_orders": total_orders,
        "total_products": total_products,
        "approved_products": locals().get("approved_products"),
        "pending_products": locals().get("pending_products"),
        "disapproved_products": locals().get("disapproved_products"),
        "total_admins": locals().get("total_admins"),
        "total_brands": locals().get("total_brands"),
        "total_customers": locals().get("total_customers"),
        "top_brands": locals().get("top_brands"),
        "chart_labels": labels,
        "chart_values": values,
        "recent_orders": recent_orders,
        "recent_products": recent_products,
        "notifications": db.selectall("SELECT * FROM notifications ORDER BY created_at DESC LIMIT 6"),
    }

    return render(request, "superadmin/adminhome.html", context)


def admin_login(request):
    if request.method == "POST":
        username = request.POST.get("username", "").strip()
        password = request.POST.get("password", "").strip()

        # Allow login by username OR email
        admin_user = db.selectone(
            "SELECT * FROM adminusers WHERE username=%s OR email=%s", (username, username)
        )

        # Clear any old messages
        storage = messages.get_messages(request)
        storage.used = True

        if admin_user and check_password(password, admin_user["password"]):
            request.session["admin_id"] = admin_user["id"]
            request.session["admin_username"] = admin_user["username"]
            messages.success(request, f"Welcome back, {admin_user['username']}!")
            return redirect("admin-home")
        else:
            messages.error(request, "Invalid username, email, or password.")
            return redirect("adminlogin")

    return render(request, "superadmin/adminsignin.html")

@cache_control(no_cache=True, must_revalidate=True, no_store=True)
def adminlogout(request):
    """Securely logs out the admin and clears session without message framework error."""
    # Clear any pending messages first
    try:
        list(messages.get_messages(request))
    except Exception:
        pass  # safely ignore if messages storage not initialized

    # Then flush the session
    request.session.flush()

    # Add a new success message after logout (fresh session)
    messages.success(request, "Admin logged out successfully.")

    # Redirect to login page or home page
    return redirect("adminlogin")


def admin_forgot_password(request):
    if request.method == "POST":
        email = request.POST.get("email", "").strip()
        admin = db.selectone("SELECT * FROM adminusers WHERE email=%s", (email,))

        if not admin:
            messages.error(request, "No admin found with that email.")
            return redirect("admin-forgot-password")

        # Generate OTP or temporary reset code
        otp = ''.join(random.choices(string.digits, k=6))
        request.session['admin_reset_email'] = email
        request.session['admin_reset_otp'] = otp

        # Send email (requires EMAIL settings configured)
        try:
            send_mail(
                subject="Admin Password Reset OTP",
                message=f"Your OTP for admin password reset is: {otp}",
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[email],
                fail_silently=False,
            )
            messages.success(request, "OTP sent to your email. Please check your inbox.")
            return redirect("admin-reset-verify")
        except Exception as e:
            messages.error(request, "Error sending email. Check email settings.")
            print(e)
            return redirect("admin-forgot-password")

    return render(request, "superadmin/forgot-password.html")


def admin_reset_verify(request):
    if request.method == "POST":
        otp = request.POST.get("otp", "").strip()
        new_password = request.POST.get("new_password", "").strip()
        confirm_password = request.POST.get("confirm_password", "").strip()

        session_otp = request.session.get("admin_reset_otp")
        email = request.session.get("admin_reset_email")

        if not session_otp or not email:
            messages.error(request, "Session expired. Please restart the reset process.")
            return redirect("admin-forgot-password")

        if otp != session_otp:
            messages.error(request, "Invalid OTP.")
            return redirect("admin-reset-verify")

        if new_password != confirm_password:
            messages.error(request, "Passwords do not match.")
            return redirect("admin-reset-verify")

        hashed_pwd = make_password(new_password)
        db.update("UPDATE adminusers SET password=%s WHERE email=%s", (hashed_pwd, email))

        # Clean up session
        request.session.pop("admin_reset_email", None)
        request.session.pop("admin_reset_otp", None)

        messages.success(request, "Password reset successful! You can now log in.")
        return redirect("adminlogin")

    return render(request, "superadmin/admin_reset_verify.html")

@cache_control(no_cache=True, must_revalidate=True, no_store=True)
def admin_profile(request):
    """Admin profile page — show details, plan info, and edit options"""
    if "admin_id" not in request.session:
        return redirect("adminlogin")

    admin_id = request.session["admin_id"]
    admin = db.selectone("SELECT * FROM adminusers WHERE id=%s", (admin_id,))

    # Fetch current plan (if any)
    plan = None
    if not admin["is_superadmin"]:
        plan = db.selectone("SELECT * FROM plans WHERE plan_name=%s", (admin.get("current_plan", ""),))

    return render(request, "superadmin/admin-profile.html", {
        "admin": admin,
        "plan": plan,
    })


@require_POST
@cache_control(no_cache=True, must_revalidate=True, no_store=True)
def update_admin_profile(request):
    """Handle updates to admin details or password"""
    if "admin_id" not in request.session:
        return redirect("adminlogin")

    admin_id = request.session["admin_id"]
    admin = db.selectone("SELECT * FROM adminusers WHERE id=%s", (admin_id,))

    # ✅ Update basic info
    if "update_profile" in request.POST:
        name = request.POST.get("username", "").strip()
        email = request.POST.get("email", "").strip()
        phone = request.POST.get("phone", "").strip()
        organization = request.POST.get("organization", "").strip()
        address = request.POST.get("address", "").strip()

        # ✅ Handle photo update
        photo = request.FILES.get("photo")
        photo_path = admin["photo"]
        if photo:
            fs = FileSystemStorage(location=os.path.join(settings.MEDIA_ROOT, "admins"))
            filename = get_random_string(8) + "_" + photo.name
            saved_name = fs.save(filename, photo)
            photo_path = f"admins/{saved_name}"

        db.update("""
            UPDATE adminusers
            SET username=%s, email=%s, phone=%s, organization=%s, address=%s, photo=%s
            WHERE id=%s
        """, (name, email, phone, organization, address, photo_path, admin_id))

        messages.success(request, "Profile updated successfully.")
        return redirect("admin-profile")

    # ✅ Change password
    elif "change_password" in request.POST:
        current_pwd = request.POST.get("current_password", "").strip()
        new_pwd = request.POST.get("new_password", "").strip()
        confirm_pwd = request.POST.get("confirm_password", "").strip()

        if not check_password(current_pwd, admin["password"]):
            messages.error(request, "Incorrect current password.")
            return redirect("admin-profile")

        if new_pwd != confirm_pwd:
            messages.error(request, "New password and confirmation do not match.")
            return redirect("admin-profile")

        hashed = make_password(new_pwd)
        db.update("UPDATE adminusers SET password=%s WHERE id=%s", (hashed, admin_id))
        messages.success(request, "Password changed successfully.")
        return redirect("admin-profile")

    messages.error(request, "Invalid action.")
    return redirect("admin-profile")

@cache_control(no_cache=True, must_revalidate=True, no_store=True)
def customers(request):
    """Superadmin — view all registered users (customers)."""
    if "admin_id" not in request.session:
        return redirect("adminlogin")

    admin = db.selectone("SELECT * FROM adminusers WHERE id=%s", (request.session["admin_id"],))
    if not admin or not admin["is_superadmin"]:
        messages.error(request, "Access denied.")
        return redirect("admin-home")

    users = db.selectall("SELECT * FROM users ORDER BY created_at DESC")

    return render(request, "superadmin/customers.html", {
        "admin": admin,
        "users": users,
    })


@require_POST
def toggle_vip(request, user_id):
    if "admin_id" not in request.session:
        return JsonResponse({"status": "error", "message": "Unauthorized"}, status=403)

    admin = db.selectone("SELECT * FROM adminusers WHERE id=%s", (request.session["admin_id"],))
    if not admin or not admin["is_superadmin"]:
        return JsonResponse({"status": "error", "message": "Access denied"}, status=403)

    user = db.selectone("SELECT id, is_vip FROM users WHERE id=%s", (user_id,))
    if not user:
        return JsonResponse({"status": "error", "message": "User not found"}, status=404)

    new_status = not user.get("is_vip", False)
    db.update("UPDATE users SET is_vip=%s WHERE id=%s", (new_status, user_id))
    return JsonResponse({"status": "success", "is_vip": new_status})


@cache_control(no_cache=True, must_revalidate=True, no_store=True)
def get_user_details(request, user_id):
    """Fetch full registered user details + order summary for superadmin offcanvas modal"""
    if "admin_id" not in request.session:
        return JsonResponse({"error": "Unauthorized"}, status=403)

    # ✅ Get user details
    user = db.selectone("SELECT * FROM users WHERE id=%s", (user_id,))
    if not user:
        return JsonResponse({"error": "User not found"}, status=404)
    
    # ✅ Fetch the user's default address (if exists)
    address = db.selectone("""
        SELECT CONCAT_WS(', ', address_line1, address_line2, city, state, country, zip_code) AS full_address
        FROM addresses
        WHERE user_id = %s AND is_default = 1
        ORDER BY id DESC LIMIT 1
    """, (user_id,))

    # Add the default address to the user data
    user["address"] = address["full_address"] if address and address["full_address"] else "-"

    # Fill missing keys to prevent JS errors
    user.setdefault("first_name", "")
    user.setdefault("last_name", "")
    user.setdefault("created_at", datetime.now())
    user.setdefault("profile_photo", "")
    user.setdefault("phone", "")
    user.setdefault("address", "")

    # ✅ Fetch all orders for this user (no main_image column)
    orders = db.selectall("""
        SELECT o.id, o.total_amount, o.created_at, o.payment_status, p.title, p.price
        FROM orders o
        LEFT JOIN products p ON o.product_id = p.id
        WHERE o.user_id = %s
        ORDER BY o.created_at DESC
    """, (user_id,))

    # ✅ Group orders into order_items dict
    order_items = {}
    for order in orders:
        order_items[order["id"]] = [{
            "title": order["title"],
            "main_image": "",  # column missing
            "price": order["price"],
            "quantity": 1
        }]

    return JsonResponse({
        "user": user,
        "orders": orders,
        "order_items": order_items
    })

def carousel_images(request):
    if "admin_id" not in request.session:
        return redirect("adminlogin")
    
    admin = db.selectone("SELECT * FROM adminusers WHERE id=%s", (request.session["admin_id"],))
    if not admin or not admin["is_superadmin"]:
        messages.error(request, "Access denied. Super admin only.")
        return redirect("admin-home")
    
    data = db.selectall("SELECT * FROM carousel_images ORDER BY id DESC")
    
    return render(request, "superadmin/carousel-images.html", {"images": data})

import json
# ✅ ADD CAROUSEL IMAGE
def add_carousel_image(request):
    if "admin_id" not in request.session:
        return redirect("adminlogin")

    admin = db.selectone("SELECT * FROM adminusers WHERE id=%s", (request.session["admin_id"],))
    if not admin or not admin["is_superadmin"]:
        messages.error(request, "Access denied. Super admin only.")
        return redirect("admin-home")

    # Fetch dropdown data
    categories = db.selectall("SELECT id, name FROM categories ORDER BY name ASC")
    subcategories = db.selectall("SELECT id, name FROM subcategories ORDER BY name ASC")
    brands = db.selectall("SELECT id, name FROM brands ORDER BY name ASC")

    if request.method == "POST":
        carousel_name = request.POST.get("carousel_name", "").strip()
        description = request.POST.get("description", "").strip()
        page_link = request.POST.get("page_link", "").strip()
        offer_text = request.POST.get("offer_text", "").strip()
        image_file = request.FILES.get("image")

        # ---------- IMAGE VALIDATION ----------
        ALLOWED_FORMATS = ["JPEG", "JPG", "WEBP", "PNG"]
        MAX_FILE_SIZE = 300 * 1024  # 300 KB
        REQUIRED_WIDTH = 1920
        REQUIRED_HEIGHT = 800

        try:
            # File size check
            if image_file.size > MAX_FILE_SIZE:
                messages.error(request, "Image size must be under 300 KB.")
                return redirect(request.path)

            # Image dimension & format check
            img = Image.open(image_file)
            width, height = img.size
            format = img.format.upper()

            if width != REQUIRED_WIDTH or height != REQUIRED_HEIGHT:
                messages.error(
                    request,
                    "Image size must be exactly 1920 × 800 pixels."
                )
                return redirect(request.path)

            if format not in ALLOWED_FORMATS:
                messages.error(
                    request,
                    "Only JPG, JPEG, PNG, or WebP images are allowed."
                )
                return redirect(request.path)

        except Exception:
            messages.error(request, "Invalid image file.")
            return redirect(request.path)
        # ---------- END VALIDATION ----------

        # Validation
        if not carousel_name or not image_file:
            messages.error(request, "Please fill all required fields.")
            return redirect("add-carousel-image")

        # Reset file pointer after PIL read
        image_file.seek(0)

        # ✅ Save image file
        fs = FileSystemStorage(location=os.path.join(settings.MEDIA_ROOT, "carousels"))
        filename = get_random_string(8) + "_" + image_file.name
        saved_name = fs.save(filename, image_file)
        image_path = f"carousels/{saved_name}"

        # ✅ Save record
        db.insert("""
            INSERT INTO carousel_images (title, description, image, page_link, offer_text)
            VALUES (%s, %s, %s, %s, %s)
        """, (carousel_name, description, image_path, page_link, offer_text))

        messages.success(request, f"Carousel '{carousel_name}' added successfully!")
        return redirect("carousel-images")

    return render(request, "superadmin/add-carousel-image.html", {
        "categories": categories,
        "subcategories": subcategories,
        "brands": brands,
    })


# ✅ DELETE CAROUSEL
def delete_carousel(request, id):
    if "admin_id" not in request.session:
        return redirect("adminlogin")

    admin = db.selectone("SELECT * FROM adminusers WHERE id=%s", (request.session["admin_id"],))
    if not admin or not admin["is_superadmin"]:
        messages.error(request, "Access denied. Super admin only.")
        return redirect("admin-home")

    item = db.selectone("SELECT * FROM carousel_images WHERE id=%s", (id,))
    if not item:
        messages.error(request, "Carousel not found.")
        return redirect("carousel-images")

    # Delete file
    if item["image"]:
        photo_path = os.path.join(settings.MEDIA_ROOT, item["image"])
        if os.path.exists(photo_path):
            os.remove(photo_path)

    db.delete("DELETE FROM carousel_images WHERE id=%s", (id,))
    messages.success(request, f"Carousel '{item['title']}' deleted successfully.")
    return redirect("carousel-images")


# ✅ EDIT CAROUSEL
def edit_carousel(request, id):
    if "admin_id" not in request.session:
        return redirect("adminlogin")

    admin = db.selectone("SELECT * FROM adminusers WHERE id=%s", (request.session["admin_id"],))
    if not admin or not admin["is_superadmin"]:
        messages.error(request, "Access denied. Super admin only.")
        return redirect("admin-home")

    carousel = db.selectone("SELECT * FROM carousel_images WHERE id=%s", (id,))
    if not carousel:
        messages.error(request, "Carousel not found.")
        return redirect("carousel-images")

    categories = db.selectall("SELECT id, name FROM categories ORDER BY name ASC")
    subcategories = db.selectall("SELECT id, name FROM subcategories ORDER BY name ASC")
    brands = db.selectall("SELECT id, name FROM brands ORDER BY name ASC")

    if request.method == "POST":
        title = request.POST.get("carousel_name", "").strip()
        description = request.POST.get("description", "").strip()
        page_link = request.POST.get("page_link", "").strip()
        offer_text = request.POST.get("offer_text", "").strip()
        image_file = request.FILES.get("image")

        image_path = carousel["image"]
        if image_file:
            # ---------- IMAGE VALIDATION ----------
            ALLOWED_FORMATS = ["JPEG", "JPG", "WEBP", "PNG"]
            MAX_FILE_SIZE = 300 * 1024  # 300 KB
            REQUIRED_WIDTH = 1920
            REQUIRED_HEIGHT = 800

            try:
                # File size check
                if image_file.size > MAX_FILE_SIZE:
                    messages.error(request, "Image size must be under 300 KB.")
                    return redirect(request.path)

                # Image dimension & format check
                img = Image.open(image_file)
                width, height = img.size
                format = img.format.upper()

                if width != REQUIRED_WIDTH or height != REQUIRED_HEIGHT:
                    messages.error(
                        request,
                        "Image size must be exactly 1920 × 800 pixels."
                    )
                    return redirect(request.path)

                if format not in ALLOWED_FORMATS:
                    messages.error(
                        request,
                        "Only JPG, JPEG, PNG, or WebP images are allowed."
                    )
                    return redirect(request.path)

            except Exception:
                messages.error(request, "Invalid image file.")
                return redirect(request.path)
            # ---------- END VALIDATION ----------

            # Reset file pointer after PIL read
            image_file.seek(0)

            # ✅ Save image file
            fs = FileSystemStorage(location=os.path.join(settings.MEDIA_ROOT, "carousels"))
            filename = get_random_string(8) + "_" + image_file.name
            saved_name = fs.save(filename, image_file)
            image_path = f"carousels/{saved_name}"

        # ✅ Use plain triple-quoted string, no f-string
        db.update("""
            UPDATE carousel_images
            SET title=%s, description=%s, image=%s, page_link=%s, offer_text=%s
            WHERE id=%s
        """, (title, description, image_path, page_link, offer_text, id))

        messages.success(request, "Carousel updated successfully!")
        return redirect("carousel-images")


    return render(request, "superadmin/edit-carousel.html", {
        "carousel": carousel,
        "categories": categories,
        "subcategories": subcategories,
        "brands": brands,
    })


@cache_control(no_cache=True, must_revalidate=True, no_store=True)
def categories(request):
    if "admin_id" not in request.session:
        return redirect("adminlogin")
    
    admin = db.selectone("SELECT * FROM adminusers WHERE id=%s", (request.session["admin_id"],))
    if not admin or not admin["is_superadmin"]:
        messages.error(request, "Access denied. Super admin only.")
        return redirect("admin-home")
    
    # ✅ Visibility filter
    visibility = request.GET.get("visibility", "all")

    visibility_condition = ""
    if visibility == "visible":
        visibility_condition = "WHERE is_active=1"
    elif visibility == "hidden":
        visibility_condition = "WHERE is_active=0"

    # ✅ Fetch all categories, subcategories, and brands
    categories = db.selectall("SELECT * FROM categories ORDER BY id DESC")
    subcategories = db.selectall("SELECT * FROM subcategories ORDER BY id DESC")
    brands = db.selectall("SELECT * FROM brands ORDER BY id DESC")

    # ✅ Count subcategories + brands for each category
    for cat in categories:
        subcat_count = sum(1 for sub in subcategories if sub["category_id"] == cat["id"])
        brand_count = sum(1 for b in brands if b["category_id"] == cat["id"])
        cat["subcat_count"] = subcat_count
        cat["brand_count"] = brand_count

    return render(request, "superadmin/categories.html", {
        "categories": categories,
        "subcategories": subcategories,
        "brands": brands,  # ✅ now passed to template
    })





def add_category(request):
    if "admin_id" not in request.session:
        return redirect("adminlogin")
    
    admin = db.selectone("SELECT * FROM adminusers WHERE id=%s", (request.session["admin_id"],))
    if not admin or not admin["is_superadmin"]:
        messages.error(request, "Access denied. Super admin only.")
        return redirect("admin-home")

    if request.method == "POST":
        category_name = request.POST.get("category_name", "")
        slug = request.POST.get("slug", "")
        description = request.POST.get("description", "")
        meta_title = request.POST.get("meta_title", "")
        meta_description = request.POST.get("meta_description", "")
        image_file = request.FILES.get("image")
        
        # CATEGORY IMAGE VALIDATION
        REQUIRED_WIDTH = 400
        REQUIRED_HEIGHT = 400
        MAX_SIZE = 200 * 1024
        ALLOWED_FORMATS = ["JPEG", "JPG", "WEBP", "PNG"]

        try:
            if image_file.size > MAX_SIZE:
                messages.error(request, "Category image must be under 200 KB.")
                return redirect(request.path)

            img = Image.open(image_file)
            width, height = img.size
            format = img.format.upper()

            if width != REQUIRED_WIDTH or height != REQUIRED_HEIGHT:
                messages.error(request, "Category image must be exactly 400 × 400 pixels.")
                return redirect(request.path)

            if format not in ALLOWED_FORMATS:
                messages.error(request, "Only JPG, JPEG, PNG, or WebP images are allowed.")
                return redirect(request.path)

        except Exception:
            messages.error(request, "Invalid image file.")
            return redirect(request.path)


        if not category_name or not image_file:
            messages.error(request, "Please fill all required fields.")
            return redirect("add-category")

        # Reset file pointer after PIL read
        image_file.seek(0)

        fs = FileSystemStorage(location=os.path.join(settings.MEDIA_ROOT, "categories"))
        filename = get_random_string(8) + "_" + image_file.name
        saved_name = fs.save(filename, image_file)
        image_path = f"categories/{saved_name}"

        db.insert("""
            INSERT INTO categories (name, slug, description, image, meta_title, meta_description)
            VALUES (%s, %s, %s, %s, %s, %s)
        """, (category_name, slug, description, image_path, meta_title, meta_description))

        messages.success(request, f"Category '{category_name}' added successfully!")
        return redirect("categories")

    return render(request, "superadmin/add-category.html")


def edit_category(request, id):
    if "admin_id" not in request.session:
        return redirect("adminlogin")
    
    admin = db.selectone("SELECT * FROM adminusers WHERE id=%s", (request.session["admin_id"],))
    if not admin or not admin["is_superadmin"]:
        messages.error(request, "Access denied. Super admin only.")
        return redirect("admin-home")

    category = db.selectone("SELECT * FROM categories WHERE id=%s", (id,))
    if not category:
        messages.error(request, "Category not found.")
        return redirect("categories")

    if request.method == "POST":
        category_name = request.POST.get("category_name", "")
        slug = request.POST.get("slug", "")
        description = request.POST.get("description", "")
        meta_title = request.POST.get("meta_title", "")
        meta_description = request.POST.get("meta_description", "")
        image_file = request.FILES.get("image")
        
                # CATEGORY IMAGE VALIDATION
        REQUIRED_WIDTH = 400
        REQUIRED_HEIGHT = 400
        MAX_SIZE = 200 * 1024
        ALLOWED_FORMATS = ["JPEG", "JPG", "WEBP", "PNG"]

        try:
            if image_file.size > MAX_SIZE:
                messages.error(request, "Category image must be under 200 KB.")
                return redirect(request.path)

            img = Image.open(image_file)
            width, height = img.size
            format = img.format.upper()

            if width != REQUIRED_WIDTH or height != REQUIRED_HEIGHT:
                messages.error(request, "Category image must be exactly 400 × 400 pixels.")
                return redirect(request.path)

            if format not in ALLOWED_FORMATS:
                messages.error(request, "Only JPG, JPEG, PNG, or WebP images are allowed.")
                return redirect(request.path)

        except Exception:
            messages.error(request, "Invalid image file.")
            return redirect(request.path)


        image_path = category["image"]
        if image_file:
            # Reset file pointer after PIL read
            image_file.seek(0)
            fs = FileSystemStorage(location=os.path.join(settings.MEDIA_ROOT, "categories"))
            filename = get_random_string(8) + "_" + image_file.name
            saved_name = fs.save(filename, image_file)
            image_path = f"categories/{saved_name}"

        db.update("""
            UPDATE categories
            SET name=%s, slug=%s, description=%s, image=%s, meta_title=%s, meta_description=%s
            WHERE id=%s
        """, (category_name, slug, description, image_path, meta_title, meta_description, id))

        messages.success(request, "Category updated successfully!")
        return redirect("categories")

    return render(request, "superadmin/edit-category.html", {"category": category})


def delete_category(request, id):
    if "admin_id" not in request.session:
        return redirect("adminlogin")
    
    admin = db.selectone("SELECT * FROM adminusers WHERE id=%s", (request.session["admin_id"],))
    if not admin or not admin["is_superadmin"]:
        messages.error(request, "Access denied. Super admin only.")
        return redirect("admin-home")

    # Fetch category
    category = db.selectone("SELECT * FROM categories WHERE id=%s", (id,))
    if not category:
        messages.error(request, "Category not found.")
        return redirect("categories")

    # Delete image file
    if category["image"]:
        image_path = os.path.join(settings.MEDIA_ROOT, category["image"])
        if os.path.exists(image_path):
            os.remove(image_path)

    # Delete category (this automatically deletes subcategories because of ON DELETE CASCADE)
    db.delete("DELETE FROM categories WHERE id=%s", (id,))

    messages.success(request, f"Category '{category['name']}' and all its subcategories deleted successfully.")
    return redirect("categories")



@cache_control(no_cache=True, must_revalidate=True, no_store=True)
def add_subcategory(request):
    if "admin_id" not in request.session:
        return redirect("adminlogin")
    
    admin = db.selectone("SELECT * FROM adminusers WHERE id=%s", (request.session["admin_id"],))
    if not admin or not admin["is_superadmin"]:
        messages.error(request, "Access denied. Super admin only.")
        return redirect("admin-home")

    # Fetch all parent categories
    categories = db.selectall("SELECT id, name FROM categories ORDER BY name ASC")

    # ✅ Capture ?parent=ID from URL
    parent_id = request.GET.get("parent")
    parent_category = None
    if parent_id:
        parent_category = db.selectone("SELECT * FROM categories WHERE id=%s", (parent_id,))

    if request.method == "POST":
        subcategory_name = request.POST.get("subcategory_name", "")
        slug = request.POST.get("slug", "")
        description = request.POST.get("description", "")
        meta_title = request.POST.get("meta_title", "")
        meta_description = request.POST.get("meta_description", "")
        category_id = request.POST.get("category_id")

        if not subcategory_name or not category_id:
            messages.error(request, "Please fill all required fields.")
            return redirect("add-subcategory")

        db.insert("""
            INSERT INTO subcategories (category_id, name, slug, description, meta_title, meta_description)
            VALUES (%s, %s, %s, %s, %s, %s)
        """, (category_id, subcategory_name, slug, description, meta_title, meta_description))

        messages.success(request, f"Subcategory '{subcategory_name}' added successfully!")
        return redirect("categories")

    # ✅ Pass parent category data to template
    return render(request, "superadmin/add-Subcategory.html", {
        "categories": categories,
        "parent_category": parent_category,
    })


def edit_subcategory(request, id):
    if "admin_id" not in request.session:
        return redirect("adminlogin")
    
    admin = db.selectone("SELECT * FROM adminusers WHERE id=%s", (request.session["admin_id"],))
    if not admin or not admin["is_superadmin"]:
        messages.error(request, "Access denied. Super admin only.")
        return redirect("admin-home")

    sub = db.selectone("SELECT * FROM subcategories WHERE id=%s", (id,))
    if not sub:
        messages.error(request, "Subcategory not found.")
        return redirect("categories")

    categories = db.selectall("SELECT id, name FROM categories ORDER BY name ASC")

    if request.method == "POST":
        name = request.POST.get("subcategory_name", "")
        slug = request.POST.get("slug", "")
        description = request.POST.get("description", "")
        meta_title = request.POST.get("meta_title", "")
        meta_description = request.POST.get("meta_description", "")
        category_id = request.POST.get("category_id")

        db.update("""
            UPDATE subcategories
            SET category_id=%s, name=%s, slug=%s, description=%s, meta_title=%s, meta_description=%s
            WHERE id=%s
        """, (category_id, name, slug, description, meta_title, meta_description, id))

        messages.success(request, "Subcategory updated successfully!")
        return redirect("categories")

    return render(request, "superadmin/edit-subcategory.html", {"subcategory": sub, "categories": categories})


def delete_subcategory(request, id):
    if "admin_id" not in request.session:
        return redirect("adminlogin")
    
    admin = db.selectone("SELECT * FROM adminusers WHERE id=%s", (request.session["admin_id"],))
    if not admin or not admin["is_superadmin"]:
        messages.error(request, "Access denied. Super admin only.")
        return redirect("admin-home")

    sub = db.selectone("SELECT * FROM subcategories WHERE id=%s", (id,))
    if not sub:
        messages.error(request, "Subcategory not found.")
        return redirect("categories")

    # 🧹 Delete related products first
    db.delete("DELETE FROM products WHERE subcategory_id=%s", (id,))

    # Now delete subcategory
    db.delete("DELETE FROM subcategories WHERE id=%s", (id,))

    messages.success(request, f"Subcategory '{sub['name']}' and its products deleted successfully.")
    return redirect("categories")

@cache_control(no_cache=True, must_revalidate=True, no_store=True)
def add_brand(request):
    if "admin_id" not in request.session:
        return redirect("adminlogin")

    admin_id = request.session["admin_id"]
    admin = db.selectone("SELECT * FROM adminusers WHERE id=%s", (admin_id,))
    if not admin:
        messages.error(request, "Admin not found.")
        return redirect("adminlogin")

    categories = db.selectall("SELECT id, name FROM categories ORDER BY name ASC")
    parent_id = request.GET.get("parent")
    parent_category = db.selectone("SELECT * FROM categories WHERE id=%s", (parent_id,)) if parent_id else None

    if request.method == "POST":
        brand_name = request.POST.get("brand_name", "").strip()
        slug = request.POST.get("slug", "").strip()
        description = request.POST.get("description", "").strip()
        meta_title = request.POST.get("meta_title", "").strip()
        meta_description = request.POST.get("meta_description", "").strip()
        category_id = request.POST.get("category_id")
        image_file = request.FILES.get("image")
        
        REQUIRED_WIDTH = 400
        REQUIRED_HEIGHT = 400
        MAX_SIZE = 200 * 1024
        ALLOWED_FORMATS = ["JPEG", "JPG", "WEBP", "PNG"]

        if image_file:
            try:
                if image_file.size > MAX_SIZE:
                    messages.error(request, "Brand image must be under 200 KB.")
                    return redirect(request.path)

                img = Image.open(image_file)
                width, height = img.size
                format = img.format.upper()

                if width != REQUIRED_WIDTH or height != REQUIRED_HEIGHT:
                    messages.error(request, "Brand image must be exactly 400 × 400 pixels.")
                    return redirect(request.path)

                if format not in ALLOWED_FORMATS:
                    messages.error(request, "Only JPG, JPEG, PNG, or WebP images are allowed.")
                    return redirect(request.path)

            except Exception:
                messages.error(request, "Invalid brand image file.")
                return redirect(request.path)

        # ✅ Validation
        if not brand_name or not category_id or not image_file:
            messages.error(request, "Please fill all required fields.")
            return redirect("add-brand")

        # ✅ Prevent duplicate brand (across all admins)
        existing = db.selectone("SELECT * FROM brands WHERE name=%s", (brand_name,))
        if existing:
            messages.error(request, f"⚠️ Brand '{brand_name}' already exists.")
            return redirect("add-brand")

        # Reset file pointer after PIL read
        image_file.seek(0)

        # ✅ Save image
        fs = FileSystemStorage(location=os.path.join(settings.MEDIA_ROOT, "brands"))
        filename = get_random_string(8) + "_" + image_file.name
        saved_name = fs.save(filename, image_file)
        image_path = f"brands/{saved_name}"

        # ✅ Insert new brand with admin_id
        db.insert("""
            INSERT INTO brands (admin_id, category_id, name, slug, description, image, meta_title, meta_description, is_active)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,1)
        """, (admin_id, category_id, brand_name, slug, description, image_path, meta_title, meta_description))

        # ✅ Extract brand color
        try:
            color = extract_dominant_color(image_path)
            db.update("UPDATE brands SET theme_color=%s WHERE name=%s", (color, brand_name))
        except Exception as e:
            print("⚠️ Color extraction failed:", e)

        messages.success(request, f"✅ Brand '{brand_name}' added successfully!")
        return redirect("brands")

    return render(request, "superadmin/add-brand.html", {
        "categories": categories,
        "parent_category": parent_category,
        "admin": admin,
    })


def update_all_brand_colors(request):
    from colorthief import ColorThief
    import os
    from django.conf import settings

    brands = db.selectall("SELECT id, image FROM brands WHERE image IS NOT NULL")

    for brand in brands:
        try:
            full_path = os.path.join(settings.MEDIA_ROOT, brand["image"])
            color_thief = ColorThief(full_path)
            dominant_color = color_thief.get_color(quality=1)
            color_hex = '#%02x%02x%02x' % dominant_color
            db.update("UPDATE brands SET theme_color=%s WHERE id=%s", (color_hex, brand["id"]))
            print(f"✅ Updated {brand['id']} color → {color_hex}")
        except Exception as e:
            print(f"⚠️ Failed for brand {brand['id']}: {e}")

    return HttpResponse("Brand colors updated successfully!")


def edit_brand(request, id):
    brand = db.selectone("SELECT * FROM brands WHERE id=%s", (id,))
    categories = db.selectall("SELECT id, name FROM categories ORDER BY name ASC")

    if request.method == "POST":
        brand_name = request.POST.get("brand_name", "")
        slug = request.POST.get("slug", "")
        description = request.POST.get("description", "")
        meta_title = request.POST.get("meta_title", "")
        meta_description = request.POST.get("meta_description", "")
        category_id = request.POST.get("category_id")
        image_file = request.FILES.get("image")

        image_path = brand["image"]
        if image_file:
            # ---------- IMAGE VALIDATION ----------
            REQUIRED_WIDTH = 400
            REQUIRED_HEIGHT = 400
            MAX_SIZE = 200 * 1024
            ALLOWED_FORMATS = ["JPEG", "JPG", "WEBP", "PNG"]

            try:
                if image_file.size > MAX_SIZE:
                    messages.error(request, "Brand image must be under 200 KB.")
                    return redirect(request.path)

                img = Image.open(image_file)
                width, height = img.size
                format = img.format.upper()

                if width != REQUIRED_WIDTH or height != REQUIRED_HEIGHT:
                    messages.error(request, "Brand image must be exactly 400 × 400 pixels.")
                    return redirect(request.path)

                if format not in ALLOWED_FORMATS:
                    messages.error(request, "Only JPG, JPEG, PNG, or WebP images are allowed.")
                    return redirect(request.path)

            except Exception:
                messages.error(request, "Invalid brand image file.")
                return redirect(request.path)
            # ---------- END VALIDATION ----------

            # Reset file pointer after PIL read
            image_file.seek(0)

            fs = FileSystemStorage(location=os.path.join(settings.MEDIA_ROOT, "brands"))
            filename = get_random_string(8) + "_" + image_file.name
            saved_name = fs.save(filename, image_file)
            image_path = f"brands/{saved_name}"
            
        if not brand_name:
            messages.error(request, "Brand name is required.")

        db.update("""
            UPDATE brands SET category_id=%s, name=%s, slug=%s, description=%s,
            image=%s, meta_title=%s, meta_description=%s WHERE id=%s
        """, (category_id, brand_name, slug, description, image_path, meta_title, meta_description, id))
        
        try:
            color = extract_dominant_color(image_path)  # ✅ use the updated path, not brand["image"]
            db.update("UPDATE brands SET theme_color=%s WHERE id=%s", (color, id))
        except Exception as e:
            print("⚠️ Color extraction failed:", e)


        messages.success(request, "Brand updated successfully!")
        return redirect("brands")

    return render(request, "superadmin/edit-brand.html", {"brand": brand, "categories": categories})


def delete_brand(request, id):
    brand = db.selectone("SELECT * FROM brands WHERE id=%s", (id,))
    if not brand:
        messages.error(request, "Brand not found.")
        return redirect("brands")

    if brand["image"]:
        image_path = os.path.join(settings.MEDIA_ROOT, brand["image"])
        if os.path.exists(image_path):
            os.remove(image_path)

    db.delete("DELETE FROM brands WHERE id=%s", (id,))
    messages.success(request, f"Brand '{brand['name']}' deleted successfully.")
    return redirect("brands")



@cache_control(no_cache=True, must_revalidate=True, no_store=True)
def products(request):
    if "admin_id" not in request.session:
        return redirect("adminlogin")

    admin_id = request.session["admin_id"]
    admin = db.selectone("SELECT * FROM adminusers WHERE id=%s", (admin_id,))

    # Superadmin sees all categories, vendors only see categories where they have brands
    if admin["is_superadmin"]:
        categories = db.selectall("SELECT * FROM categories ORDER BY name ASC")
    else:
        categories = db.selectall("""
            SELECT DISTINCT c.* FROM categories c
            INNER JOIN brands b ON b.category_id = c.id
            WHERE b.admin_id = %s
            ORDER BY c.name ASC
        """, (admin_id,))

    # ✅ Add this line to fetch active plan
    all_plans = db.selectall("SELECT * FROM plans WHERE is_active=1 ORDER BY price ASC")

    context = {
        "categories": categories,
        "admin": admin,
        "all_plans": all_plans,  # ✅ Added for your modal
    }
    return render(request, "superadmin/products.html", context)

    
  
@cache_control(no_cache=True, must_revalidate=True, no_store=True)
def add_productcategory(request, category_id):
    if "admin_id" not in request.session:
        return redirect("adminlogin")

    admin_id = request.session["admin_id"]
    admin = db.selectone("SELECT * FROM adminusers WHERE id=%s", (admin_id,))
    category = db.selectone("SELECT * FROM categories WHERE id=%s", (category_id,))

    if not category:
        messages.error(request, "Category not found.")
        return redirect("products")

    # Vendors can only access categories where they have brands
    if not admin["is_superadmin"]:
        has_brand = db.selectone(
            "SELECT id FROM brands WHERE category_id=%s AND admin_id=%s LIMIT 1",
            (category_id, admin_id)
        )
        if not has_brand:
            messages.error(request, "You don't have access to this category.")
            return redirect("products")

    brands = db.selectall("SELECT * FROM brands WHERE category_id=%s AND admin_id=%s ORDER BY name ASC", (category_id, admin_id))

    page = int(request.GET.get("page", "1") or 1)
    limit = 10
    offset = (page - 1) * limit

    
    total_row = db.selectone("""
         SELECT COUNT(*) AS count FROM products
        WHERE category_id=%s AND admin_id=%s
        """, (category_id, admin_id))

    visibility = request.GET.get("visibility", "all")

    visibility_condition = ""
    if visibility == "visible":
        visibility_condition = "AND p.is_active=1"
    elif visibility == "hidden":
        visibility_condition = "AND p.is_active=0"

    products = db.selectall(f"""
        SELECT 
            p.id, p.title, p.price, p.sale_price, p.stock, p.description,
            p.approved, p.pending_approval, p.disapproved, p.disapprove_reason,
            p.created_at, p.is_active,
            c.name AS category_name,
            s.name AS subcategory_name,
            b.name AS brand_name,
            (SELECT image FROM product_images WHERE product_id = p.id LIMIT 1) AS main_image
        FROM products p
        LEFT JOIN categories c ON p.category_id = c.id
        LEFT JOIN subcategories s ON p.subcategory_id = s.id
        LEFT JOIN brands b ON p.brand_id = b.id
        WHERE p.category_id=%s AND p.admin_id=%s {visibility_condition}
        ORDER BY p.id DESC
        LIMIT %s OFFSET %s
    """, (category_id, admin_id, limit, offset))




    total = total_row["count"] if total_row else 0
    total_pages = ceil(total / limit) if total > 0 else 1

    context = {
        "category": category,
        "brands": brands,
        "products": products,
        "page": page,
        "total_pages": total_pages,
        "total": total,
        "admin": admin,
    }
    return render(request, "superadmin/Addproductscat.html", context)

@cache_control(no_cache=True, must_revalidate=True, no_store=True)
def add_products(request, category_id):
    if "admin_id" not in request.session:
        return redirect("adminlogin")

    admin_id = request.session["admin_id"]
    admin = db.selectone("SELECT * FROM adminusers WHERE id=%s", (admin_id,))
    category = db.selectone("SELECT * FROM categories WHERE id=%s", (category_id,))
    subcategories = db.selectall("SELECT * FROM subcategories WHERE category_id=%s ORDER BY name ASC", (category_id,))

    if not category:
        messages.error(request, "Invalid category.")
        return redirect("products")

    # Vendors can only access categories where they have brands
    if not admin["is_superadmin"]:
        has_brand = db.selectone(
            "SELECT id FROM brands WHERE category_id=%s AND admin_id=%s LIMIT 1",
            (category_id, admin_id)
        )
        if not has_brand:
            messages.error(request, "You don't have access to this category.")
            return redirect("products")

    # ✅ Filter brands based on admin
    brands = db.selectall(
        "SELECT * FROM brands WHERE category_id=%s AND admin_id=%s ORDER BY name ASC",
        (category_id, admin_id)
    )

    # ✅ UPDATED — FIX for plan_limit int conversion
    if admin["is_superadmin"]:
        plan_limit = 999999
    else:
        try:
            plan_limit = int(admin.get("plan_limit", 25) or 25)
        except:
            plan_limit = 25

    product_count = db.selectone("SELECT COUNT(*) as count FROM products WHERE admin_id=%s", (admin_id,))
    current_count = product_count["count"] if product_count else 0

    # ✅ LIMIT CHECK (now works correctly)
    if not admin["is_superadmin"] and current_count >= plan_limit:
        messages.error(request, f"🚫 You’ve reached your product limit ({plan_limit}). Upgrade to add more products.")
        return redirect("products")

    # ✅ Handle form submit
    if request.method == "POST":
        title = request.POST.get("title", "")
        subcategory_id = request.POST.get("subcategory") or None
        brand_id = request.POST.get("brand") or None
        price = request.POST.get("price", "0")
        sale_price = request.POST.get("sale_price", "0")
        stock = request.POST.get("stock", "0")
        weight = request.POST.get("weight", "0")
        description = request.POST.get("description", "")
        meta_title = request.POST.get("meta_title", "")
        meta_description = request.POST.get("meta_description", "")
        is_vip = request.POST.get("is_vip") == "on"

        approved = admin["is_superadmin"]
        pending_approval = not admin["is_superadmin"]

        db.insert("""
            INSERT INTO products 
            (title, category_id, subcategory_id, brand_id, price, sale_price, stock, weight, description,
             meta_title, meta_description, admin_id, approved, pending_approval, is_vip)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        """, (
            title, category_id, subcategory_id, brand_id, price, sale_price, stock, weight,
            description, meta_title, meta_description, admin_id,
            approved, pending_approval, is_vip
        ))

        product = db.selectone("SELECT * FROM products ORDER BY id DESC LIMIT 1")

        # ✅ Product images
        files = request.FILES.getlist("images")
        if files:
            fs = FileSystemStorage(location=os.path.join(settings.MEDIA_ROOT, "products"))
            for img in files:
                filename = get_random_string(8) + "_" + img.name
                fs.save(filename, img)
                db.insert("INSERT INTO product_images (product_id, image) VALUES (%s,%s)",
                          (product["id"], f"products/{filename}"))

        # ✅ Attributes
        field_names = request.POST.getlist("field_name[]")
        field_values = request.POST.getlist("field_value[]")
        for name, value in zip(field_names, field_values):
            if name and value:
                db.insert("INSERT INTO product_attributes (product_id, field_name, field_value) VALUES (%s,%s,%s)",
                          (product["id"], name, value))

        messages.success(request, f"✅ Product '{title}' added successfully under {category['name']}")
        return redirect("add-productcategory", category_id=category_id)

    return render(request, "superadmin/add-product.html", {
        "category": category,
        "subcategories": subcategories,
        "brands": brands,
        "admin": admin,
    })


@cache_control(no_cache=True, must_revalidate=True, no_store=True)
def delete_product(request, id):
    if "admin_id" not in request.session:
        return redirect("adminlogin")

    product = db.selectone("SELECT * FROM products WHERE id=%s", (id,))
    if not product:
        messages.error(request, "Product not found.")
        return redirect("products")

    # Delete images from media
    images = db.selectall("SELECT image FROM product_images WHERE product_id=%s", (id,))
    for img in images:
        path = os.path.join(settings.MEDIA_ROOT, img["image"])
        if os.path.exists(path):
            os.remove(path)

    db.delete("DELETE FROM products WHERE id=%s", (id,))
    messages.success(request, f"Product '{product['title']}' deleted successfully.")
    return redirect("add-productcategory", category_id=product["category_id"])

@cache_control(no_cache=True, must_revalidate=True, no_store=True)
def delete_selected_products(request):
    if "admin_id" not in request.session:
        return redirect("adminlogin")

    if request.method == "POST":
        selected = request.POST.getlist("selected_products")

        if not selected:
            messages.warning(request, "⚠️ No products selected for deletion.")
            return redirect(request.META.get("HTTP_REFERER", "products"))

        deleted_count = 0

        for pid in selected:
            # Fetch product
            product = db.selectone("SELECT * FROM products WHERE id=%s", (pid,))
            if not product:
                continue

            # Delete product images from media
            images = db.selectall("SELECT image FROM product_images WHERE product_id=%s", (pid,))
            for img in images:
                img_path = os.path.join(settings.MEDIA_ROOT, img["image"])
                if os.path.exists(img_path):
                    os.remove(img_path)

            # Delete related entries
            db.delete("DELETE FROM product_images WHERE product_id=%s", (pid,))
            db.delete("DELETE FROM product_attributes WHERE product_id=%s", (pid,))
            db.delete("DELETE FROM products WHERE id=%s", (pid,))
            deleted_count += 1

        messages.success(request, f"🗑️ {deleted_count} product(s) deleted successfully.")
        return redirect(request.META.get("HTTP_REFERER", "products"))

    return redirect("products")

@csrf_exempt
def toggle_product_status(request, product_id):
    """AJAX toggle for product visibility"""
    if "admin_id" not in request.session:
        return JsonResponse({"status": "error", "message": "Login required"})

    product = db.selectone("SELECT id, is_active FROM products WHERE id=%s", (product_id,))
    if not product:
        return JsonResponse({"status": "error", "message": "Product not found"})

    new_status = not bool(product["is_active"])
    db.update("UPDATE products SET is_active=%s WHERE id=%s", (new_status, product_id))

    return JsonResponse({
        "status": "success",
        "new_status": new_status,
        "message": "Product visibility updated."
    })



@csrf_exempt
def toggle_brand_status(request, brand_id):
    """Only superadmin can toggle brand visibility"""
    if "admin_id" not in request.session:
        return JsonResponse({"status": "error", "message": "Login required"})

    admin_id = request.session["admin_id"]
    admin = db.selectone("SELECT * FROM adminusers WHERE id=%s", (admin_id,))

    if not admin or not admin["is_superadmin"]:
        return JsonResponse({"status": "error", "message": "Only superadmin can toggle visibility"})

    brand = db.selectone("SELECT id, is_active FROM brands WHERE id=%s", (brand_id,))
    if not brand:
        return JsonResponse({"status": "error", "message": "Brand not found"})

    new_status = not bool(brand["is_active"])
    db.update("UPDATE brands SET is_active=%s WHERE id=%s", (new_status, brand_id))
    db.update("UPDATE products SET is_active=%s WHERE brand_id=%s", (new_status, brand_id))

    return JsonResponse({
        "status": "success",
        "new_status": new_status,
        "message": f"Brand visibility {'activated' if new_status else 'hidden'} successfully."
    })




@cache_control(no_cache=True, must_revalidate=True, no_store=True)
def edit_product(request, id):
    if "admin_id" not in request.session:
        return redirect("adminlogin")

    # ✅ Fetch product
    product = db.selectone("SELECT * FROM products WHERE id=%s", (id,))
    if not product:
        messages.error(request, "Product not found.")
        return redirect("products")

    # ✅ Fetch related data
    category = db.selectone("SELECT * FROM categories WHERE id=%s", (product["category_id"],))
    subcategories = db.selectall("SELECT id, name FROM subcategories WHERE category_id=%s", (product["category_id"],))
    brands = db.selectall("SELECT id, name FROM brands WHERE category_id=%s ORDER BY name ASC", (product["category_id"],))
    attributes = db.selectall("SELECT * FROM product_attributes WHERE product_id=%s", (id,))
    images = db.selectall("SELECT * FROM product_images WHERE product_id=%s", (id,))

    if request.method == "POST":
        title = request.POST.get("title", "")
        subcategory_id = request.POST.get("subcategory") or None
        brand_id = request.POST.get("brand") or None
        price = request.POST.get("price", "0")
        sale_price = request.POST.get("sale_price", "0")
        stock = request.POST.get("stock", "0")
        weight = request.POST.get("weight", "0")
        description = request.POST.get("description", "")
        meta_title = request.POST.get("meta_title", "")
        meta_description = request.POST.get("meta_description", "")

        # ✅ Update product info
        db.update("""
            UPDATE products
            SET title=%s, subcategory_id=%s, brand_id=%s, price=%s, sale_price=%s, stock=%s, weight=%s,
                description=%s, meta_title=%s, meta_description=%s
            WHERE id=%s
        """, (title, subcategory_id, brand_id, price, sale_price, stock, weight,
              description, meta_title, meta_description, id))

        # ✅ Handle custom fields
        db.delete("DELETE FROM product_attributes WHERE product_id=%s", (id,))
        names = request.POST.getlist("field_name[]")
        values = request.POST.getlist("field_value[]")
        for n, v in zip(names, values):
            if n and v:
                db.insert(
                    "INSERT INTO product_attributes (product_id, field_name, field_value) VALUES (%s,%s,%s)",
                    (id, n, v)
                )

        # ✅ Handle image logic
        keep_ids = request.POST.getlist("keep_images[]")
        existing = db.selectall("SELECT id, image FROM product_images WHERE product_id=%s", (id,))
        for img in existing:
            if str(img["id"]) not in keep_ids:
                path = os.path.join(settings.MEDIA_ROOT, img["image"])
                if os.path.exists(path):
                    os.remove(path)
                db.delete("DELETE FROM product_images WHERE id=%s", (img["id"],))

        # ✅ Add new images
        new_imgs = request.FILES.getlist("images")
        if new_imgs:
            fs = FileSystemStorage(location=os.path.join(settings.MEDIA_ROOT, "products"))
            for img in new_imgs:
                filename = get_random_string(8) + "_" + img.name
                fs.save(filename, img)
                db.insert("INSERT INTO product_images (product_id, image) VALUES (%s,%s)",
                          (id, f"products/{filename}"))

        messages.success(request, f"✅ Product '{title}' updated successfully!")
        return redirect("add-productcategory", category_id=product["category_id"])

    # ✅ Render edit form
    return render(request, "superadmin/edit-product.html", {
        "product": product,
        "category": category,
        "subcategories": subcategories,
        "brands": brands,
        "attributes": attributes,
        "images": images,
    })
     


from django.views.decorators.http import require_POST

@require_POST
def delete_product_image(request, image_id):
    if "admin_id" not in request.session:
        return JsonResponse({"status": "error", "message": "Login required"})

    # Fetch image
    image = db.selectone("SELECT * FROM product_images WHERE id=%s", (image_id,))
    if not image:
        return JsonResponse({"status": "error", "message": "Image not found"})

    # Delete file from media
    image_path = os.path.join(settings.MEDIA_ROOT, image["image"])
    if os.path.exists(image_path):
        os.remove(image_path)

    # Delete from database
    db.delete("DELETE FROM product_images WHERE id=%s", (image_id,))

    return JsonResponse({"status": "success", "message": "Image deleted successfully"})


@cache_control(no_cache=True, must_revalidate=True, no_store=True)
def approve_product(request):
    if "admin_id" not in request.session:
        return redirect("adminlogin")

    superadmin = db.selectone("SELECT * FROM adminusers WHERE id=%s", (request.session["admin_id"],))
    if not superadmin or not superadmin["is_superadmin"]:
        messages.error(request, "Access denied. Super admin only.")
        return redirect("admin-home")

    # ✅ Fetch all admins who have pending products
    pending_admins = db.selectall("""
        SELECT a.id AS admin_id,
               a.username,
               a.email,
               a.organization,
               a.phone,
               a.photo,
               COUNT(p.id) AS pending_count
        FROM adminusers a
        JOIN products p ON p.admin_id = a.id
        WHERE p.pending_approval=1 AND p.approved=0 AND p.disapproved=0
        GROUP BY a.id, a.username, a.email, a.organization, a.phone
        ORDER BY pending_count DESC
    """)

    return render(request, "superadmin/Approveproduct.html", {
        "pending_admins": pending_admins
    })

@cache_control(no_cache=True, must_revalidate=True, no_store=True)
def approve_product_list(request, admin_id):
    if "admin_id" not in request.session:
        return redirect("adminlogin")

    superadmin = db.selectone("SELECT * FROM adminusers WHERE id=%s", (request.session["admin_id"],))
    if not superadmin or not superadmin["is_superadmin"]:
        messages.error(request, "Access denied. Super admin only.")
        return redirect("admin-home")

    # ✅ Fetch all products (pending + approved + disapproved) for this admin
    products = db.selectall("""
        SELECT p.*, 
               c.name AS category_name, 
               s.name AS subcategory_name,
               b.name AS brand_name,
               a.username AS admin_name,
               (SELECT image FROM product_images WHERE product_id = p.id LIMIT 1) AS main_image
        FROM products p
        LEFT JOIN categories c ON p.category_id = c.id
        LEFT JOIN subcategories s ON p.subcategory_id = s.id
        LEFT JOIN adminusers a ON p.admin_id = a.id
        LEFT JOIN brands b ON p.brand_id = b.id
        WHERE p.admin_id=%s
        ORDER BY 
            CASE 
                WHEN p.pending_approval=1 THEN 1 
                WHEN p.approved=1 THEN 2 
                ELSE 3 
            END ASC, 
            p.id DESC
    """, (admin_id,))

    admin_user = db.selectone("SELECT * FROM adminusers WHERE id=%s", (admin_id,))
    return render(request, "superadmin/Approveproductlist.html", {
        "admin_user": admin_user,
        "products": products
    })

# ✅ Approve Product
def approve_product_action(request, product_id):
    if "admin_id" not in request.session:
        return redirect("adminlogin")

    superadmin = db.selectone("SELECT * FROM adminusers WHERE id=%s", (request.session["admin_id"],))
    if not superadmin or not superadmin["is_superadmin"]:
        messages.error(request, "Access denied.")
        return redirect("admin-home")

    product = db.selectone("SELECT * FROM products WHERE id=%s", (product_id,))
    if not product:
        messages.error(request, "Product not found.")
        return redirect("approve-product")

    # ✅ Approve
    db.update("""
        UPDATE products 
        SET approved=1, pending_approval=0, disapproved=0, disapprove_reason=NULL
        WHERE id=%s
    """, (product_id,))

    # Notify uploader
    db.insert("""
        INSERT INTO notifications (admin_id, message)
        VALUES (%s, %s)
    """, (product["admin_id"], f"✅ Your product '{product['title']}' has been approved and is now live."))

    messages.success(request, f"Product '{product['title']}' approved successfully.")
    return redirect("approve-product-list", admin_id=product["admin_id"])


# ❌ Disapprove Product
def disapprove_product_action(request, product_id):
    if "admin_id" not in request.session:
        return redirect("adminlogin")

    # must be superadmin
    superadmin = db.selectone("SELECT * FROM adminusers WHERE id=%s", (request.session["admin_id"],))
    if not superadmin or not superadmin.get("is_superadmin"):
        messages.error(request, "Access denied. Super admin only.")
        return redirect("admin-home")

    product = db.selectone("SELECT * FROM products WHERE id=%s", (product_id,))
    if not product:
        messages.error(request, "Product not found.")
        return redirect("approve-product")

    if request.method == "POST":
        # optional reason from form
        reason = request.POST.get("disapprove_reason", "").strip()
        # basic sanitization: remove HTML tags
        reason_clean = strip_tags(reason) if reason else None

        db.update("""
            UPDATE products
            SET approved=0, pending_approval=0, disapproved=1, disapprove_reason=%s
            WHERE id=%s
        """, (reason_clean, product_id))

        # Insert notification for product owner (include reason if present)
        if reason_clean:
            notif_msg = f"❌ Your product '{product['title']}' was disapproved by Superadmin. Reason: {reason_clean}"
        else:
            notif_msg = f"❌ Your product '{product['title']}' was disapproved by Superadmin."

        db.insert("""
            INSERT INTO notifications (admin_id, message)
            VALUES (%s, %s)
        """, (product["admin_id"], notif_msg))

        messages.warning(request, f"Product '{product['title']}' disapproved.")
        return redirect("approve-product-list", admin_id=product["admin_id"])

    # If someone GETs this URL directly, redirect back
    return redirect("approve-product-list", admin_id=product["admin_id"])

@cache_control(no_cache=True, must_revalidate=True, no_store=True)
def approval_list(request):
    """Show all admins who have added any products (approved, pending, or disapproved)"""
    if "admin_id" not in request.session:
        return redirect("adminlogin")

    superadmin = db.selectone("SELECT * FROM adminusers WHERE id=%s", (request.session["admin_id"],))
    if not superadmin or not superadmin["is_superadmin"]:
        messages.error(request, "Access denied. Super admin only.")
        return redirect("admin-home")

    # ✅ Fetch all admins who have at least one product
    admins_with_products = db.selectall("""
        SELECT a.id AS admin_id,
               a.username,
               a.email,
               a.organization,
               a.phone,
               a.photo,
               COUNT(p.id) AS total_products
        FROM adminusers a
        JOIN products p ON p.admin_id = a.id
        GROUP BY a.id, a.username, a.email, a.organization, a.phone, a.photo
        ORDER BY a.username ASC
    """)

    return render(request, "superadmin/ApprovalList.html", {
        "admins_with_products": admins_with_products
    })

@cache_control(no_cache=True, must_revalidate=True, no_store=True)
def approval_list_products(request, admin_id):
    """Show all products (any status) by this admin"""
    if "admin_id" not in request.session:
        return redirect("adminlogin")

    superadmin = db.selectone("SELECT * FROM adminusers WHERE id=%s", (request.session["admin_id"],))
    if not superadmin or not superadmin["is_superadmin"]:
        messages.error(request, "Access denied. Super admin only.")
        return redirect("admin-home")

    products = db.selectall("""
        SELECT p.*, 
               c.name AS category_name, 
               s.name AS subcategory_name,
               b.name AS brand_name,
               a.username AS admin_name,
               (SELECT image FROM product_images WHERE product_id = p.id LIMIT 1) AS main_image
        FROM products p
        LEFT JOIN categories c ON p.category_id = c.id
        LEFT JOIN subcategories s ON p.subcategory_id = s.id
        LEFT JOIN brands b ON p.brand_id = b.id
        LEFT JOIN adminusers a ON p.admin_id = a.id
        WHERE p.admin_id=%s
        ORDER BY p.id DESC
    """, (admin_id,))

    admin_user = db.selectone("SELECT * FROM adminusers WHERE id=%s", (admin_id,))
    return render(request, "superadmin/ApprovalListProducts.html", {
        "admin_user": admin_user,
        "products": products
    })

@cache_control(no_cache=True, must_revalidate=True, no_store=True)
def download_product_template_global(request):
    import re
    import xlsxwriter
    from io import BytesIO
    from django.http import HttpResponse

    admin_id = request.session["admin_id"]

    # Fetch all categories, subcategories, and brands for this admin
    categories = db.selectall("SELECT id, name FROM categories ORDER BY name ASC")
    subcategories = db.selectall("SELECT id, name, category_id FROM subcategories ORDER BY name ASC")
    brands = db.selectall(
        "SELECT id, name, category_id FROM brands WHERE admin_id=%s ORDER BY name ASC",
        (admin_id,)
    )

    # Create workbook
    output = BytesIO()
    wb = xlsxwriter.Workbook(output)
    ws = wb.add_worksheet("Products")
    hidden = wb.add_worksheet("Lists")
    hidden.hide()

    headers = [
        "title", "category", "subcategory", "brand", "price",
        "sale_price", "stock", "weight (kg)", "description"
    ]
    fmt = wb.add_format({"bold": True, "bg_color": "#D9E1F2", "border": 1})

    for c, h in enumerate(headers):
        ws.write(0, c, h, fmt)
        ws.set_column(c, c, 22)

    # Safe Excel name (must start with letter, no space)
    def safe_name(name):
        cleaned = re.sub(r"[^A-Za-z0-9_]", "_", name.strip())
        if not cleaned:
            cleaned = "X"
        if not cleaned[0].isalpha():
            cleaned = "N_" + cleaned
        return cleaned

    # Write category list
    cat_names = [c["name"] for c in categories]
    for i, name in enumerate(cat_names):
        hidden.write(i, 0, name)

    sub_map, brand_map = {}, {}
    col_offset = 1

    # Subcategories → group by category
    for cat in categories:
        cat_name = safe_name(cat["name"])
        subs = [s["name"] for s in subcategories if s["category_id"] == cat["id"]]
        if subs:
            for r, sname in enumerate(subs):
                hidden.write(r, col_offset, sname)
            end_row = len(subs)
            col_letter = xlsxwriter.utility.xl_col_to_name(col_offset)
            sub_map[cat_name] = f"{col_letter}$1:{col_letter}${end_row}"
            col_offset += 1

    # Brands → group by category (filtered by admin)
    for cat in categories:
        cat_name = safe_name(cat["name"])
        brs = [b["name"] for b in brands if b["category_id"] == cat["id"]]
        if brs:
            for r, bname in enumerate(brs):
                hidden.write(r, col_offset, bname)
            end_row = len(brs)
            col_letter = xlsxwriter.utility.xl_col_to_name(col_offset)
            brand_map[cat_name] = f"{col_letter}$1:{col_letter}${end_row}"
            col_offset += 1

    # Define Excel named ranges
    for cname, ref in sub_map.items():
        wb.define_name(f"{cname}_Sub", f"=Lists!{ref}")
    for cname, ref in brand_map.items():
        wb.define_name(f"{cname}_Brand", f"=Lists!{ref}")

    # Category dropdown
    ws.data_validation("B2:B200", {
        "validate": "list",
        "source": f"=Lists!$A$1:$A${len(cat_names)}"
    })

    # Subcategory dropdown (dependent)
    for row in range(2, 202):
        ws.data_validation(f"C{row}", {
            "validate": "list",
            "source": (
                f"=INDIRECT(SUBSTITUTE(SUBSTITUTE(SUBSTITUTE(SUBSTITUTE("
                f"SUBSTITUTE(TRIM($B{row}),\" \",\"_\"),\"&\",\"_\"),\"-\",\"_\"),\"/\",\"_\"),\"'\",\"_\") & \"_Sub\")"
            )
        })

    # Brand dropdown (dependent)
    for row in range(2, 202):
        ws.data_validation(f"D{row}", {
            "validate": "list",
            "source": (
                f"=INDIRECT(SUBSTITUTE(SUBSTITUTE(SUBSTITUTE(SUBSTITUTE("
                f"SUBSTITUTE(TRIM($B{row}),\" \",\"_\"),\"&\",\"_\"),\"-\",\"_\"),\"/\",\"_\"),\"'\",\"_\") & \"_Brand\")"
            )
        })

    wb.close()
    output.seek(0)

    response = HttpResponse(
        output.getvalue(),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    response["Content-Disposition"] = 'attachment; filename=\"bulk_product_upload_template.xlsx\"'
    return response



@cache_control(no_cache=True, must_revalidate=True, no_store=True)
def upload_product_excel_global(request):
    if "admin_id" not in request.session:
        return redirect("adminlogin")

    import io
    import pandas as pd
    from django.utils.safestring import mark_safe

    admin_id = request.session["admin_id"]
    admin = db.selectone("SELECT * FROM adminusers WHERE id=%s", (admin_id,))

    if not admin:
        messages.error(request, "Admin account not found. Please login again.")
        return redirect("adminlogin")

    plan_limit = 999999 if admin["is_superadmin"] else admin.get("plan_limit", 25) or 25

    product_count = db.selectone("SELECT COUNT(*) AS count FROM products WHERE admin_id=%s", (admin_id,))
    current_count = product_count["count"] if product_count else 0

    if request.method == "POST" and request.FILES.get("excel_file"):
        excel_file = request.FILES["excel_file"]
        try:
            df = pd.read_excel(excel_file)
        except Exception as e:
            messages.error(request, f"Error reading Excel file: {str(e)}")
            return redirect("products")

        required_columns = ["title", "category", "price", "stock"]
        for col in required_columns:
            if col not in df.columns:
                messages.error(request, f"Missing required column: {col}")
                return redirect("products")

        total_rows = len(df)

        if not admin["is_superadmin"] and (current_count + total_rows) > plan_limit:
            remaining = plan_limit - current_count
            preview_html = (
                df.head(5).to_html(index=False, border=0, classes="table table-bordered table-sm mb-0")
            )
            msg = mark_safe(
                f"""
                🚫 <strong>Upload rejected:</strong> You already have {current_count} products.<br>
                Your plan allows {plan_limit} total products, so you can only add {remaining} more.<br><br>
                <strong>Preview of your file:</strong><br>{preview_html}
                """
            )
            messages.error(request, msg)
            return redirect("products")

        added_count = 0
        for _, row in df.iterrows():
            title = str(row.get("title", "")).strip()
            category_name = str(row.get("category", "")).strip()
            subcategory_name = str(row.get("subcategory", "")).strip() if "subcategory" in df.columns else ""
            brand_name = str(row.get("brand", "")).strip() if "brand" in df.columns else ""

            if not title or not category_name:
                continue

            category = db.selectone("SELECT id FROM categories WHERE name=%s", (category_name,))
            if not category:
                messages.error(request, f"❌ Category '{category_name}' not found in DB.")
                return redirect("products")

            category_id = category["id"]

            subcategory_id = None
            if subcategory_name:
                sub = db.selectone(
                    "SELECT id FROM subcategories WHERE name=%s AND category_id=%s",
                    (subcategory_name, category_id),
                )
                if sub:
                    subcategory_id = sub["id"]

            brand_id = None
            if brand_name:
                # ✅ Check if the brand belongs to this admin
                brand = db.selectone(
                    "SELECT id FROM brands WHERE name=%s AND category_id=%s AND admin_id=%s",
                    (brand_name, category_id, admin_id),
                )

                if not brand:
                    if admin["is_superadmin"]:
                        # Superadmin can create global brands
                        db.insert("""
                            INSERT INTO brands (category_id, name, slug, description, image, admin_id)
                            VALUES (%s,%s,%s,%s,%s,%s)
                        """, (category_id, brand_name, brand_name.lower().replace(" ", "-"), "", "", admin_id))
                        brand = db.selectone(
                            "SELECT id FROM brands WHERE name=%s AND category_id=%s AND admin_id=%s",
                            (brand_name, category_id, admin_id),
                        )
                    else:
                        messages.error(
                            request,
                            f"⚠️ Brand '{brand_name}' does not belong to your account. Please create it in Brands section first."
                        )
                        return redirect("products")
                brand_id = brand["id"]


            price = float(row.get("price", 0) or 0)
            sale_price = float(row.get("sale_price", 0) or 0)
            stock = int(row.get("stock", 0) or 0)
            weight = float(row.get("weight (kg)", 0) or 0)  # ✅ NEW COLUMN
            description = str(row.get("description", "") or "")
            meta_title = str(row.get("meta_title", "") or "")
            meta_description = str(row.get("meta_description", "") or "")
            is_vip = str(row.get("is_vip", "")).lower() in ["true", "1", "yes"]

            # ✅ Insert Product (now includes weight)
            db.insert("""
                INSERT INTO products
                (title, category_id, subcategory_id, brand_id, price, sale_price, stock, weight, description,
                 meta_title, meta_description, admin_id, approved, pending_approval, is_vip)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """, (
                title, category_id, subcategory_id, brand_id, price, sale_price, stock, weight,
                description, meta_title, meta_description, admin_id,
                admin["is_superadmin"], not admin["is_superadmin"], is_vip
            ))

            product = db.selectone("SELECT id FROM products ORDER BY id DESC LIMIT 1")

            # ✅ Handle custom fields
            standard_cols = [
                "title", "category", "subcategory", "brand", "price", "sale_price",
                "stock", "weight (kg)", "description", "meta_title", "meta_description", "is_vip"
            ]
            for col in df.columns:
                if col not in standard_cols and pd.notna(row.get(col)):
                    db.insert(
                        "INSERT INTO product_attributes (product_id, field_name, field_value) VALUES (%s,%s,%s)",
                        (product["id"], col, str(row[col]))
                    )

            added_count += 1

        messages.success(request, f"✅ {added_count} products added successfully with weight column.")
        return redirect("products")

    return redirect("products")


def track_admin_order_open(admin_id, order_id):
    existing = db.selectone("SELECT * FROM admin_order_activity WHERE admin_id=%s AND order_id=%s", (admin_id, order_id))
    if existing:
        db.update("UPDATE admin_order_activity SET opened_at=%s, last_action=%s WHERE admin_id=%s AND order_id=%s",
                  (datetime.now(), "opened", admin_id, order_id))
    else:
        db.insert("INSERT INTO admin_order_activity (admin_id, order_id, opened_at, last_action) VALUES (%s,%s,%s,%s)",
                  (admin_id, order_id, datetime.now(), "opened"))


@cache_control(no_cache=True, must_revalidate=True, no_store=True)
def manage_alert_settings(request):
    if "admin_id" not in request.session:
        return redirect("adminlogin")

    admin_id = request.session["admin_id"]
    admin = db.selectone("SELECT * FROM adminusers WHERE id=%s", (admin_id,))
    if not admin or not admin["is_superadmin"]:
        messages.warning(request, "Access denied. Superadmin only.")
        return redirect("admin-home")

    # Fetch existing settings
    settings = db.selectone("SELECT * FROM superadmin_alert_settings ORDER BY id DESC LIMIT 1")

    if request.method == "POST":
        subject = request.POST.get("subject")
        message = request.POST.get("message")
        hours = request.POST.get("hours")

        if settings:
            db.update("""
                UPDATE superadmin_alert_settings 
                SET subject=%s, message=%s, alert_after_hours=%s, updated_at=NOW()
                WHERE id=%s
            """, (subject, message, hours, settings["id"]))
        else:
            db.insert("""
                INSERT INTO superadmin_alert_settings (subject, message, alert_after_hours)
                VALUES (%s, %s, %s)
            """, (subject, message, hours))

        messages.success(request, "✅ Alert settings updated successfully!")
        return redirect("manage-alert-settings")

    settings = db.selectone("SELECT * FROM superadmin_alert_settings ORDER BY id DESC LIMIT 1")
    return render(request, "superadmin/manage-alert-settings.html", {"settings": settings})


@cache_control(no_cache=True, must_revalidate=True, no_store=True)
def manage_plans(request):
    """Superadmin view: list all plans."""
    if "admin_id" not in request.session:
        return redirect("adminlogin")

    admin_id = request.session["admin_id"]
    admin = db.selectone("SELECT * FROM adminusers WHERE id=%s", (admin_id,))
    if not admin["is_superadmin"]:
        messages.error(request, "Access denied.")
        return redirect("admin-home")

    plans = db.selectall("SELECT * FROM plans ORDER BY id DESC")
    return render(request, "superadmin/manage_plans.html", {"plans": plans})


@cache_control(no_cache=True, must_revalidate=True, no_store=True)
def add_plan(request):
    """Superadmin: Add new monthly plan."""
    if "admin_id" not in request.session:
        return redirect("adminlogin")

    admin_id = request.session["admin_id"]
    admin = db.selectone("SELECT * FROM adminusers WHERE id=%s", (admin_id,))
    if not admin["is_superadmin"]:
        messages.error(request, "Access denied.")
        return redirect("admin-home")

    if request.method == "POST":
        plan_name = request.POST.get("plan_name", "")
        price = request.POST.get("price", 0)
        product_limit = request.POST.get("product_limit", 25)
        description = request.POST.get("description", "")
        is_active = "is_active" in request.POST

        db.insert("""
            INSERT INTO plans (plan_name, price, product_limit, description, is_active)
            VALUES (%s,%s,%s,%s,%s)
        """, (plan_name, price, product_limit, description, is_active))

        messages.success(request, f"✅ Plan '{plan_name}' added successfully.")
        return redirect("manage-plans")

    return render(request, "superadmin/add_plan.html")


@cache_control(no_cache=True, must_revalidate=True, no_store=True)
def edit_plan(request, plan_id):
    """Edit existing monthly plan"""
    if "admin_id" not in request.session:
        return redirect("adminlogin")

    admin_id = request.session["admin_id"]
    admin = db.selectone("SELECT * FROM adminusers WHERE id=%s", (admin_id,))
    if not admin["is_superadmin"]:
        messages.error(request, "Access denied.")
        return redirect("admin-home")

    plan = db.selectone("SELECT * FROM plans WHERE id=%s", (plan_id,))
    if not plan:
        messages.error(request, "Plan not found.")
        return redirect("manage-plans")

    if request.method == "POST":
        plan_name = request.POST.get("plan_name", "")
        price = request.POST.get("price", 0)
        product_limit = request.POST.get("product_limit", 0)
        description = request.POST.get("description", "")
        is_active = "is_active" in request.POST

        db.update("""
            UPDATE plans 
            SET plan_name=%s, price=%s, product_limit=%s, description=%s, is_active=%s 
            WHERE id=%s
        """, (plan_name, price, product_limit, description, is_active, plan_id))

        messages.success(request, f"✅ Plan '{plan_name}' updated successfully.")
        return redirect("manage-plans")

    return render(request, "superadmin/edit_plan.html", {"plan": plan})


@cache_control(no_cache=True, must_revalidate=True, no_store=True)
def delete_plan(request, plan_id):
    """Delete a plan (superadmin only)"""
    if "admin_id" not in request.session:
        return redirect("adminlogin")

    admin_id = request.session["admin_id"]
    admin = db.selectone("SELECT * FROM adminusers WHERE id=%s", (admin_id,))
    if not admin["is_superadmin"]:
        messages.error(request, "Access denied.")
        return redirect("admin-home")



    # 🔹 Fetch the plan
    plan = db.selectone("SELECT * FROM plans WHERE id=%s", (plan_id,))

    if not plan:
        messages.error(request, "Plan not found.")
        return redirect("manage-plans")

    # 🔹 Prevent deleting an active plan
    if plan["is_active"]:
        messages.error(
            request,
            f"⚠️ Cannot delete active plan '{plan['plan_name']}'. Please deactivate it first."
        )
        return redirect("manage-plans")

    # 🔹 Safe to delete now
    db.delete("DELETE FROM plans WHERE id=%s", (plan_id,))
    messages.success(request, f" Plan '{plan['plan_name']}' deleted successfully.")
    return redirect("manage-plans")



# ✅ Toggle Active / Inactive
@cache_control(no_cache=True, must_revalidate=True, no_store=True)
def toggle_plan_status(request, plan_id):
    """AJAX toggle plan active/inactive"""
    if "admin_id" not in request.session:
        return JsonResponse({"status": "error", "message": "Login required."})

    admin_id = request.session["admin_id"]
    admin = db.selectone("SELECT * FROM adminusers WHERE id=%s", (admin_id,))
    if not admin["is_superadmin"]:
        return JsonResponse({"status": "error", "message": "Access denied."})

    plan = db.selectone("SELECT * FROM plans WHERE id=%s", (plan_id,))
    if not plan:
        return JsonResponse({"status": "error", "message": "Plan not found."})

    new_status = not bool(plan["is_active"])  # ensure it's boolean toggle
    db.update("UPDATE plans SET is_active=%s WHERE id=%s", (new_status, plan_id))

    return JsonResponse({
        "status": "success",
        "is_active": new_status,
        "message": f"Plan '{plan['plan_name']}' is now {'Active' if new_status else 'Inactive'}."
    })


@cache_control(no_cache=True, must_revalidate=True, no_store=True)
def manage_shipping_rewards(request):
    """Superadmin page — shipping cost (separate) + reward Excel upload/delete (separate)"""
    if "admin_id" not in request.session:
        return redirect("adminlogin")

    admin_id = request.session["admin_id"]
    admin = db.selectone("SELECT * FROM adminusers WHERE id=%s", (admin_id,))
    if not admin or not admin["is_superadmin"]:
        messages.error(request, "Access denied. Superadmin only.")
        return redirect("admin-home")

    # ===============================================
    # 🚚 SHIPPING SECTION — independent
    # ===============================================
    shipping = db.selectone("SELECT * FROM shipping_settings WHERE id=1")
    if not shipping:
        db.insert("INSERT INTO shipping_settings (id, cost_per_kg) VALUES (1, 0)")
        shipping = {"id": 1, "cost_per_kg": 0}

    if request.method == "POST" and "update_shipping" in request.POST:
        new_cost = request.POST.get("cost_per_kg", "0")
        db.update("UPDATE shipping_settings SET cost_per_kg=%s WHERE id=1", (new_cost,))
        messages.success(request, f"🚚 Shipping cost updated to ₹{new_cost}/kg")
        return redirect("manage-shipping-rewards")

    if request.method == "POST" and "delete_shipping" in request.POST:
        db.update("UPDATE shipping_settings SET cost_per_kg=0 WHERE id=1")
        messages.success(request, "Shipping cost reset to ₹0/kg")
        return redirect("manage-shipping-rewards")

    # ===============================================
    # 🏅 REWARDS SECTION — separate logic
    # ===============================================
    import pandas as pd, json

    # --- Upload rewards Excel ---
    if request.method == "POST" and "upload_rewards" in request.POST:
        file = request.FILES.get("rewards_file")
        if not file:
            messages.error(request, "No file uploaded.")
            return redirect("manage-shipping-rewards")

        try:
            df = pd.read_excel(file)
            if df.empty:
                messages.warning(request, "Uploaded Excel file is empty.")
                return redirect("manage-shipping-rewards")

            df.columns = [str(c).strip().lower().replace(" ", "_") for c in df.columns]

            # Save new template
            template_name = file.name
            template_id = db.insert_return_id(
                "INSERT INTO reward_templates(template_name, is_active) VALUES(%s, 0)",
                (template_name,)
            )

            # Save field names
            for col in df.columns:
                db.insert(
                    "INSERT INTO reward_template_fields(template_id, field_name) VALUES (%s, %s)",
                    (template_id, col)
                )

            # Save each reward row
            for _, row in df.iterrows():
                record = {col: str(row.get(col, "")) for col in df.columns}
                db.insert(
                    "INSERT INTO reward_template_data(template_id, data) VALUES (%s, %s)",
                    (template_id, json.dumps(record))
                )

            messages.success(request, f"🎉 New template '{template_name}' uploaded successfully!")

        except Exception as e:
            messages.error(request, f"Upload failed: {e}")

        return redirect("manage-shipping-rewards")

    # --- Switch active template ---
    if request.method == "POST" and "set_active" in request.POST:
        active_id = request.POST.get("active_template")
        if active_id:
            db.update("UPDATE reward_templates SET is_active=0")
            db.update("UPDATE reward_templates SET is_active=1 WHERE id=%s", (active_id,))
            messages.success(request, "✅ Template switched successfully!")
            return redirect("manage-shipping-rewards")

    # --- Delete a reward ---
    delete_id = request.GET.get("delete_id")
    if delete_id:
        db.delete("DELETE FROM reward_template_data WHERE id=%s", (delete_id,))
        messages.success(request, "Reward deleted successfully.")
        return redirect("manage-shipping-rewards")

    # ===============================================
    # Fetch current data for display
    # ===============================================
    # All templates for dropdown
    all_templates = db.selectall("SELECT * FROM reward_templates ORDER BY uploaded_at DESC")

    # Active template (or fallback to latest)
    template = db.selectone("SELECT * FROM reward_templates WHERE is_active=1 ORDER BY uploaded_at DESC LIMIT 1")
    if not template:
        template = db.selectone("SELECT * FROM reward_templates ORDER BY uploaded_at DESC LIMIT 1")

    fields, rewards_data = [], []
    if template:
        fields = [f["field_name"] for f in db.selectall(
            "SELECT field_name FROM reward_template_fields WHERE template_id=%s", (template["id"],)
        )]
        rewards = db.selectall(
            "SELECT id, data FROM reward_template_data WHERE template_id=%s", (template["id"],)
        )
        for r in rewards:
            data = json.loads(r["data"])
            data["id"] = r["id"]
            rewards_data.append(data)

    # ===============================================
    # Render
    # ===============================================
    return render(
        request,
        "superadmin/manage-shipping-rewards.html",
        {
            "admin": admin,
            "shipping": shipping,
            "template": template,
            "fields": fields,
            "rewards_data": rewards_data,
            "all_templates": all_templates,
        },
    )

def issue_rewards_from_active_template(user_id, total_amount):
    """
    Issue rewards to user from the currently active reward template.
    Does NOT affect SuperCoins or unrelated reward logic.
    """
    # ✅ Get active template
    active_template = db.selectone("SELECT id FROM reward_templates WHERE is_active=1 LIMIT 1")
    if not active_template:
        return  # no active template, skip

    template_id = active_template["id"]

    # ✅ Fetch all rewards under this template
    rewards_data = db.selectall("""
        SELECT * FROM reward_template_data
        WHERE template_id=%s ORDER BY id ASC
    """, (template_id,))

    if not rewards_data:
        return

    # ✅ Loop through each rule and issue reward if purchase meets condition
    for r in rewards_data:
        try:
            min_purchase = float(r.get("min_purchase") or 0)
            reward_name = r.get("reward_name") or "Reward"
            reward_value = r.get("reward_value") or ""
            reward_desc = r.get("description") or ""
            reward_type = r.get("reward_type") or "Coupon"

            if total_amount >= min_purchase:
                # Generate unique code for this reward
                promo_code = "RWD" + ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))

                # Insert into your rewards table (not SuperCoins)
                db.insert("""
                    INSERT INTO rewards (user_id, coins_earned, source, promo_code, created_at)
                    VALUES (%s, %s, %s, %s, %s)
                """, (
                    user_id,
                    0,  # this is not supercoins
                    f"{reward_name} ({reward_type}) - {reward_desc}",
                    promo_code,
                    datetime.now(),
                ))
        except Exception as e:
            print("Reward issue failed:", e)



@cache_control(no_cache=True, must_revalidate=True, no_store=True)
def payment(request):
    """Payment page showing all available plans."""
    if "admin_id" not in request.session:
        return redirect("adminlogin")

    admin_id = request.session["admin_id"]
    admin = db.selectone("SELECT * FROM adminusers WHERE id=%s", (admin_id,))

    # Get all active plans
    all_plans = db.selectall("SELECT * FROM plans WHERE is_active=1 ORDER BY price ASC")

    return render(request, "superadmin/payment.html", {
        "all_plans": all_plans,
        "admin": admin,
    })
    
@cache_control(no_cache=True, must_revalidate=True, no_store=True)
def payment_success(request, plan_id):
    """Simulate payment success and upgrade normal admin plan limit."""
    if "admin_id" not in request.session:
        return redirect("adminlogin")

    admin_id = request.session["admin_id"]
    admin = db.selectone("SELECT * FROM adminusers WHERE id=%s", (admin_id,))
    if not admin:
        messages.error(request, "Admin not found.")
        return redirect("adminlogin")

    # Superadmin skip
    if admin["is_superadmin"]:
        messages.info(request, "Superadmin has unlimited products.")
        return redirect("products")

    # Fetch selected plan
    plan = db.selectone("SELECT * FROM plans WHERE id=%s", (plan_id,))
    if not plan:
        messages.error(request, "Invalid plan selected.")
        return redirect("payment")

    # Get current plan limit
    current_limit = admin.get("plan_limit", 25) or 25

    # Add new plan’s limit to the old total
    new_total_limit = current_limit + plan["product_limit"]

    # Update admin’s plan info
    db.update("""
        UPDATE adminusers
        SET current_plan=%s,
            plan_limit=%s,
            plan_start=NOW(),
            plan_active=1
        WHERE id=%s
    """, (plan["plan_name"], new_total_limit, admin_id))

    # Record payment
    db.insert("""
        INSERT INTO payments (admin_id, plan_id, amount, status, created_at)
        VALUES (%s, %s, %s, %s, NOW())
    """, (admin_id, plan_id, plan["price"], "success"))

    messages.success(request, f"✅ {plan['plan_name']} plan activated. You can now add up to {new_total_limit} products!")
    return redirect("products")



def admin_notifications(request):
    if "admin_id" not in request.session:
        return redirect("adminlogin")

    admin_id = request.session["admin_id"]
    notes = db.selectall("""
        SELECT * FROM notifications
        WHERE admin_id=%s ORDER BY created_at DESC
    """, (admin_id,))
    return render(request, "superadmin/admin-notifications.html", {"notifications": notes})

def mark_all_read(request):
    if "admin_id" not in request.session:
        return redirect("adminlogin")

    admin_id = request.session["admin_id"]
    db.update("UPDATE notifications SET is_read=1 WHERE admin_id=%s", (admin_id,))
    messages.success(request, "All notifications marked as read.")
    return redirect("admin-home")

def delete_notification(request, id):
    if "admin_id" not in request.session:
        return redirect("adminlogin")
    db.update("DELETE FROM notifications WHERE id=%s", (id,))
    return redirect("admin-notifications")


def delete_selected_notifications(request):
    if "admin_id" not in request.session:
        return redirect("adminlogin")

    if request.method == "POST":
        selected = request.POST.getlist("selected[]")
        if selected:
            ids = ",".join(selected)
            db.update(f"DELETE FROM notifications WHERE id IN ({ids})")
    return redirect("admin-notifications")


def delete_all_notifications(request):
    if "admin_id" not in request.session:
        return redirect("adminlogin")
    admin_id = request.session["admin_id"]
    db.update("DELETE FROM notifications WHERE admin_id=%s", (admin_id,))
    return redirect("admin-notifications")



@cache_control(no_cache=True, must_revalidate=True, no_store=True)
def order_list(request):
    if "admin_id" not in request.session:
        return redirect("adminlogin")

    admin_id = request.session["admin_id"]
    admin = db.selectone("SELECT * FROM adminusers WHERE id=%s", (admin_id,))

    # ✅ Fetch orders grouped by order_group (cart orders clubbed together)
    # For old orders without order_group, each order is its own group
    order_base_sql = """
        SELECT
            COALESCE(o.order_group, CONCAT('SINGLE-', o.id)) AS group_id,
            MIN(o.id) AS order_id,
            GROUP_CONCAT(DISTINCT o.id) AS order_ids,
            SUM(o.total_amount) AS total_amount,
            MIN(o.payment_status) AS payment_status,
            MIN(o.payment_method) AS payment_method,
            MIN(o.created_at) AS created_at,
            MIN(o.address_id) AS address_id,
            MIN(o.user_id) AS user_id,
            u.first_name,
            u.last_name,
            (SELECT status FROM order_tracking WHERE order_id=MIN(o.id) ORDER BY updated_at DESC LIMIT 1) AS current_status
        FROM orders o
        JOIN users u ON o.user_id=u.id
        JOIN products p ON o.product_id=p.id
    """
    if admin["is_superadmin"]:
        orders = db.selectall(order_base_sql + """
            WHERE o.admin_deleted=0
            GROUP BY group_id, u.id, u.first_name, u.last_name
            ORDER BY created_at DESC
        """)
    else:
        orders = db.selectall(order_base_sql + """
            WHERE p.admin_id=%s AND o.admin_deleted=0
            GROUP BY group_id, u.id, u.first_name, u.last_name
            ORDER BY created_at DESC
        """, (admin_id,))

    # ✅ Add product list for each grouped order
    for order in orders:
        oid_list = order["order_ids"].split(",")
        placeholders = ",".join(["%s"] * len(oid_list))
        if admin["is_superadmin"]:
            items = db.selectall(f"""
                SELECT
                    o.id AS order_id,
                    p.title AS product_title,
                    p.price, p.sale_price,
                    b.name AS brand_name,
                    (SELECT image FROM product_images WHERE product_id=p.id LIMIT 1) AS product_image
                FROM orders o
                JOIN products p ON o.product_id=p.id
                LEFT JOIN brands b ON p.brand_id=b.id
                WHERE o.id IN ({placeholders})
            """, tuple(oid_list))
        else:
            items = db.selectall(f"""
                SELECT
                    o.id AS order_id,
                    p.title AS product_title,
                    p.price, p.sale_price,
                    b.name AS brand_name,
                    (SELECT image FROM product_images WHERE product_id=p.id LIMIT 1) AS product_image
                FROM orders o
                JOIN products p ON o.product_id=p.id
                LEFT JOIN brands b ON p.brand_id=b.id
                WHERE o.id IN ({placeholders}) AND p.admin_id=%s
            """, tuple(oid_list) + (admin_id,))
        order["items"] = items

        # Fetch shipping address: use stored address_id, fallback to user's default
        addr = None
        if order.get("address_id"):
            addr = db.selectone("SELECT * FROM addresses WHERE id=%s", (order["address_id"],))
        if not addr and order.get("user_id"):
            addr = db.selectone("SELECT * FROM addresses WHERE user_id=%s AND is_default=TRUE LIMIT 1", (order["user_id"],))
        if addr:
            order["addr_first"] = addr.get("first_name", "")
            order["addr_last"] = addr.get("last_name", "")
            order["addr_phone"] = addr.get("phone", "")
            order["addr_line1"] = addr.get("address_line1", "")
            order["addr_line2"] = addr.get("address_line2", "")
            order["addr_city"] = addr.get("city", "")
            order["addr_state"] = addr.get("state", "")
            order["addr_country"] = addr.get("country", "")
            order["addr_zip"] = addr.get("zip_code", "")

    return render(
        request,
        "superadmin/order-list.html",
        {"orders": orders, "admin": admin}
    )


@cache_control(no_cache=True, must_revalidate=True, no_store=True)
def admin_order_details(request, order_id):
    if "admin_id" not in request.session:
        return redirect("adminlogin")

    admin_id = request.session["admin_id"]

    track_admin_order_open(admin_id, order_id)

    order_items = db.selectall("""
        SELECT 
            p.title AS product_title,
            p.price, p.sale_price,
            b.name AS brand_name,
            u.first_name, u.last_name,
            o.total_amount, o.payment_status, o.payment_method, o.created_at,
            (SELECT image FROM product_images WHERE product_id=p.id LIMIT 1) AS product_image,
            t.status AS tracking_status
        FROM orders o
        JOIN users u ON o.user_id = u.id
        JOIN products p ON o.product_id = p.id
        JOIN brands b ON p.brand_id = b.id
        LEFT JOIN order_tracking t ON t.order_id = o.id
        WHERE o.id=%s AND p.admin_id=%s
    """, (order_id, admin_id))

    if not order_items:
        messages.warning(request, "No order items found for your brands.")
        return redirect("order-list")

    return render(request, "superadmin/admin-order-details.html", {"items": order_items})



@cache_control(no_cache=True, must_revalidate=True, no_store=True)
def track_order(request, order_id):
    """User order tracking detail view"""
    if "user_id" not in request.session:
        return redirect("userlogin")
    
    user_id = request.session["user_id"]

     # ✅ Fetch order details including address and payment method
    order = db.selectone("""
        SELECT 
            o.id AS order_id,
            o.total_amount,
            o.created_at,
            o.payment_status,
            o.order_status,
            o.payment_method,
            a.first_name, a.last_name,
            a.address_line1, a.address_line2,
            a.city, a.state, a.country, a.zip_code, a.phone,
            p.title AS product_title,
            (SELECT image FROM product_images WHERE product_id=p.id LIMIT 1) AS product_image
        FROM orders o
        JOIN products p ON o.product_id = p.id
        LEFT JOIN addresses a ON a.id = COALESCE(o.address_id, (SELECT id FROM addresses WHERE user_id=o.user_id AND is_default=1 LIMIT 1))
        WHERE o.id=%s AND o.user_id=%s
    """, (order_id, user_id))

    if not order:
        messages.error(request, "Order not found.")
        return redirect("order-details")

    tracking = db.selectone("""
        SELECT * FROM order_tracking WHERE order_id=%s ORDER BY updated_at DESC LIMIT 1
    """, (order_id,))

    # ✅ Fallback if no tracking or missing status
    if not tracking or not tracking.get("status"):
        tracking = {"status": order.get("order_status", "Order Placed"), "updated_at": order.get("updated_at")}


    status_steps = ["Order Placed", "Packed", "Shipped", "Out for Delivery", "Delivered"]
     # ✅ Format address as dictionary for easier rendering
    order["address"] = {
        "first_name": order.get("first_name"),
        "last_name": order.get("last_name"),
        "address_line1": order.get("address_line1"),
        "address_line2": order.get("address_line2"),
        "city": order.get("city"),
        "state": order.get("state"),
        "country": order.get("country"),
        "zip_code": order.get("zip_code"),
        "phone": order.get("phone"),
    }

    return render(request, "user/track-order.html", {
        "order": order,
        "tracking": tracking,
        "status_steps": status_steps,
        "cart_count": get_cart_count(request.session["user_id"]),
        "wishlist_count": get_wishlist_count(request.session["user_id"]),
    })

   
def cancel_order(request, order_id):
    """User cancels an order — updates both orders and order_tracking properly."""
    if request.method != "POST":
        messages.error(request, "Invalid request method.")
        return redirect("track-order", order_id=order_id)

    reason = request.POST.get("reason", "No reason provided").strip()
    user_id = request.session.get("user_id")

    # --- Fetch order ---
    order = db.selectone("SELECT * FROM orders WHERE id=%s", (order_id,))
    if not order:
        messages.error(request, "Order not found.")
        return redirect("order-details")

    # --- Security check ---
    if user_id and order.get("user_id") != user_id:
        messages.error(request, "You are not authorized to cancel this order.")
        return redirect("order-details")

    try:
        # ✅ 1. Update the orders table
        db.update("""
            UPDATE orders
            SET order_status = %s,
                cancel_reason = %s,
                updated_at = NOW()
            WHERE id = %s
        """, ("Cancelled", reason, order_id))

        # ✅ 2. Update the order_tracking table (use only existing columns)
        tracking = db.selectone("SELECT id FROM order_tracking WHERE order_id = %s", (order_id,))
        if tracking:
            db.update("""
                UPDATE order_tracking
                SET status = %s, updated_at = NOW()
                WHERE order_id = %s
            """, ("Cancelled", order_id))
        else:
            db.insert("""
                INSERT INTO order_tracking (order_id, status, updated_at)
                VALUES (%s, %s, NOW())
            """, (order_id, "Cancelled"))

        messages.success(request, "Order cancelled successfully.")

    except Exception as e:
        print("❌ Cancel Error:", e)
        messages.error(request, "Something went wrong while cancelling your order.")

    return redirect("track-order", order_id=order_id)

@cache_control(no_cache=True, must_revalidate=True, no_store=True)
def order_delete(request):
    if request.method == "POST":
        delete_id = request.POST.get("delete_order")
        if delete_id:
            db.update("UPDATE orders SET admin_deleted=1 WHERE id=%s", (delete_id,))
            messages.success(request, "Cancelled order deleted.")
    return redirect("order-list")

@cache_control(no_cache=True, must_revalidate=True, no_store=True)
def superadmin_order_monitor(request):
    if "admin_id" not in request.session:
        return redirect("adminlogin")

    admin = db.selectone("SELECT * FROM adminusers WHERE id=%s", (request.session["admin_id"],))
    if not admin or not admin["is_superadmin"]:
        messages.error(request, "Access denied. Superadmin only.")
        return redirect("admin-home")

    # Fetch all orders + who owns the brand
    orders = db.selectall("""
        SELECT 
            o.id AS order_id,
            o.created_at,
            o.total_amount,
            u.first_name, u.last_name,
            p.title AS product_title,
            a.username AS admin_name,
            a.id AS admin_id,
            (SELECT status FROM order_tracking WHERE order_id=o.id ORDER BY updated_at DESC LIMIT 1) AS status,
            (SELECT opened_at FROM admin_order_activity WHERE order_id=o.id AND admin_id=a.id LIMIT 1) AS opened_at
        FROM orders o
        JOIN users u ON o.user_id=u.id
        JOIN products p ON o.product_id=p.id
        JOIN adminusers a ON p.admin_id=a.id
        ORDER BY o.created_at DESC
    """)

    return render(request, "superadmin/order-monitor.html", {"orders": orders})



def sellers(request):
    if "admin_id" not in request.session:
        return redirect("adminlogin")
    
    admin = db.selectone("SELECT * FROM adminusers WHERE id=%s", (request.session["admin_id"],))
    if not admin or not admin["is_superadmin"]:
        messages.error(request, "Access denied. Super admin only.")
        return redirect("admin-home")

    # Fetch all admins (you can later filter by is_admin if you have sellers too)
    data = db.selectall("SELECT * FROM adminusers ORDER BY id DESC")

    return render(request, "superadmin/Sellers.html", {"admins": data})

def add_sellers(request):
    if "admin_id" not in request.session:
        return redirect("adminlogin")

 # ✅ clear old messages before rendering this form
    storage = messages.get_messages(request)
    storage.used = True
    
    admin = db.selectone("SELECT * FROM adminusers WHERE id=%s", (request.session["admin_id"],))
    if not admin or not admin["is_superadmin"]:
        messages.error(request, "Access denied. Super admin only.")
        return redirect("admin-home")
    
    if request.method == "POST":
        name = request.POST.get("name", "").strip()
        email = request.POST.get("email", "").strip()
        phone = request.POST.get("phone", "").strip()
        password = request.POST.get("password", "").strip()
        organization = request.POST.get("organization", "").strip()
        address = request.POST.get("address", "").strip()
        joining_date = request.POST.get("joining_date", "").strip()
        photo_file = request.FILES.get("photo")

        if not name or not email or not password:
            messages.error(request, "Please fill all required fields.")
            return redirect("add-sellers")

        existing = db.selectone("SELECT * FROM adminusers WHERE email=%s", (email,))
        if existing:
            messages.error(request, "Email already exists.")
            return redirect("add-sellers")
        
        # Convert joining date
        try:
            formatted_date = datetime.strptime(joining_date, "%d/%m/%Y").date() if joining_date else None
        except ValueError:
            formatted_date = None

        photo_path = None
        if photo_file:
            fs = FileSystemStorage(location=os.path.join(settings.MEDIA_ROOT, "admins"))
            filename = get_random_string(8) + "_" + photo_file.name
            saved_name = fs.save(filename, photo_file)
            photo_path = f"admins/{saved_name}"

        hashed_pwd = make_password(password)

        db.insert("""
            INSERT INTO adminusers (username, email, phone, password, organization, address, photo, joining_date, is_superadmin)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (name, email, phone, hashed_pwd, organization, address, photo_path, formatted_date, False))

        messages.success(request, f"{name.capitalize()} created successfully!")
        return redirect("sellers")

    return render(request, "superadmin/Add-Sellers.html")

# ✅ DELETE ADMIN
def delete_admin(request, id):
    

    if "admin_id" not in request.session:
        return redirect("adminlogin")
    
    admin = db.selectone("SELECT * FROM adminusers WHERE id=%s", (request.session["admin_id"],))
    if not admin or not admin["is_superadmin"]:
        messages.error(request, "Access denied. Super admin only.")
        return redirect("admin-home")

    # Check admin exists
    admin = db.selectone("SELECT * FROM adminusers WHERE id=%s", (id,))
    if not admin:
        messages.error(request, "Admin not found.")
        return redirect("sellers")

    # Delete the photo file if it exists
    if admin["photo"]:
        photo_path = os.path.join(settings.MEDIA_ROOT, admin["photo"])
        if os.path.exists(photo_path):
            os.remove(photo_path)

    # Delete the admin record
    db.delete("DELETE FROM adminusers WHERE id=%s", (id,))
    messages.success(request, f"Admin '{admin['username']}' deleted successfully.")
    response = redirect("sellers")

    # ✅ Immediately clear message storage (prevents showing again later)
    storage = messages.get_messages(request)
    storage.used = True

    return response



# ✅ EDIT ADMIN
def edit_admin(request, id):
    if "admin_id" not in request.session:
        return redirect("adminlogin")

    # ✅ Get the logged-in admin (superadmin check)
    logged_admin = db.selectone("SELECT * FROM adminusers WHERE id=%s", (request.session["admin_id"],))
    if not logged_admin or not logged_admin["is_superadmin"]:
        messages.error(request, "Access denied. Super admin only.")
        return redirect("admin-home")

    # ✅ Get the admin record to edit
    admin_to_edit = db.selectone("SELECT * FROM adminusers WHERE id=%s", (id,))
    if not admin_to_edit:
        messages.error(request, "Admin not found.")
        return redirect("sellers")

    if request.method == "POST":
        name = request.POST.get("name", "").strip()
        email = request.POST.get("email", "").strip()
        phone = request.POST.get("phone", "").strip()
        organization = request.POST.get("organization", "").strip()
        address = request.POST.get("address", "").strip()
        joining_date = request.POST.get("joining_date", "").strip()
        photo_file = request.FILES.get("photo")

        # Convert date (dd/mm/yyyy → yyyy-mm-dd)
        try:
            formatted_date = datetime.strptime(joining_date, "%d/%m/%Y").date() if joining_date else None
        except ValueError:
            formatted_date = None

        # ✅ Handle photo update
        photo_path = admin_to_edit["photo"]
        if photo_file:
            # Delete old photo if exists
            if photo_path:
                old_photo_path = os.path.join(settings.MEDIA_ROOT, photo_path)
                if os.path.exists(old_photo_path):
                    os.remove(old_photo_path)

            fs = FileSystemStorage(location=os.path.join(settings.MEDIA_ROOT, "admins"))
            filename = get_random_string(8) + "_" + photo_file.name
            saved_name = fs.save(filename, photo_file)
            photo_path = f"admins/{saved_name}"

        # ✅ Update DB
        db.update("""
            UPDATE adminusers 
            SET username=%s, email=%s, phone=%s, organization=%s, address=%s, photo=%s, joining_date=%s
            WHERE id=%s
        """, (name, email, phone, organization, address, photo_path, formatted_date, id))

        messages.success(request, "Admin updated successfully!")
        return redirect("sellers")

    return render(request, "superadmin/edit-admin.html", {"admin": admin_to_edit})





from django.utils import timezone
from datetime import timedelta
from django.core.mail import send_mail

def check_inactive_admin_orders():
    """
    Scheduled job:
    - Reads alert settings from superadmin_alert_settings (subject, message, hours)
    - Finds normal admins who have orders older than the threshold
      that they haven’t opened yet.
    - Sends email reminder to that admin saying:
      “You haven’t opened your new order yet.”
    """

    try:
        settings_row = db.selectone("""
            SELECT subject, message, alert_after_hours 
            FROM superadmin_alert_settings 
            ORDER BY id DESC LIMIT 1
        """)
        if not settings_row:
            print("⚠️ No alert settings found.")
            return

        subject_template = settings_row["subject"]
        message_template = settings_row["message"]
        hours = int(settings_row["alert_after_hours"] or 4)
        now = timezone.now()
        threshold = now - timedelta(hours=hours)

        # Get all admins (non-super)
        admins = db.selectall("""
            SELECT id, username, email 
            FROM adminusers 
            WHERE is_superadmin=0 AND email IS NOT NULL
        """)

        for admin in admins:
            admin_id = admin["id"]
            admin_email = admin["email"]
            admin_name = admin["username"]

            # Find orders assigned to this admin that are older than threshold and not opened
            unviewed_orders = db.selectall("""
                SELECT o.id AS order_id, o.created_at
                FROM orders o
                JOIN products p ON o.product_id = p.id
                WHERE p.admin_id = %s
                  AND o.created_at <= %s
                  AND o.id NOT IN (
                      SELECT order_id FROM admin_order_activity WHERE admin_id=%s
                  )
            """, (admin_id, threshold, admin_id))

            if not unviewed_orders:
                continue  # this admin has opened all recent orders

            for order in unviewed_orders:
                order_id = order["order_id"]

                # avoid duplicates (don’t send multiple for same order)
                existing_alert = db.selectone("""
                    SELECT id FROM notifications
                    WHERE admin_id=%s 
                      AND message LIKE %s 
                      AND created_at >= %s
                    LIMIT 1
                """, (admin_id, f"%order {order_id}%", threshold))
                if existing_alert:
                    continue

                # send personalized email
                message_body = message_template
                message_body = (
                    message_body
                    .replace("{{ admin_name }}", admin_name)
                    .replace("{{ order_id }}", str(order_id))
                    .replace("{{ hours }}", str(hours))
                )

                try:
                    send_mail(
                        subject=subject_template,
                        message=message_body,
                        from_email=settings.DEFAULT_FROM_EMAIL,
                        recipient_list=[admin_email],
                        fail_silently=True,
                    )

                    # log notification
                    db.insert("""
                        INSERT INTO notifications (admin_id, message, created_at)
                        VALUES (%s, %s, NOW())
                    """, (admin_id, f"📩 Reminder: You haven't opened order {order_id} in {hours} hours."))

                    print(f"✅ Reminder sent to {admin_email} for order {order_id}")

                except Exception as e:
                    print(f"❌ Failed to send mail to {admin_email}: {e}")

    except Exception as err:
        print("check_inactive_admin_orders() error:", err)


def send_order_emails_html(user_id, order_ids):
    """
    Sends HTML emails:
      - Combined order summary to the user
      - One email per admin (only their products in the order)
      - Summary to superadmin
    """
    try:
        if not order_ids:
            return

        order_ids = [int(x) for x in order_ids]
        ids_csv = ",".join(map(str, order_ids))

        # ✅ Fetch user info
        user = db.selectone("SELECT first_name,last_name,email FROM users WHERE id=%s", (user_id,))
        user_name = (user.get("first_name","") + " " + user.get("last_name","")).strip() if user else "Customer"
        user_email = user.get("email") if user else None

        # ✅ Fetch orders + related data
        order_items = db.selectall(f"""
            SELECT 
                o.id AS order_id,
                o.total_amount,
                p.id AS product_id,
                p.title AS product_title,
                COALESCE(p.sale_price, p.price) AS unit_price,
                b.name AS brand_name,
                a.id AS admin_id,
                a.username AS admin_name,
                a.email AS admin_email
            FROM orders o
            JOIN products p ON o.product_id = p.id
            LEFT JOIN brands b ON p.brand_id = b.id
            LEFT JOIN adminusers a ON p.admin_id = a.id
            WHERE o.id IN ({ids_csv})
            ORDER BY o.id ASC
        """)

        if not order_items:
            print("⚠️ No order items found for email generation.")
            return

        print("✅ Order items fetched:", len(order_items))

        # Group by admin
        by_admin = {}
        total_amount = 0
        for it in order_items:
            admin_email = it.get("admin_email")
            if not admin_email:
                print(f"⚠️ Skipping admin for product {it['product_title']} (no email).")
                continue
            by_admin.setdefault(admin_email, {"admin_name": it.get("admin_name") or "Admin", "items": []})
            by_admin[admin_email]["items"].append(it)
            total_amount += float(it.get("unit_price") or 0)

        # ---------- USER MAIL ----------
        user_rows = ""
        for it in order_items:
            brand = it.get("brand_name") or "Unknown"
            user_rows += f"""
            <tr>
              <td style="padding:8px;border:1px solid #ddd;">{it['product_title']}</td>
              <td style="padding:8px;border:1px solid #ddd;">{brand}</td>
              <td style="padding:8px;border:1px solid #ddd;text-align:right;">₹{float(it['unit_price']):.2f}</td>
              <td style="padding:8px;border:1px solid #ddd;text-align:center;">1</td>
            </tr>
            """

        user_html = f"""
        <html><body style="font-family:Arial,sans-serif;color:#333;">
        <div style="max-width:700px;margin:0 auto;padding:20px;">
        <h2 style="color:#0d6efd;">Thank you for your order, {user_name}!</h2>
        <p>Order IDs: {', '.join(map(str, order_ids))}</p>
        <table style="width:100%;border-collapse:collapse;margin-top:12px;">
          <thead>
            <tr>
              <th style="padding:8px;border:1px solid #ddd;background:#f6f8fb;text-align:left;">Product</th>
              <th style="padding:8px;border:1px solid #ddd;background:#f6f8fb;text-align:left;">Brand</th>
              <th style="padding:8px;border:1px solid #ddd;background:#f6f8fb;text-align:right;">Price</th>
              <th style="padding:8px;border:1px solid #ddd;background:#f6f8fb;text-align:center;">Qty</th>
            </tr>
          </thead>
          <tbody>{user_rows}</tbody>
        </table>
        <p style="text-align:right;font-weight:bold;margin-top:12px;">Total: ₹{total_amount:.2f}</p>
        <hr style="margin:18px 0;">
        <p style="font-size:0.9em;color:#666;">If you have questions, reply to this mail or visit your orders page.</p>
        </div></body></html>
        """

        if user_email:
            send_mail(
                subject="🛒 Order Confirmation - Yellow Banyan",
                message=f"Your order ({order_ids}) has been placed.",
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[user_email],
                html_message=user_html,
                fail_silently=True,
            )
            print("📩 User mail sent to:", user_email)
        else:
            print("⚠️ No email for user_id:", user_id)

        # ---------- ADMIN MAIL ----------
        for admin_email, block in by_admin.items():
            items = block["items"]
            admin_name = block["admin_name"]
            subtotal = sum(float(it["unit_price"]) for it in items)
            rows = ""
            brands = set()
            for it in items:
                brands.add(it.get("brand_name") or "Unknown")
                rows += f"""
                <tr>
                  <td style="padding:8px;border:1px solid #ddd;">{it['product_title']}</td>
                  <td style="padding:8px;border:1px solid #ddd;">{it.get('brand_name') or '-'}</td>
                  <td style="padding:8px;border:1px solid #ddd;text-align:right;">₹{float(it['unit_price']):.2f}</td>
                </tr>
                """

            admin_html = f"""
            <html><body style="font-family:Arial,sans-serif;color:#333;">
            <div style="max-width:700px;margin:0 auto;padding:20px;">
            <h3 style="color:#0d6efd;">New Order received — {', '.join(brands)}</h3>
            <p>Hi {admin_name},</p>
            <p>The following items were ordered and belong to your brand(s):</p>
            <table style="width:100%;border-collapse:collapse;margin-top:12px;">
              <thead><tr>
                <th style="padding:8px;border:1px solid #ddd;background:#f6f8fb;text-align:left;">Product</th>
                <th style="padding:8px;border:1px solid #ddd;background:#f6f8fb;text-align:left;">Brand</th>
                <th style="padding:8px;border:1px solid #ddd;background:#f6f8fb;text-align:right;">Price</th>
              </tr></thead>
              <tbody>{rows}</tbody>
            </table>
            <p style="text-align:right;font-weight:bold;margin-top:12px;">Subtotal: ₹{subtotal:.2f}</p>
            <p>Please login to your admin panel to process these order(s).</p>
            </div></body></html>
            """

            send_mail(
                subject=f"🛍️ New Order Received — {', '.join(brands)}",
                message=f"New order received. Subtotal ₹{subtotal:.2f}",
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[admin_email],
                html_message=admin_html,
                fail_silently=True,
            )
            print("📩 Admin mail sent to:", admin_email)

        # ---------- SUPERADMIN MAIL ----------
        super_row = db.selectone("SELECT email, username FROM adminusers WHERE is_superadmin=1 LIMIT 1")
        if super_row and super_row.get("email"):
            send_mail(
                subject="🧾 New Order Summary - Yellow Banyan",
                message=f"User {user_name} placed {len(order_items)} item(s).",
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[super_row["email"]],
                html_message=f"<html><body><p>New order(s) placed by {user_name}.</p><p>Order IDs: {order_ids}</p><p>Total ₹{total_amount:.2f}</p></body></html>",
                fail_silently=True,
            )
            print("📩 Superadmin mail sent to:", super_row["email"])

    except Exception as e:
        print("❌ send_order_emails_html error:", e)