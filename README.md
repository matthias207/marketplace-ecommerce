# Marketplace — Multi-Vendor E-Commerce Site

A full working e-commerce site built for a student IT project. It covers the
features you asked for:

- Product catalog with **multiple vendors**, each managing their own products
  through a vendor dashboard
- **Sales and promotions** (sale prices on products, a site-wide promotions
  banner)
- **Shopping cart** (add, update quantity, remove)
- **Customer registration** and login
- **Credit card payment** via Stripe Checkout (your card details never touch
  this app's server — Stripe handles that on their own secure page, which is
  the standard, safe way to do this)
- An **e-wallet**: customers carry a balance and can pay from it instead of a
  card
- **Email confirmation** for every order, with a link to the order status page
- **Order cancellation** for any order that hasn't shipped yet
- **Error handling** (404 / 400 / 500 pages, and form validation everywhere)
- **Product recommendations** on product pages and in the cart
- Built with plain server-rendered HTML and CSS, so it works the same in
  Internet Explorer 11 and in modern browsers (see the note at the bottom)

This guide assumes you've never done this before. Follow it top to bottom —
don't skip steps, and if something doesn't match what you see, stop and ask
rather than guessing.

---

## Part 1 — Install Python (Windows)

1. Go to https://www.python.org/downloads/ and click the yellow **Download
   Python** button.
2. Run the installer. On the **first screen**, check the box at the bottom
   that says **"Add python.exe to PATH"** before clicking Install. This is
   the most commonly missed step — without it, none of the commands below
   will work.
3. Open the **Command Prompt** (press Start, type `cmd`, press Enter).
4. Type:
   ```
   python --version
   ```
   You should see `Python 3.x.x`. If you instead see an error like "not
   recognized," Python either isn't installed or PATH wasn't checked —
   reinstall and make sure that box is ticked.

## Part 2 — Get the project running on your computer

1. Unzip this project folder somewhere easy to find, like
   `C:\Users\YourName\marketplace`.
2. Open Command Prompt and navigate into that folder:
   ```
   cd C:\Users\YourName\marketplace
   ```
3. Install the project's dependencies:
   ```
   pip install -r requirements.txt
   ```
4. Create the database with sample products and vendors already loaded:
   ```
   set FLASK_APP=app.py
   flask init-db
   ```
   This prints out some test login emails and a shared password
   (`password123`) — write those down, you'll use them to log in and explore.
5. Start the site:
   ```
   flask run
   ```
6. Open your browser to **http://127.0.0.1:5000** — the site should be
   running. Try logging in as `customer@example.com` / `password123`, add
   something to your cart, and look around the vendor side by logging in as
   `vendor1@example.com` / `password123`.

At this point, card payments and emails won't work yet — that's expected,
we'll turn those on next.

## Part 3 — Set up Stripe (credit card payments)

Stripe is the payment processor; it's what actually talks to Visa/Mastercard
behind the scenes. It's free to set up and use in **test mode**, which uses
fake card numbers instead of real money — perfect for a class project.

1. Go to https://dashboard.stripe.com/register and create a free account.
2. Once logged in, make sure you're in **Test mode** (there's a toggle near
   the top of the dashboard — it should already default to test mode).
3. Go to **Developers → API keys**. You'll see two values:
   - **Publishable key** (starts with `pk_test_...`)
   - **Secret key** (starts with `sk_test_...`) — click "Reveal" to see it
4. In your project folder, copy `.env.example` to a new file named `.env`,
   and paste those two values in:
   ```
   STRIPE_SECRET_KEY=sk_test_yourkeyhere
   STRIPE_PUBLISHABLE_KEY=pk_test_yourkeyhere
   ```
5. Since plain `flask run` doesn't read `.env` files automatically, set the
   values in your Command Prompt session before running the app:
   ```
   set STRIPE_SECRET_KEY=sk_test_yourkeyhere
   set STRIPE_PUBLISHABLE_KEY=pk_test_yourkeyhere
   flask run
   ```
6. Restart the site, add something to your cart, and check out by card. On
   Stripe's payment page, use the test card number **4242 4242 4242 4242**,
   any future expiry date, any 3-digit CVC, and any ZIP code. No real money
   moves.

