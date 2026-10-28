"""Sign-in, the trial clock, and one-time pass checkout."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, Response

from atlas.auth.accounts import (
    LOCK_AFTER,
    LOCK_MINUTES,
    PASSES,
    days_left,
    extend_until,
    hash_password,
    is_open,
    new_token,
    normalize_email,
    pass_catalog,
    password_ok,
    stamp,
    trial_end,
)
from atlas.auth.billing import create_checkout, signed_event
from atlas.config import Settings
from atlas.metadata.store import MetadataStore, PurchaseRow, SessionRow, UserRow

COOKIE = "atlas_session"
SESSION_DAYS = 30
LOGIN_ERROR = "Email or password is wrong"


def install_auth(app: FastAPI, settings: Settings, store: MetadataStore) -> None:
    @app.middleware("http")
    async def require_access(request: Request, call_next):
        if not settings.auth_enabled or _public(request.url.path):
            return await call_next(request)
        user = _user_from_request(store, request)
        if user is None:
            return JSONResponse(status_code=401, content={"detail": "Sign in required"})
        allowed = request.url.path in {"/auth/checkout", "/auth/logout"}
        if not allowed and not is_open(user.access_until):
            return JSONResponse(
                status_code=402,
                content={"detail": "Trial ended. Choose a pass."},
            )
        return await call_next(request)

    @app.post("/auth/register", status_code=201)
    def register(body: dict, request: Request) -> Response:
        _require_auth(settings)
        try:
            email = normalize_email(str(body.get("email", "")))
            password_hash = hash_password(str(body.get("password", "")))
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        if store.user_by_email(email) is not None:
            raise HTTPException(status_code=409, detail="An account with that email already exists")
        now = datetime.now(UTC)
        user = UserRow(
            id=uuid4().hex,
            email=email,
            password_hash=password_hash,
            created_at=stamp(now),
            access_until=stamp(trial_end(now)),
            failed_logins=0,
            locked_until=None,
        )
        store.add_user(user)
        store.audit("register", outcome="ok", detail=email)
        return _session_response(store, user, request)

    @app.post("/auth/login")
    def login(body: dict, request: Request) -> Response:
        _require_auth(settings)
        email = str(body.get("email", "")).strip().lower()
        password = str(body.get("password", ""))
        user = store.user_by_email(email)
        if user is None or _locked(user) or not password_ok(password, user.password_hash):
            if user is not None and not _locked(user):
                user.failed_logins += 1
                if user.failed_logins >= LOCK_AFTER:
                    user.locked_until = stamp(datetime.now(UTC) + timedelta(minutes=LOCK_MINUTES))
                    user.failed_logins = 0
                store.save_user(user)
            raise HTTPException(status_code=401, detail=LOGIN_ERROR)
        user.failed_logins = 0
        user.locked_until = None
        store.save_user(user)
        return _session_response(store, user, request)

    @app.post("/auth/logout")
    def logout(request: Request) -> Response:
        token = request.cookies.get(COOKIE, "")
        if token:
            store.delete_session(token)
        response = JSONResponse({"ok": True})
        response.delete_cookie(COOKIE, path="/")
        return response

    @app.get("/auth/session")
    def session(request: Request) -> dict:
        if not settings.auth_enabled:
            return {"auth": False, "open": True, "user": None}
        user = _user_from_request(store, request)
        if user is None:
            return {"auth": True, "open": False, "user": None}
        return {"auth": True, "open": is_open(user.access_until), "user": _public_user(user)}

    @app.get("/auth/passes")
    def passes() -> dict:
        return {"passes": pass_catalog()}

    @app.post("/auth/checkout")
    def checkout(body: dict, request: Request) -> dict:
        _require_auth(settings)
        user = _user_from_request(store, request)
        if user is None:
            raise HTTPException(status_code=401, detail="Sign in required")
        plan = str(body.get("plan", ""))
        if plan not in PASSES:
            raise HTTPException(status_code=422, detail="Choose a 30, 90, or 365 day pass")
        if not settings.stripe_secret_key:
            raise HTTPException(status_code=503, detail="Payments are not configured")
        base = (settings.public_base_url or str(request.base_url)).rstrip("/")
        try:
            url = create_checkout(
                secret_key=settings.stripe_secret_key,
                user_id=user.id,
                email=user.email,
                plan=plan,
                success_url=f"{base}/?paid=1",
                cancel_url=f"{base}/?paid=0",
            )
        except RuntimeError as exc:
            raise HTTPException(status_code=502, detail="Checkout could not be started") from exc
        return {"url": url}

    @app.post("/auth/webhook")
    async def webhook(request: Request) -> dict:
        payload = await request.body()
        header = request.headers.get("stripe-signature", "")
        if not settings.stripe_webhook_secret:
            raise HTTPException(status_code=503, detail="Payments are not configured")
        try:
            event = signed_event(settings.stripe_webhook_secret, payload, header)
        except ValueError:
            raise HTTPException(status_code=400, detail="Bad signature") from None
        if event.get("type") == "checkout.session.completed":
            _grant(store, event.get("data", {}).get("object", {}))
        return {"ok": True}


def _grant(store: MetadataStore, checkout: dict) -> None:
    if not isinstance(checkout, dict):
        return
    if checkout.get("payment_status") != "paid":
        return
    checkout_id = str(checkout.get("id", ""))
    meta = checkout.get("metadata") or {}
    plan = str(meta.get("plan", ""))
    user_id = str(checkout.get("client_reference_id") or meta.get("user_id", ""))
    if not checkout_id or plan not in PASSES or store.purchase_by_checkout(checkout_id) is not None:
        return
    user = store.get_user(user_id)
    if user is None:
        return
    days = PASSES[plan][0]
    user.access_until = extend_until(user.access_until, days)
    granted = store.grant_pass(
        user,
        PurchaseRow(
            id=uuid4().hex,
            user_id=user.id,
            plan=plan,
            days=days,
            stripe_session_id=checkout_id,
            created_at=stamp(datetime.now(UTC)),
        ),
    )
    if granted:
        store.audit("pass", outcome="ok", detail=f"{user.email} {plan}")


def _session_response(store: MetadataStore, user: UserRow, request: Request) -> Response:
    now = datetime.now(UTC)
    token = new_token()
    store.add_session(
        SessionRow(
            token=token,
            user_id=user.id,
            expires_at=stamp(now + timedelta(days=SESSION_DAYS)),
        )
    )
    response = JSONResponse(
        status_code=201 if request.url.path.endswith("/register") else 200,
        content={"auth": True, "open": is_open(user.access_until), "user": _public_user(user)},
    )
    response.set_cookie(
        COOKIE,
        token,
        httponly=True,
        samesite="lax",
        secure=_https(request),
        max_age=SESSION_DAYS * 24 * 60 * 60,
        path="/",
    )
    return response


def _public_user(user: UserRow) -> dict:
    return {
        "email": user.email,
        "open": is_open(user.access_until),
        "access_until": user.access_until,
        "days_left": days_left(user.access_until),
    }


def _user_from_request(store: MetadataStore, request: Request) -> UserRow | None:
    token = request.cookies.get(COOKIE, "")
    if not token:
        return None
    session = store.get_session(token)
    if session is None or not is_open(session.expires_at):
        return None
    return store.get_user(session.user_id)


def _locked(user: UserRow) -> bool:
    return bool(user.locked_until) and is_open(user.locked_until or "")


def _https(request: Request) -> bool:
    forwarded = request.headers.get("x-forwarded-proto", "")
    return forwarded.split(",")[0].strip() == "https" or request.url.scheme == "https"


def _require_auth(settings: Settings) -> None:
    if not settings.auth_enabled:
        raise HTTPException(status_code=404, detail="Sign-in is off on this install")


def _public(path: str) -> bool:
    if path in {
        "/health",
        "/auth/register",
        "/auth/login",
        "/auth/session",
        "/auth/passes",
        "/auth/webhook",
        "/auth/logout",
        "/demo",
        "/",
    }:
        return True
    if path.startswith("/assets/"):
        return True
    return path.rsplit(".", 1)[-1] in {"js", "css", "svg", "png", "jpg", "ico", "woff2"}
