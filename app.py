import os
import hmac
import hashlib
import time
from functools import wraps

import requests
from flask import (
    Flask, render_template, request, redirect, url_for, session, flash, jsonify, abort
)
from markupsafe import Markup
from werkzeug.security import generate_password_hash, check_password_hash

import db
from mailer import send_order_confirmation_email, mail_is_configured

STRIPE_SECRET_KEY = os.environ.get("STRIPE_SECRET_KEY", "")
STRIPE_PUBLISHABLE_KEY = os.environ.get("STRIPE_PUBLISHABLE_KEY", "")
STRIPE_WEBHOOK_SECRET = os.environ.get("STRIPE_WEBHOOK_SECRET", "")
SITE_URL = os.environ.get("SITE_URL", "http://127.0.0.1:5000")
STRIPE_API_BASE = "https://api.stripe.com/v1"

ICONS = {
    "electronics": '<svg viewBox="0 0 64 64" xmlns="http://www.w3.org/2000/svg"><rect x="10" y="14" width="44" height="28" rx="3" fill="#f3ecdb" stroke="#3c2415" stroke-width="2.2"/><rect x="22" y="46" width="20" height="4" rx="1.5" fill="#3c2415"/><circle cx="32" cy="28" r="6" stroke="#c08a3e" stroke-width="2" fill="none"/></svg>',
    "home-kitchen": '<svg viewBox="0 0 64 64" xmlns="http://www.w3.org/2000/svg"><path d="M14 28l18-14 18 14v22a3 3 0 01-3 3H17a3 3 0 01-3-3z" fill="#f3ecdb" stroke="#3c2415" stroke-width="2.2"/><rect x="26" y="38" width="12" height="15" fill="#c08a3e"/></svg>',
    "fashion": '<svg viewBox="0 0 64 64" xmlns="http://www.w3.org/2000/svg"><path d="M24 10l8 6 8-6 8 8-6 6v30H22V24l-6-6z" fill="#f3ecdb" stroke="#3c2415" stroke-width="2.2"/></svg>',
    "sports-outdoors": '<svg viewBox="0 0 64 64" xmlns="http://www.w3.org/2000/svg"><circle cx="32" cy="32" r="20" fill="#f3ecdb" stroke="#3c2415" stroke-width="2.2"/><path d="M14 32h36M32 14v36M19 19l26 26M45 19L19 45" stroke="#c08a3e" stroke-width="1.4"/></svg>',
    "books-stationery": '<svg viewBox="0 0 64 64" xmlns="http://www.w3.org/2000/svg"><rect x="14" y="12" width="36" height="40" rx="2" fill="#f3ecdb" stroke="#3c2415" stroke-width="2.2"/><line x1="22" y1="22" x2="42" y2="22" stroke="#c08a3e" stroke-width="2"/><line x1="22" y1="30" x2="42" y2="30" stroke="#c08a3e" stroke-width="2"/><line x1="22" y1="38" x2="36" y2="38" stroke="#c08a3e" stroke-width="2"/></svg>',
}
DEFAULT_ICON = ICONS["electronics"]

# Orders can be cancelled by the customer as long as they haven't shipped yet.
CANCELLABLE_STATUSES = {"pending", "paid", "processing"}
ORDER_STATUS_FLOW = ["pending", "paid", "processing", "shipped", "delivered"]


def create_app():
    app = Flask(__name__)
    app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-secret-change-me")
    db.init_app(app)
    register_routes(app)
    register_error_handlers(app)
    return app


# ---------------- helpers ----------------

def get_cart():
    return session.setdefault("cart", {})


def cart_count():
    return sum(session.get("cart", {}).values())


def current_user():
    user_id = session.get("user_id")
    if not user_id:
        return None
    conn = db.get_db()
    return conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("user_id"):
            flash("Please log in to continue.", "error")
            return redirect(url_for("login", next=request.path))
        return view(*args, **kwargs)
    return wrapped


def vendor_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        user = current_user()
        if not user or user["role"] != "vendor":
            flash("That page is only available to vendor accounts.", "error")
            return redirect(url_for("index"))
        return view(*args, **kwargs)
    return wrapped


def format_price(cents):
    if cents is None:
        return ""
    return f"${cents / 100:,.2f}"


def effective_price(product):
    """The price a customer actually pays: sale price if set, else list price."""
    return product["sale_price_cents"] if product["sale_price_cents"] else product["price_cents"]


