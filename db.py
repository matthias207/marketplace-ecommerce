import sqlite3
import os
import uuid
import click
from werkzeug.security import generate_password_hash
from flask import current_app, g

DB_PATH = os.path.join(os.path.dirname(__file__), "store.db")


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH, detect_types=sqlite3.PARSE_DECLTYPES)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


def close_db(e=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    db = get_db()
    with current_app.open_resource("schema.sql") as f:
        db.executescript(f.read().decode("utf8"))


SEED_CATEGORIES = [
    ("Electronics", "electronics", "Phones, laptops, audio, and accessories."),
    ("Home & Kitchen", "home-kitchen", "Everything for the kitchen and living room."),
    ("Fashion", "fashion", "Clothing, shoes, and accessories."),
    ("Sports & Outdoors", "sports-outdoors", "Gear for staying active."),
    ("Books & Stationery", "books-stationery", "Books, notebooks, and office supplies."),
]

# (vendor store name, vendor email) -- each becomes a user with role='vendor'
SEED_VENDORS = [
    ("Northbridge Electronics", "vendor1@example.com"),
    ("Maple & Co Home Goods", "vendor2@example.com"),
    ("Urban Thread Apparel", "vendor3@example.com"),
    ("Trailhead Outdoor Supply", "vendor4@example.com"),
    ("Inkwell Books & Office", "vendor5@example.com"),
]

# category_slug, vendor_store_name, name, short_desc, description, price, sale_price, stock, featured
SEED_PRODUCTS = [
    ("electronics", "Northbridge Electronics", "Aurora 13\" Laptop", "Lightweight laptop for everyday use",
     "A 13-inch laptop with a 10-hour battery, 16GB RAM, and a 512GB SSD. Great for students and remote work.",
     89900, 79900, 14),
    ("electronics", "Northbridge Electronics", "Pulse Wireless Earbuds", "Noise-cancelling true wireless earbuds",
     "Active noise cancellation, 28-hour battery with the case, and a snug fit for workouts or commutes.",
     12900, None, 40),
    ("electronics", "Northbridge Electronics", "Beacon Smart Speaker", "Voice-controlled speaker with rich bass",
     "Fills a room with warm, balanced sound and connects to your music library and smart home devices.",
     7900, 5900, 25),
    ("home-kitchen", "Maple & Co Home Goods", "Hearth 6-Quart Slow Cooker", "Programmable slow cooker for weeknight meals",
     "A 6-quart ceramic-insert slow cooker with three heat settings and a locking lid for transport.",
     5400, None, 20),
    ("home-kitchen", "Maple & Co Home Goods", "Linen Weave Throw Blanket", "Soft cotton-linen throw, 50x60 inches",
     "A breathable cotton-linen blend throw that works year-round, machine washable.",
     3200, 2400, 35),
    ("home-kitchen", "Maple & Co Home Goods", "Oakwood Cutting Board Set", "3-piece bamboo cutting board set",
     "Three nesting bamboo boards in graduated sizes, gentle on knife edges and easy to clean.",
     2800, None, 30),
    ("fashion", "Urban Thread Apparel", "Heritage Denim Jacket", "Classic mid-wash denim jacket",
     "A timeless mid-wash denim jacket with a relaxed fit, built from heavyweight cotton denim.",
     6900, 4900, 18),
    ("fashion", "Urban Thread Apparel", "Everyday Crew Tee 3-Pack", "Soft cotton crew neck tees, pack of 3",
     "Three breathable cotton crew tees in everyday colors, pre-shrunk for a consistent fit.",
     2400, None, 50),
    ("fashion", "Urban Thread Apparel", "Trailrunner Sneakers", "Lightweight everyday sneakers",
     "A cushioned, breathable sneaker built for all-day wear, with a grippy rubber outsole.",
     5900, None, 22),
    ("sports-outdoors", "Trailhead Outdoor Supply", "Summit 65L Backpacking Pack", "Multi-day hiking backpack",
     "A 65-liter pack with an adjustable torso fit, rain cover, and a hydration sleeve.",
     14900, 11900, 10),
    ("sports-outdoors", "Trailhead Outdoor Supply", "Basecamp 2-Person Tent", "Lightweight 3-season tent",
     "A freestanding 2-person tent that packs down small and pitches in under five minutes.",
     9900, None, 12),
    ("sports-outdoors", "Trailhead Outdoor Supply", "Insulated Steel Water Bottle", "32oz double-wall insulated bottle",
     "Keeps drinks cold for 24 hours or hot for 12, with a leakproof lid.",
     2200, None, 60),
    ("books-stationery", "Inkwell Books & Office", "The Long Horizon (Novel)", "Bestselling literary fiction",
     "A sweeping multi-generational story about a coastal town and the people who never quite leave it.",
     1899, None, 45),
    ("books-stationery", "Inkwell Books & Office", "Dot-Grid Notebook, A5", "Hardcover dot-grid notebook, 160 pages",
     "A durable hardcover notebook with dot-grid pages, an elastic closure, and a ribbon marker.",
     1400, 1000, 70),
    ("books-stationery", "Inkwell Books & Office", "Desk Organizer Tray Set", "3-piece wood-finish desk organizer",
     "A 3-piece tray set that keeps pens, sticky notes, and paperwork in their place.",
     1900, None, 33),
]

SEED_PROMOTIONS = [
    ("Back-to-school sale", "Save on laptops, notebooks, and backpacks this week only.", "SCHOOL10", 10, 1),
    ("Free shipping weekend", "Free shipping on every order over $50, no code needed.", None, None, 1),
]

DEFAULT_PASSWORD = "password123"


def seed_db():
    db = get_db()

    cat_ids = {}
    for name, slug, desc in SEED_CATEGORIES:
        cur = db.execute(
            "INSERT INTO categories (name, slug, description) VALUES (?, ?, ?)",
            (name, slug, desc),
        )
        cat_ids[slug] = cur.lastrowid

    vendor_ids = {}
    for store_name, email in SEED_VENDORS:
        cur = db.execute(
            "INSERT INTO users (name, email, password_hash, role) VALUES (?, ?, ?, 'vendor')",
            (store_name, email, generate_password_hash(DEFAULT_PASSWORD)),
        )
        user_id = cur.lastrowid
        cur2 = db.execute(
            "INSERT INTO vendors (user_id, store_name, description) VALUES (?, ?, ?)",
            (user_id, store_name, f"{store_name} sells goods through this marketplace."),
        )
        vendor_ids[store_name] = cur2.lastrowid

    for cat_slug, store_name, name, short_desc, desc, price, sale_price, stock in SEED_PRODUCTS:
        slug = name.lower().replace(" ", "-").replace("\"", "").replace(",", "").replace("/", "-")
        db.execute(
            """INSERT INTO products
               (vendor_id, category_id, name, slug, short_desc, description,
                price_cents, sale_price_cents, stock)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (vendor_ids[store_name], cat_ids[cat_slug], name, slug, short_desc, desc,
             price, sale_price, stock),
        )

    for title, desc, code, discount, active in SEED_PROMOTIONS:
        db.execute(
            "INSERT INTO promotions (title, description, code, discount_percent, active) VALUES (?, ?, ?, ?, ?)",
            (title, desc, code, discount, active),
        )

    # A ready-made customer account for testing, with starter wallet funds.
    db.execute(
        "INSERT INTO users (name, email, password_hash, role, wallet_balance_cents) VALUES (?, ?, ?, 'customer', ?)",
        ("Demo Customer", "customer@example.com", generate_password_hash(DEFAULT_PASSWORD), 5000),
    )

    db.commit()


@click.command("init-db")
def init_db_command():
    """Wipe, recreate, and reseed the database with sample vendors and products."""
    init_db()
    seed_db()
    click.echo("Initialized and seeded the database.")
    click.echo(f"Sample logins (password for all: {DEFAULT_PASSWORD}):")
    click.echo("  customer@example.com (customer, $50.00 wallet balance)")
    for _, email in SEED_VENDORS:
        click.echo(f"  {email} (vendor)")


def new_tracking_token():
    return uuid.uuid4().hex


def init_app(app):
    app.teardown_appcontext(close_db)
    app.cli.add_command(init_db_command)
