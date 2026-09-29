import hmac
import os
import secrets
from datetime import timedelta
from functools import wraps

from flask import Flask, abort, flash, jsonify, redirect, render_template, request, session, url_for
from sqlalchemy import func, select, text

from .db import (AlertHistory, DiscoveredProduct, DiscoverySource, Product, PurchaseCandidate,
                 PurchaseEvent, PurchaseRule, Retailer, StatusHistory, WorkerState, make_engine,
                 session_factory, utcnow)
from .service import add_product, add_retailer, apply_result, resolve_adapter, send_discord, send_event
from . import adapters, discovery, purchase


def understandable_error(raw):
    if not raw:
        return ""
    if raw.startswith("HTTP 403"):
        return "The retailer denied access. We will try again later."
    if raw.startswith("HTTP 429") or raw.startswith("Rate limited"):
        return "The retailer asked us to slow down. The next check is delayed."
    if raw in ("ConnectionError", "ConnectTimeout", "ReadTimeout", "Timeout"):
        return "Could not reach the retailer. We will try again later."
    if raw in ("No unambiguous primary product signal", "Empty or unexpected product page"):
        return "Stock could not be confirmed from this page."
    if raw == "Retailer challenge or access restriction":
        return "The retailer restricted this check. We will try again later."
    if raw.startswith("HTTP "):
        return "The retailer returned an error (" + raw + "). We will try again later."
    return raw


