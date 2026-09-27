import hmac
import os
import secrets
from datetime import timedelta
from functools import wraps

from flask import Flask, abort, flash, jsonify, redirect, render_template, request, session, url_for
from sqlalchemy import func, select, text

from .db import AlertHistory, Product, Retailer, StatusHistory, WorkerState, make_engine, session_factory, utcnow
from .service import add_product, add_retailer, send_discord


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
        healthy_worker = bool(worker and worker.heartbeat_at and utcnow() - worker.heartbeat_at < timedelta(minutes=2))
        return render_template("dashboard.html", products=products, retailers=retailers, history=history,
                               alerts=alerts, worker=worker, healthy_worker=healthy_worker,
                               discord_configured=bool(os.getenv("DISCORD_WEBHOOK_URL")))

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

    return app


app = create_app()
