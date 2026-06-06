# Yellow Banyan E-commerce — Project Context

## Overview
Full-featured e-commerce platform with multi-seller support, product approval workflows, VIP user tiers, and an admin dashboard. Deployed on AWS EC2 at `yellowbanyan.com`.

## Tech Stack
- **Backend:** Python 3, Django 4.2+
- **Database:** MySQL (via PyMySQL) — raw SQL only, no Django ORM
- **Frontend:** Django templates, Bootstrap, jQuery, Slick Carousel, Nouislider
- **Production:** Gunicorn + Nginx on AWS EC2
- **CI/CD:** GitHub Actions (auto-deploys on push to `main`)

## Project Structure
```
Ecom/           Django project config (settings.py, urls.py)
app/
  views.py      All view functions (~5 000+ lines, function-based)
  urls.py       163 URL routes
  db.py         Raw SQL helpers: insert(), selectall(), selectone(), update(), delete()
  models.py     Empty — database tables managed externally (no migrations for data tables)
  middleware.py Custom middleware
  context_processors.py  Template context globals
  templatetags/ Custom template tags
  templates/    All HTML (base.html, shop-*.html, user/, superadmin/)
  static/assets/ CSS, JS, vendor libs (Bootstrap, Slick, Feather Icons)
deployment/     Gunicorn systemd service + setup instructions
.github/workflows/deploy.yml  10-stage CI/CD pipeline
```

## Architecture Decisions
- **Raw SQL over ORM:** All database access goes through `app/db.py` helpers. Do not introduce Django ORM queries — keep using the existing `insert()`, `selectall()`, `selectone()`, `update()`, `delete()` pattern.
- **Fat views:** Business logic lives in `app/views.py`. No separate service layer.
- **Session auth:** Two separate tables — `users` (shoppers) and `adminusers` (admins/superadmin). Session keys differ between them.
- **VIP system:** Some brands are restricted to VIP users; enforced in views and templates.
- **No migrations for data tables:** `manage.py migrate` only applies Django's built-in migrations. Custom tables are created/altered directly in MySQL.

## Common Commands
```bash
# Development server
python manage.py runserver

# Collect static files (required after any static file change in prod)
python manage.py collectstatic --noinput

# Apply Django built-in migrations only
python manage.py migrate

# Production restart (on server)
sudo systemctl restart gunicorn
sudo systemctl reload nginx
```

## Coding Conventions
- Function-based views throughout — do not introduce class-based views.
- All DB calls use `app/db.py` helpers, not raw `cursor.execute()` inline.
- CSRF tokens required on all POST forms (`{% csrf_token %}`).
- Template inheritance from `base.html`; admin pages extend `superadmin/base.html`.
- Static files live under `app/static/assets/`; media uploads go to `/media/`.
- No test suite in active use — verify changes manually via the running server.

## Key Features / Areas
| Area | Entry point |
|---|---|
| Product catalog, search, filtering | `views.py` → `shop_grid`, `category_products` |
| Cart & wishlist | `views.py` → `cart_*`, `wishlist_*` |
| Checkout & orders | `views.py` → `checkout`, `order_*` |
| Admin dashboard | `views.py` → `superadmin_*`; templates in `superadmin/` |
| Seller management | `views.py` → `seller_*` |
| User auth | `views.py` → `signin`, `signup`, `forgot_password` |
| VIP/rewards | `views.py` → `vip_*`, `rewards_*` |
| Scheduled tasks | `django-crontab` — checks inactive admin orders hourly |

## Environment & Secrets
- `.env` file is gitignored — contains `SECRET_KEY`, DB credentials, email password.
- `Ecom/settings.py` reads these at startup.
- Allowed hosts: `yellowbanyan.com`, `www.yellowbanyan.com`, `localhost`.
- CSRF trusted origins include Cloudflare/HTTPS domains.

## Deployment
Push to `main` → GitHub Actions auto-deploys: pulls code, installs deps, runs migrations, collects static, restarts Gunicorn, reloads Nginx, health checks.
The `/media/` folder is never overwritten during deployment.