def create_app(database_url=None, testing=False):
    app = Flask(__name__)
    secret = os.getenv("SECRET_KEY", "")
    password = os.getenv("ADMIN_PASSWORD", "")
    if not testing and (len(secret) < 32 or len(password) < 16 or
                        "replace-with" in secret or "replace-with" in password):
        raise RuntimeError("Set SECRET_KEY (32+ characters) and ADMIN_PASSWORD (16+ characters)")
    app.secret_key = secret or "test-only-secret"
    app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax",
                      SESSION_COOKIE_SECURE=os.getenv("SESSION_COOKIE_SECURE", "true").lower() == "true",
                      PERMANENT_SESSION_LIFETIME=timedelta(hours=12))
    engine = make_engine(database_url)
    factory = session_factory(engine)
    app.extensions["db_factory"] = factory
    app.jinja_env.filters["understandable_error"] = understandable_error

    @app.after_request
    def secure_headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Content-Security-Policy"] = "default-src 'self'; style-src 'self' 'unsafe-inline'; form-action 'self'; frame-ancestors 'none'"
        response.headers["Cache-Control"] = "no-store"
        return response

    def csrf():
        token = session.get("csrf")
        if not token:
            token = secrets.token_urlsafe(32)
            session["csrf"] = token
        return token

    app.jinja_env.globals["csrf_token"] = csrf

    def require_csrf():
        if not hmac.compare_digest(request.form.get("csrf", ""), session.get("csrf", "")):
            abort(400)

    def admin(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if not session.get("admin"):
                return redirect(url_for("login"))
            return view(*args, **kwargs)
        return wrapped

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if request.method == "POST":
            require_csrf()
            if password and hmac.compare_digest(request.form.get("password", ""), password):
                session.clear()
                session["admin"] = True
                session.permanent = True
                return redirect(url_for("dashboard"))
            flash("Incorrect password")
        return render_template("login.html")

    @app.post("/logout")
    @admin
    def logout():
        require_csrf()
        session.clear()
        return redirect(url_for("login"))

    @app.get("/health")
    def health():
        try:
            with factory() as db:
                db.execute(text("SELECT 1"))
                state = db.get(WorkerState, 1)
                enabled = db.scalar(select(func.count()).select_from(Product).where(Product.enabled.is_(True)))
                errors = db.scalar(select(func.count()).select_from(Product).where(Product.enabled.is_(True),
                                   Product.status.in_(("ERROR", "UNKNOWN"))))
            recent = bool(state and state.heartbeat_at and utcnow() - state.heartbeat_at < timedelta(minutes=2))
            data = {"application": "running", "database": "connected",
                    "worker": "running" if recent else "stale",
                    "last_cycle": state.last_cycle_at.isoformat() + "Z" if state and state.last_cycle_at else None,
                    "enabled_products": enabled, "products_reporting_errors": errors,
                    "discord_configured": bool(os.getenv("DISCORD_WEBHOOK_URL"))}
            return jsonify(data), 200 if recent else 503
        except Exception:
            return jsonify({"application": "running", "database": "error", "worker": "unknown"}), 503

    @app.get("/")
    @admin
    def dashboard():
        with factory() as db:
            products = db.scalars(select(Product).order_by(Product.created_at.desc())).all()
            retailers = db.scalars(select(Retailer).order_by(Retailer.name)).all()
            history = db.execute(select(StatusHistory, Product.name).join(Product).order_by(
                StatusHistory.checked_at.desc()).limit(30)).all()
            alerts = db.scalars(select(AlertHistory).order_by(AlertHistory.attempted_at.desc()).limit(10)).all()
            worker = db.get(WorkerState, 1)
            sources = db.scalars(select(DiscoverySource).order_by(DiscoverySource.id)).all()
            discoveries = db.scalars(select(DiscoveredProduct).order_by(
                DiscoveredProduct.first_seen_at.desc()).limit(20)).all()
            rules = db.scalars(select(PurchaseRule).order_by(PurchaseRule.id)).all()
            candidates = db.scalars(select(PurchaseCandidate).order_by(
                PurchaseCandidate.created_at.desc()).limit(30)).all()
            purchase_events = db.scalars(select(PurchaseEvent).order_by(PurchaseEvent.id.desc()).limit(20)).all()
        zinc_ready, zinc_detail = purchase.sandbox_ready()
        healthy_worker = bool(worker and worker.heartbeat_at and utcnow() - worker.heartbeat_at < timedelta(minutes=2))
        attention_count = sum(p.enabled and p.status in ("ERROR", "UNKNOWN") for p in products)
        return render_template("dashboard.html", products=products, retailers=retailers, history=history,
                               alerts=alerts, worker=worker, healthy_worker=healthy_worker,
                               discord_configured=bool(os.getenv("DISCORD_WEBHOOK_URL")),
                               attention_count=attention_count, sources=sources, discoveries=discoveries,
                               rules=rules, candidates=candidates, purchase_events=purchase_events,
                               product_by_id={product.id: product for product in products},
                               purchases_enabled=bool(worker and worker.purchases_enabled),
                               zinc_ready=zinc_ready, zinc_detail=zinc_detail)

    @app.post("/products")
    @admin
    def products_add():
        require_csrf()
        try:
            with factory() as db:
                add_product(db, request.form.get("name", ""), request.form.get("url", ""),
                            request.form.get("retailer") or None)
            flash("Product added")
        except ValueError as exc:
            flash(str(exc))
        return redirect(url_for("dashboard"))

    @app.post("/products/<int:product_id>/toggle")
    @admin
    def product_toggle(product_id):
        require_csrf()
        with factory() as db:
            product = db.get(Product, product_id)
            if not product:
                abort(404)
            product.enabled = not product.enabled
            if product.enabled:
                product.next_check_at = utcnow()
            db.commit()
        return redirect(url_for("dashboard"))

    @app.post("/products/<int:product_id>/delete")
    @admin
    def product_delete(product_id):
        require_csrf()
        with factory() as db:
            product = db.get(Product, product_id)
            if not product:
                abort(404)
            if db.scalar(select(PurchaseCandidate.id).where(PurchaseCandidate.product_id == product_id)):
                product.enabled = False
                db.commit()
                flash("Product paused. Purchase history must be retained, so this product cannot be removed.")
                return redirect(url_for("dashboard"))
            db.delete(product)
            db.commit()
        flash("Product removed")
        return redirect(url_for("dashboard"))

    @app.post("/retailers")
    @admin
    def retailer_add():
        require_csrf()
        try:
            with factory() as db:
                add_retailer(db, *(request.form.get(k, "") for k in (
                    "name", "domain", "example_url", "in_stock_text", "out_of_stock_text",
                    "stock_selector", "price_selector")))
            flash("Retailer added")
        except ValueError as exc:
            flash(str(exc))
        return redirect(url_for("dashboard"))

    @app.post("/retailers/<int:retailer_id>/toggle")
    @admin
    def retailer_toggle(retailer_id):
        require_csrf()
        with factory() as db:
            retailer = db.get(Retailer, retailer_id)
            if not retailer:
                abort(404)
            retailer.enabled = not retailer.enabled
            db.commit()
        return redirect(url_for("dashboard"))

    @app.post("/discord/test")
    @admin
    def discord_test():
        require_csrf()
        with factory() as db:
            success, detail = send_discord(db, test=True)
        flash(("Test sent: " if success else "Test failed: ") + detail)
        return redirect(url_for("dashboard"))

    @app.post("/discovery/sources")
    @admin
    def source_add():
        require_csrf()
        try:
            retailer = request.form.get("retailer", "")
            url = discovery.validate_source(retailer, request.form.get("url", "").strip())
            with factory() as db:
                if db.scalar(select(DiscoverySource.id).where(DiscoverySource.url == url)):
                    raise ValueError("Source URL is already configured")
                db.add(DiscoverySource(retailer=retailer, url=url, next_scan_at=utcnow()))
                db.commit()
            flash("Discovery source added. Its first successful scan will be silent.")
        except ValueError as exc:
            flash(str(exc))
        return redirect(url_for("dashboard"))

    @app.post("/discovery/sources/<int:source_id>/toggle")
    @admin
    def source_toggle(source_id):
        require_csrf()
        with factory() as db:
            source = db.get(DiscoverySource, source_id)
            if not source:
                abort(404)
            source.enabled = not source.enabled
            db.commit()
        return redirect(url_for("dashboard"))

    def rule_fields():
        mode = request.form.get("mode", "MONITOR")
        if mode not in ("MONITOR", "APPROVAL", "AUTO"):
            raise ValueError("Choose Monitor, Approval, or Auto")
        def positive(name, minimum=1):
            try:
                value = int(request.form.get(name, ""))
            except ValueError:
                raise ValueError(f"{name.replace('_', ' ').title()} must be a whole number") from None
            if value < minimum:
                raise ValueError(f"{name.replace('_', ' ').title()} must be at least {minimum}")
            return value
        values = dict(name=request.form.get("name", "").strip()[:100], mode=mode,
                      retailers=request.form.get("retailers", "").strip()[:300],
                      product_types=request.form.get("product_types", "").strip()[:500],
                      title_include=request.form.get("title_include", "").strip()[:300],
                      title_exclude=request.form.get("title_exclude", "").strip()[:300],
                      max_item_cents=positive("max_item_cents"),
                      max_order_cents=positive("max_order_cents"), quantity=positive("quantity"),
                      retailer_direct_only=request.form.get("retailer_direct_only") == "on",
                      daily_spend_cents=positive("daily_spend_cents"))
        ceiling = request.form.get("lifetime_sku_quantity", "").strip()
        values["lifetime_sku_quantity"] = int(ceiling) if ceiling else None
        if not values["name"] or values["quantity"] > 100 or (ceiling and int(ceiling) < 1):
            raise ValueError("Enter a name, quantity from 1 to 100, and a valid SKU limit")
        if values["max_order_cents"] > values["daily_spend_cents"]:
            raise ValueError("Daily ceiling must be at least the order ceiling")
        return values

    @app.post("/purchase/rules")
    @admin
    def rule_add():
        require_csrf()
        try:
            values = rule_fields()
            with factory() as db:
                db.add(PurchaseRule(**values))
                db.commit()
            flash("Rule saved disabled. Review it before enabling.")
        except ValueError as exc:
            flash(str(exc))
        return redirect(url_for("dashboard"))

    @app.post("/purchase/rules/<int:rule_id>/edit")
    @admin
    def rule_edit(rule_id):
        require_csrf()
        try:
            values = rule_fields()
            with factory() as db:
                rule = db.get(PurchaseRule, rule_id)
                if not rule:
                    abort(404)
                for key, value in values.items():
                    setattr(rule, key, value)
                rule.enabled = False
                db.commit()
            flash("Rule updated and disabled for review.")
        except ValueError as exc:
            flash(str(exc))
        return redirect(url_for("dashboard"))

    @app.post("/purchase/rules/<int:rule_id>/toggle")
    @admin
    def rule_toggle(rule_id):
        require_csrf()
        with factory() as db:
            rule = db.get(PurchaseRule, rule_id)
            if not rule:
                abort(404)
            rule.enabled = not rule.enabled
            db.commit()
        return redirect(url_for("dashboard"))

    @app.post("/purchase/switch")
    @admin
    def purchase_switch():
        require_csrf()
        with factory() as db:
            state = db.get(WorkerState, 1)
            if not state:
                state = WorkerState(id=1)
                db.add(state)
            if request.form.get("action") == "off":
                state.purchases_enabled = False
            elif request.form.get("action") == "on":
                ready, reason = purchase.sandbox_ready()
                if not ready:
                    flash(reason)
                    return redirect(url_for("dashboard"))
                state.purchases_enabled = True
            db.commit()
        flash("Sandbox purchase switch updated. Live purchasing is unavailable.")
        return redirect(url_for("dashboard"))

    @app.post("/purchase/candidates/<int:candidate_id>/<action>")
    @admin
    def candidate_decision(candidate_id, action):
        require_csrf()
        if action not in ("approve", "reject"):
            abort(404)
        with factory() as db:
            candidate = db.scalar(select(PurchaseCandidate).where(
                PurchaseCandidate.id == candidate_id).with_for_update())
            if not candidate:
                abort(404)
            if candidate.status != "PENDING_APPROVAL":
                flash("This candidate has already been handled.")
                return redirect(url_for("dashboard"))
            if action == "reject":
                candidate.status = "REJECTED"
                purchase.record(db, candidate, "REJECTED")
                flash("Candidate rejected.")
                return redirect(url_for("dashboard"))
            product = db.get(Product, candidate.product_id)
            rule = db.get(PurchaseRule, candidate.rule_id)
            try:
                _, adapter = resolve_adapter(db, product.url, product.retailer)
                result = adapters.fetch(product.url, adapter)
                apply_result(db, product, result)
            except Exception:
                db.rollback()
                candidate = db.get(PurchaseCandidate, candidate_id)
                candidate.status = "BLOCKED"
                purchase.record(db, candidate, "BLOCKED", "Product recheck failed")
                flash("Approval stopped: the product could not be rechecked.")
                return redirect(url_for("dashboard"))
            matched, reason = purchase.rule_matches(rule, product)
            allowed, limit_reason = purchase.budget_allows(db, rule, product, exclude_id=candidate.id)
            if not matched or not allowed:
                candidate.status = "BLOCKED"
                purchase.record(db, candidate, "BLOCKED", reason if not matched else limit_reason)
                flash("Approval stopped: " + (reason if not matched else limit_reason))
                return redirect(url_for("dashboard"))
            candidate.status = "APPROVED"
            purchase.record(db, candidate, "APPROVED")
            submitted = purchase.submit_candidate(db, candidate.id)
            if submitted.status == "SUBMITTED":
                send_event(db, "PURCHASE_SUBMITTED", product,
                           f"🧪 **SANDBOX PURCHASE SUBMITTED**\n{product.name}\n{product.retailer}\n"
                           f"{product.price}\n{product.url}")
            elif submitted.status == "SUBMISSION_UNKNOWN":
                send_event(db, "PURCHASE_FAILED", product,
                           f"⚠️ **SANDBOX PURCHASE OUTCOME UNKNOWN**\n{product.name}\n"
                           f"{product.retailer}\nCheck Zinc before retrying.\n{product.url}")
            flash("Sandbox order status: " + submitted.status.replace("_", " ").title())
        return redirect(url_for("dashboard"))

    return app


app = create_app()