## Part 4 — Set up email confirmations (Mailtrap)

Mailtrap is a free service that catches emails your app sends, so you can see
them without needing a real inbox or risking sending real email to strangers
during testing.

1. Go to https://mailtrap.io and sign up for a free account.
2. After logging in, go to **Email Testing → Inboxes** and open the default
   inbox.
3. Click **SMTP Settings**, and choose the "Integrations" view showing
   Python/SMTP credentials. You'll see a host, port, username, and password.
4. Add those to your `.env` file (or `set` them in Command Prompt like the
   Stripe keys above):
   ```
   MAIL_HOST=sandbox.smtp.mailtrap.io
   MAIL_PORT=2525
   MAIL_USERNAME=your-username-from-mailtrap
   MAIL_PASSWORD=your-password-from-mailtrap
   MAIL_FROM=orders@example.com
   ```
5. Restart the site and place a test order. Check your Mailtrap inbox in the
   browser — the confirmation email (with the order tracking link) should
   show up there within a few seconds.

## Part 5 — Put it live on the internet

For a class project, **Render** (https://render.com) is one of the simplest
free options — no credit card needed for small projects, and it deploys
straight from a zip or a GitHub repository.

1. Create a free account at https://render.com.
2. Put this project's code on GitHub: create a free GitHub account at
   https://github.com if you don't have one, create a new repository, and
   upload this project's folder to it (GitHub's website has an "upload
   files" option if you'd rather not use git commands).
3. In Render, click **New → Web Service**, connect your GitHub repository,
   and use these settings:
   - **Build command:** `pip install -r requirements.txt && flask init-db`
   - **Start command:** `gunicorn app:app`
   - Add a line `gunicorn` to `requirements.txt` first (it's the production
     web server — the one built into Flask is for development only).
4. Under **Environment**, add the same variables as your `.env` file:
   `SECRET_KEY`, `STRIPE_SECRET_KEY`, `STRIPE_PUBLISHABLE_KEY`, `MAIL_HOST`,
   `MAIL_PORT`, `MAIL_USERNAME`, `MAIL_PASSWORD`, `MAIL_FROM`, and `SITE_URL`
   set to the URL Render gives you (something like
   `https://your-app.onrender.com`).
5. Click **Deploy**. After a minute or two, your site is live at that URL —
   that's the link you'd share with your instructor or anyone else.

Once it's live, go back to Stripe's dashboard and add a webhook endpoint
pointing at `https://your-app.onrender.com/webhooks/stripe`, subscribed to
the `checkout.session.completed` event, and put the signing secret it gives
you into `STRIPE_WEBHOOK_SECRET`. This makes order status update reliably
even if someone closes their browser right after paying.

## Demo accounts (after running `flask init-db`)

| Email | Role | Password |
|---|---|---|
| customer@example.com | Customer (with $50 wallet balance) | password123 |
| vendor1@example.com | Vendor — Northbridge Electronics | password123 |
| vendor2@example.com | Vendor — Maple & Co Home Goods | password123 |
| vendor3@example.com | Vendor — Urban Thread Apparel | password123 |
| vendor4@example.com | Vendor — Trailhead Outdoor Supply | password123 |
| vendor5@example.com | Vendor — Inkwell Books & Office | password123 |

## How the features map to files (useful for your write-up)

- `schema.sql` / `db.py` — database structure and seed data
- `app.py` — all the routes: catalog, cart, checkout, vendor dashboard, order
  status/cancellation, wallet, error handlers
- `mailer.py` — order confirmation emails
- `templates/` — every page's HTML
- `static/css/style.css` — all styling

## A note on Internet Explorer

The site is built with standard server-rendered HTML forms and links rather
than a JavaScript framework, so the core functionality (browsing, cart,
checkout, accounts) works in Internet Explorer 11 as well as Chrome, Firefox,
Edge, and Safari. Some modern visual touches (rounded corners, custom fonts)
may render more plainly in IE11, but nothing breaks functionally. If your
assignment specifically requires IE11 testing, note that Microsoft ended
support for IE11 in 2022, so testing it usually means using a virtual machine
or browser emulation tool.