def stripe_request(method, path, data=None):
    resp = requests.request(method, f"{STRIPE_API_BASE}{path}", auth=(STRIPE_SECRET_KEY, ""), data=data, timeout=15)
    return resp.json(), resp.status_code


def flatten_stripe_line_items(items):
    pairs = []
    for i, item in enumerate(items):
        prefix = f"line_items[{i}]"
        pairs.append((f"{prefix}[quantity]", item["quantity"]))
        pairs.append((f"{prefix}[price_data][currency]", "usd"))
        pairs.append((f"{prefix}[price_data][unit_amount]", item["unit_amount"]))
        pairs.append((f"{prefix}[price_data][product_data][name]", item["name"]))
    return pairs


def get_recommendations(conn, category_id, exclude_product_id, limit=4):
    return conn.execute(
        """SELECT * FROM products
           WHERE category_id = ? AND id != ? AND active = 1 AND stock > 0
           ORDER BY RANDOM() LIMIT ?""",
        (category_id, exclude_product_id, limit),
    ).fetchall()


def vendor_owns_product(conn, user_id, product_id):
    row = conn.execute(
        """SELECT p.id FROM products p
           JOIN vendors v ON v.id = p.vendor_id
           WHERE p.id = ? AND v.user_id = ?""",
        (product_id, user_id),
    ).fetchone()
    return row is not None


# ---------------- routes ----------------

def register_routes(app):

    app.jinja_env.globals["instrument_icon"] = lambda slug: Markup(ICONS.get(slug, DEFAULT_ICON))
    app.jinja_env.globals["effective_price"] = effective_price

    @app.context_processor
    def inject_lookups():
        conn = db.get_db()
        cats = conn.execute("SELECT id, slug FROM categories").fetchall()
        cat_lookup = {c["id"]: c["slug"] for c in cats}
        vendors = conn.execute("SELECT id, store_name FROM vendors").fetchall()
        vendor_lookup = {v["id"]: v["store_name"] for v in vendors}
        active_promos = conn.execute("SELECT * FROM promotions WHERE active = 1").fetchall()
        return {
            "category_slug_for": lambda cat_id: cat_lookup.get(cat_id, "electronics"),
            "vendor_name_for": lambda vendor_id: vendor_lookup.get(vendor_id, "Marketplace seller"),
            "active_promotions": active_promos,
        }

    @app.context_processor
    def inject_globals():
        return {
            "cart_count": cart_count(),
            "current_user": current_user(),
            "format_price": format_price,
            "stripe_publishable_key": STRIPE_PUBLISHABLE_KEY,
        }

    # ---------- catalog ----------

    @app.route("/")
    def index():
        conn = db.get_db()
        featured = conn.execute(
            "SELECT * FROM products WHERE active = 1 AND stock > 0 ORDER BY sale_price_cents IS NOT NULL DESC, RANDOM() LIMIT 8"
        ).fetchall()
        categories = conn.execute("SELECT * FROM categories").fetchall()
        return render_template("index.html", featured=featured, categories=categories)

    @app.route("/shop")
    @app.route("/shop/<slug>")
    def shop(slug=None):
        conn = db.get_db()
        categories = conn.execute("SELECT * FROM categories").fetchall()
        active_category = None
        query = request.args.get("q", "").strip()

        sql = "SELECT * FROM products WHERE active = 1"
        params = []
        if slug:
            active_category = conn.execute("SELECT * FROM categories WHERE slug = ?", (slug,)).fetchone()
            if active_category is None:
                flash("That category doesn't exist.", "error")
                return redirect(url_for("shop"))
            sql += " AND category_id = ?"
            params.append(active_category["id"])
        if query:
            sql += " AND name LIKE ?"
            params.append(f"%{query}%")
        sql += " ORDER BY name"

        products = conn.execute(sql, params).fetchall()
        return render_template(
            "shop.html", products=products, categories=categories,
            active_category=active_category, query=query,
        )

    @app.route("/product/<slug>")
    def product_detail(slug):
        conn = db.get_db()
        product = conn.execute("SELECT * FROM products WHERE slug = ? AND active = 1", (slug,)).fetchone()
        if product is None:
            flash("That product couldn't be found.", "error")
            return redirect(url_for("shop"))
        related = get_recommendations(conn, product["category_id"], product["id"])
        return render_template("product.html", product=product, related=related)

    # ---------- cart ----------

    @app.route("/cart")
    def cart_view():
        conn = db.get_db()
        cart = get_cart()
        items, total = [], 0
        for product_id, qty in cart.items():
            product = conn.execute("SELECT * FROM products WHERE id = ?", (product_id,)).fetchone()
            if product:
                price = effective_price(product)
                subtotal = price * qty
                total += subtotal
                items.append({"product": product, "qty": qty, "subtotal": subtotal, "price": price})
        recs = []
        if items:
            recs = get_recommendations(conn, items[0]["product"]["category_id"], items[0]["product"]["id"])
        return render_template("cart.html", items=items, total=total, recommendations=recs)

    @app.route("/cart/add/<int:product_id>", methods=["POST"])
    def cart_add(product_id):
        conn = db.get_db()
        product = conn.execute("SELECT * FROM products WHERE id = ? AND active = 1", (product_id,)).fetchone()
        if product is None:
            flash("That product couldn't be found.", "error")
            return redirect(url_for("shop"))
        if product["stock"] <= 0:
            flash("Sorry, that item is out of stock.", "error")
            return redirect(request.referrer or url_for("shop"))
        try:
            qty = max(1, int(request.form.get("quantity", 1)))
        except ValueError:
            qty = 1
        cart = get_cart()
        key = str(product_id)
        cart[key] = min(product["stock"], cart.get(key, 0) + qty)
        session["cart"] = cart
        flash(f"Added {product['name']} to your cart.", "success")
        return redirect(request.referrer or url_for("shop"))

    @app.route("/cart/update/<int:product_id>", methods=["POST"])
    def cart_update(product_id):
        cart = get_cart()
        try:
            qty = int(request.form.get("quantity", 0))
        except ValueError:
            qty = 0
        key = str(product_id)
        if qty <= 0:
            cart.pop(key, None)
        else:
            cart[key] = qty
        session["cart"] = cart
        return redirect(url_for("cart_view"))

    @app.route("/cart/remove/<int:product_id>", methods=["POST"])
    def cart_remove(product_id):
        cart = get_cart()
        cart.pop(str(product_id), None)
        session["cart"] = cart
        return redirect(url_for("cart_view"))

    # ---------- auth ----------

    @app.route("/register", methods=["GET", "POST"])
    def register():
        if request.method == "POST":
            name = request.form.get("name", "").strip()
            email = request.form.get("email", "").strip().lower()
            password = request.form.get("password", "")
            errors = []
            if not name:
                errors.append("Please enter your name.")
            if not email or "@" not in email:
                errors.append("Please enter a valid email address.")
            if len(password) < 8:
                errors.append("Passwords need at least 8 characters.")
            conn = db.get_db()
            if not errors and conn.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone():
                errors.append("An account with that email already exists.")
            if errors:
                for e in errors:
                    flash(e, "error")
                return render_template("register.html", name=name, email=email)
            conn.execute(
                "INSERT INTO users (name, email, password_hash, role) VALUES (?, ?, ?, 'customer')",
                (name, email, generate_password_hash(password)),
            )
            conn.commit()
            user = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
            session["user_id"] = user["id"]
            flash("Welcome! Your account has been created.", "success")
            return redirect(url_for("index"))
        return render_template("register.html")

    @app.route("/vendor/register", methods=["GET", "POST"])
    def vendor_register():
        if request.method == "POST":
            store_name = request.form.get("store_name", "").strip()
            name = request.form.get("name", "").strip()
            email = request.form.get("email", "").strip().lower()
            password = request.form.get("password", "")
            errors = []
            if not store_name:
                errors.append("Please enter a store name.")
            if not name:
                errors.append("Please enter your name.")
            if not email or "@" not in email:
                errors.append("Please enter a valid email address.")
            if len(password) < 8:
                errors.append("Passwords need at least 8 characters.")
            conn = db.get_db()
            if not errors and conn.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone():
                errors.append("An account with that email already exists.")
            if errors:
                for e in errors:
                    flash(e, "error")
                return render_template("vendor_register.html", store_name=store_name, name=name, email=email)
            cur = conn.execute(
                "INSERT INTO users (name, email, password_hash, role) VALUES (?, ?, ?, 'vendor')",
                (name, email, generate_password_hash(password)),
            )
            user_id = cur.lastrowid
            conn.execute(
                "INSERT INTO vendors (user_id, store_name, description) VALUES (?, ?, ?)",
                (user_id, store_name, ""),
            )
            conn.commit()
            session["user_id"] = user_id
            flash(f"Welcome, {store_name} is now live on the marketplace.", "success")
            return redirect(url_for("vendor_dashboard"))
        return render_template("vendor_register.html")

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if request.method == "POST":
            email = request.form.get("email", "").strip().lower()
            password = request.form.get("password", "")
            conn = db.get_db()
            user = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
            if user is None or not check_password_hash(user["password_hash"], password):
                flash("That email and password don't match our records.", "error")
                return render_template("login.html")
            session["user_id"] = user["id"]
            flash(f"Welcome back, {user['name']}.", "success")
            next_url = request.args.get("next")
            if next_url:
                return redirect(next_url)
            return redirect(url_for("vendor_dashboard") if user["role"] == "vendor" else url_for("index"))
        return render_template("login.html")

    @app.route("/logout", methods=["POST"])
    def logout():
        session.clear()
        flash("You've been logged out.", "success")
        return redirect(url_for("index"))

    @app.route("/account")
    @login_required
    def account():
        conn = db.get_db()
        user = current_user()
        orders = conn.execute(
            "SELECT * FROM orders WHERE user_id = ? ORDER BY created_at DESC", (user["id"],)
        ).fetchall()
        wallet_tx = conn.execute(
            "SELECT * FROM wallet_transactions WHERE user_id = ? ORDER BY created_at DESC LIMIT 20",
            (user["id"],),
        ).fetchall()
        return render_template("account.html", orders=orders, wallet_tx=wallet_tx)

    # ---------- wallet ----------

    @app.route("/wallet/topup", methods=["GET", "POST"])
    @login_required
    def wallet_topup():
        if request.method == "POST":
            try:
                amount = float(request.form.get("amount", 0))
            except ValueError:
                amount = 0
            if amount <= 0 or amount > 1000:
                flash("Enter an amount between $0.01 and $1,000.", "error")
                return redirect(url_for("wallet_topup"))
            cents = int(round(amount * 100))
            conn = db.get_db()
            user = current_user()
            conn.execute(
                "UPDATE users SET wallet_balance_cents = wallet_balance_cents + ? WHERE id = ?",
                (cents, user["id"]),
            )
            conn.execute(
                "INSERT INTO wallet_transactions (user_id, amount_cents, description) VALUES (?, ?, ?)",
                (user["id"], cents, "Wallet top-up (demo)"),
            )
            conn.commit()
            flash(f"Added {format_price(cents)} to your wallet.", "success")
            return redirect(url_for("account"))
        return render_template("wallet_topup.html")

    # ---------- checkout / payment ----------

    @app.route("/checkout", methods=["GET", "POST"])
    @login_required
    def checkout():
        conn = db.get_db()
        user = current_user()
        cart = get_cart()
        if not cart:
            flash("Your cart is empty.", "error")
            return redirect(url_for("shop"))

        items, total = [], 0
        for product_id, qty in cart.items():
            product = conn.execute("SELECT * FROM products WHERE id = ?", (product_id,)).fetchone()
            if product:
                price = effective_price(product)
                items.append({"product": product, "qty": qty, "price": price})
                total += price * qty

        if request.method == "GET":
            return render_template("checkout.html", items=items, total=total, user=user)

        payment_method = request.form.get("payment_method")
        email = request.form.get("email", "").strip() or user["email"]

        if payment_method == "wallet":
            if user["wallet_balance_cents"] < total:
                flash("Your wallet balance isn't enough to cover this order. Top it up or pay by card.", "error")
                return redirect(url_for("checkout"))
            order_id = create_order(conn, user, items, total, email, "wallet")
            conn.execute(
                "UPDATE users SET wallet_balance_cents = wallet_balance_cents - ? WHERE id = ?",
                (total, user["id"]),
            )
            conn.execute(
                "INSERT INTO wallet_transactions (user_id, amount_cents, description) VALUES (?, ?, ?)",
                (user["id"], -total, f"Order #{order_id}"),
            )
            conn.execute("UPDATE orders SET status = 'paid' WHERE id = ?", (order_id,))
            conn.commit()
            decrement_stock(conn, items)
            send_confirmation(conn, order_id)
            session["cart"] = {}
            return redirect(url_for("order_status_by_id", order_id=order_id))

        # payment_method == "card" (Stripe)
        if not STRIPE_SECRET_KEY:
            flash("Card payments aren't configured yet. Add STRIPE_SECRET_KEY to your environment, or pay by wallet.", "error")
            return redirect(url_for("checkout"))

        order_id = create_order(conn, user, items, total, email, "card")

        line_items = [{"name": it["product"]["name"], "quantity": it["qty"], "unit_amount": it["price"]} for it in items]
        form_data = [
            ("mode", "payment"),
            ("success_url", f"{SITE_URL}/checkout/success?session_id={{CHECKOUT_SESSION_ID}}&order_id={order_id}"),
            ("cancel_url", f"{SITE_URL}/checkout/cancel"),
            ("customer_email", email),
            ("client_reference_id", str(order_id)),
        ]
        form_data += flatten_stripe_line_items(line_items)

        try:
            result, status = stripe_request("POST", "/checkout/sessions", form_data)
        except requests.RequestException as exc:
            conn.execute("UPDATE orders SET status = 'cancelled' WHERE id = ?", (order_id,))
            conn.commit()
            flash(f"Couldn't reach Stripe: {exc}", "error")
            return redirect(url_for("checkout"))

        if status >= 400:
            conn.execute("UPDATE orders SET status = 'cancelled' WHERE id = ?", (order_id,))
            conn.commit()
            flash(result.get("error", {}).get("message", "Stripe couldn't start checkout."), "error")
            return redirect(url_for("checkout"))

        conn.execute("UPDATE orders SET stripe_session_id = ? WHERE id = ?", (result["id"], order_id))
        conn.commit()
        return redirect(result["url"], code=303)

    @app.route("/checkout/success")
    def checkout_success():
        order_id = request.args.get("order_id")
        session_id = request.args.get("session_id")
        conn = db.get_db()
        order = None
        if order_id:
            order = conn.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
            if order and order["status"] == "pending" and session_id:
                conn.execute("UPDATE orders SET status = 'paid' WHERE id = ?", (order["id"],))
                conn.commit()
                items = conn.execute("SELECT * FROM order_items WHERE order_id = ?", (order["id"],)).fetchall()
                decrement_stock(conn, [{"product": {"id": it["product_id"]}, "qty": it["quantity"]} for it in items])
                send_confirmation(conn, order["id"])
        session["cart"] = {}
        if order:
            return redirect(url_for("order_status_by_id", order_id=order["id"]))
        return render_template("checkout_success.html", order=None)

    @app.route("/checkout/cancel")
    def checkout_cancel():
        return render_template("checkout_cancel.html")

    @app.route("/webhooks/stripe", methods=["POST"])
    def stripe_webhook():
        payload = request.get_data()
        sig_header = request.headers.get("Stripe-Signature", "")
        if STRIPE_WEBHOOK_SECRET and not verify_stripe_signature(payload, sig_header, STRIPE_WEBHOOK_SECRET):
            return jsonify({"error": "invalid signature"}), 400
        event = request.get_json(silent=True) or {}
        if event.get("type") == "checkout.session.completed":
            stripe_session = event["data"]["object"]
            conn = db.get_db()
            conn.execute("UPDATE orders SET status = 'paid' WHERE stripe_session_id = ?", (stripe_session["id"],))
            conn.commit()
        return jsonify({"received": True})

    # ---------- order status / cancellation ----------

    @app.route("/order/<int:order_id>")
    def order_status_by_id(order_id):
        conn = db.get_db()
        order = conn.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
        if order is None:
            abort(404)
        return render_template("order_status.html", order=order, items=get_order_items(conn, order_id))

    @app.route("/order/track/<token>")
    def order_status_by_token(token):
        conn = db.get_db()
        order = conn.execute("SELECT * FROM orders WHERE tracking_token = ?", (token,)).fetchone()
        if order is None:
            abort(404)
        return render_template("order_status.html", order=order, items=get_order_items(conn, order["id"]))

    @app.route("/order/<int:order_id>/cancel", methods=["POST"])
    def order_cancel(order_id):
        conn = db.get_db()
        order = conn.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
        if order is None:
            abort(404)
        if order["status"] not in CANCELLABLE_STATUSES:
            flash("This order has already shipped, so it can no longer be cancelled.", "error")
            return redirect(url_for("order_status_by_id", order_id=order_id))

        conn.execute("UPDATE orders SET status = 'cancelled' WHERE id = ?", (order_id,))
        if order["payment_method"] == "wallet" and order["user_id"]:
            conn.execute(
                "UPDATE users SET wallet_balance_cents = wallet_balance_cents + ? WHERE id = ?",
                (order["total_cents"], order["user_id"]),
            )
            conn.execute(
                "INSERT INTO wallet_transactions (user_id, amount_cents, description) VALUES (?, ?, ?)",
                (order["user_id"], order["total_cents"], f"Refund for cancelled order #{order_id}"),
            )
        conn.commit()
        flash("Your order has been cancelled.", "success")
        return redirect(url_for("order_status_by_id", order_id=order_id))

    # ---------- vendor dashboard ----------

    @app.route("/vendor/dashboard")
    @login_required
    @vendor_required
    def vendor_dashboard():
        conn = db.get_db()
        user = current_user()
        vendor = conn.execute("SELECT * FROM vendors WHERE user_id = ?", (user["id"],)).fetchone()
        products = conn.execute("SELECT * FROM products WHERE vendor_id = ? ORDER BY created_at DESC", (vendor["id"],)).fetchall()
        order_items = conn.execute(
            """SELECT oi.*, o.status, o.created_at, p.name as product_name
               FROM order_items oi
               JOIN orders o ON o.id = oi.order_id
               JOIN products p ON p.id = oi.product_id
               WHERE oi.vendor_id = ? ORDER BY o.created_at DESC LIMIT 30""",
            (vendor["id"],),
        ).fetchall()
        return render_template("vendor_dashboard.html", vendor=vendor, products=products, order_items=order_items)

    @app.route("/vendor/products/new", methods=["GET", "POST"])
    @login_required
    @vendor_required
    def vendor_product_new():
        conn = db.get_db()
        categories = conn.execute("SELECT * FROM categories").fetchall()
        if request.method == "POST":
            ok, payload_or_errors = validate_product_form(request.form)
            if not ok:
                for e in payload_or_errors:
                    flash(e, "error")
                return render_template("vendor_product_form.html", categories=categories, form=request.form)
            user = current_user()
            vendor = conn.execute("SELECT * FROM vendors WHERE user_id = ?", (user["id"],)).fetchone()
            data = payload_or_errors
            slug = data["name"].lower().replace(" ", "-")
            conn.execute(
                """INSERT INTO products
                   (vendor_id, category_id, name, slug, short_desc, description, price_cents, sale_price_cents, stock)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (vendor["id"], data["category_id"], data["name"], slug, data["short_desc"], data["description"],
                 data["price_cents"], data["sale_price_cents"], data["stock"]),
            )
            conn.commit()
            flash("Product added.", "success")
            return redirect(url_for("vendor_dashboard"))
        return render_template("vendor_product_form.html", categories=categories, form=None)

    @app.route("/vendor/products/<int:product_id>/edit", methods=["GET", "POST"])
    @login_required
    @vendor_required
    def vendor_product_edit(product_id):
        conn = db.get_db()
        user = current_user()
        if not vendor_owns_product(conn, user["id"], product_id):
            flash("You can only edit your own products.", "error")
            return redirect(url_for("vendor_dashboard"))
        categories = conn.execute("SELECT * FROM categories").fetchall()
        product = conn.execute("SELECT * FROM products WHERE id = ?", (product_id,)).fetchone()
        if request.method == "POST":
            ok, payload_or_errors = validate_product_form(request.form)
            if not ok:
                for e in payload_or_errors:
                    flash(e, "error")
                return render_template("vendor_product_form.html", categories=categories, form=request.form, product=product)
            data = payload_or_errors
            conn.execute(
                """UPDATE products SET name=?, category_id=?, short_desc=?, description=?,
                   price_cents=?, sale_price_cents=?, stock=? WHERE id=?""",
                (data["name"], data["category_id"], data["short_desc"], data["description"],
                 data["price_cents"], data["sale_price_cents"], data["stock"], product_id),
            )
            conn.commit()
            flash("Product updated.", "success")
            return redirect(url_for("vendor_dashboard"))
        return render_template("vendor_product_form.html", categories=categories, form=product, product=product)

    @app.route("/vendor/products/<int:product_id>/delete", methods=["POST"])
    @login_required
    @vendor_required
    def vendor_product_delete(product_id):
        conn = db.get_db()
        user = current_user()
        if not vendor_owns_product(conn, user["id"], product_id):
            flash("You can only remove your own products.", "error")
            return redirect(url_for("vendor_dashboard"))
        conn.execute("UPDATE products SET active = 0 WHERE id = ?", (product_id,))
        conn.commit()
        flash("Product removed from the catalog.", "success")
        return redirect(url_for("vendor_dashboard"))


def validate_product_form(form):
    errors = []
    name = (form.get("name") or "").strip()
    category_id = form.get("category_id")
    short_desc = (form.get("short_desc") or "").strip()
    description = (form.get("description") or "").strip()

    if not name:
        errors.append("Please enter a product name.")
    if not category_id:
        errors.append("Please choose a category.")

    try:
        price = float(form.get("price", ""))
        price_cents = int(round(price * 100))
        if price_cents <= 0:
            errors.append("Price must be greater than zero.")
    except (TypeError, ValueError):
        errors.append("Please enter a valid price (e.g. 19.99).")
        price_cents = 0

    sale_price_cents = None
    sale_raw = (form.get("sale_price") or "").strip()
    if sale_raw:
        try:
            sale_price = float(sale_raw)
            sale_price_cents = int(round(sale_price * 100))
            if sale_price_cents <= 0 or (price_cents and sale_price_cents >= price_cents):
                errors.append("Sale price must be lower than the regular price.")
        except ValueError:
            errors.append("Sale price must be a number (e.g. 14.99).")

    try:
        stock = int(form.get("stock", ""))
        if stock < 0:
            errors.append("Stock can't be negative.")
    except (TypeError, ValueError):
        errors.append("Please enter a whole number for stock.")
        stock = 0

    if errors:
        return False, errors

    return True, {
        "name": name, "category_id": category_id, "short_desc": short_desc,
        "description": description, "price_cents": price_cents,
        "sale_price_cents": sale_price_cents, "stock": stock,
    }


def create_order(conn, user, items, total, email, payment_method):
    token = db.new_tracking_token()
    cur = conn.execute(
        """INSERT INTO orders (user_id, tracking_token, status, payment_method, total_cents, customer_email)
           VALUES (?, ?, 'pending', ?, ?, ?)""",
        (user["id"] if user else None, token, payment_method, total, email),
    )
    order_id = cur.lastrowid
    for it in items:
        conn.execute(
            "INSERT INTO order_items (order_id, product_id, vendor_id, quantity, price_cents) VALUES (?, ?, ?, ?, ?)",
            (order_id, it["product"]["id"], it["product"]["vendor_id"], it["qty"], it["price"]),
        )
    conn.commit()
    return order_id


def decrement_stock(conn, items):
    for it in items:
        conn.execute(
            "UPDATE products SET stock = MAX(0, stock - ?) WHERE id = ?",
            (it["qty"], it["product"]["id"]),
        )
    conn.commit()


def get_order_items(conn, order_id):
    return conn.execute(
        "SELECT oi.*, p.name, p.slug FROM order_items oi JOIN products p ON p.id = oi.product_id WHERE oi.order_id = ?",
        (order_id,),
    ).fetchall()


def send_confirmation(conn, order_id):
    order = conn.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
    items = get_order_items(conn, order_id)
    status_url = f"{SITE_URL}/order/track/{order['tracking_token']}"
    sent, error = send_order_confirmation_email(order["customer_email"], order, items, status_url)
    if not sent:
        # Don't break checkout if email fails -- just log it for the developer.
        print(f"[email not sent for order #{order_id}]: {error}")


def verify_stripe_signature(payload, sig_header, secret):
    try:
        parts = dict(p.split("=", 1) for p in sig_header.split(","))
        timestamp, signature = parts["t"], parts["v1"]
    except (KeyError, ValueError):
        return False
    signed_payload = f"{timestamp}.{payload.decode('utf-8')}"
    expected = hmac.new(secret.encode("utf-8"), signed_payload.encode("utf-8"), hashlib.sha256).hexdigest()
    if abs(time.time() - int(timestamp)) > 300:
        return False
    return hmac.compare_digest(expected, signature)


def register_error_handlers(app):
    @app.errorhandler(404)
    def not_found(e):
        return render_template("error.html", code=404, message="That page couldn't be found."), 404

    @app.errorhandler(400)
    def bad_request(e):
        return render_template("error.html", code=400, message="That request didn't look right."), 400

    @app.errorhandler(500)
    def server_error(e):
        return render_template("error.html", code=500, message="Something went wrong on our end."), 500


app = create_app()

if __name__ == "__main__":
    app.run(debug=True)
