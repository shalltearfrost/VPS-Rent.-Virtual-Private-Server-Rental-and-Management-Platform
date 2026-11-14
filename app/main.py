import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from app.api import router
from app.billing.monobank import configured_gateway
from app.billing.routes import router as billing_router
from app.billing.service import run_billing_cycle
from app.config import get_settings
from app.database import get_engine
from app.services import flag_expired

logger = logging.getLogger(__name__)
STATIC_DIR = Path(__file__).parent / "static"


def scan_expired() -> None:
    with Session(get_engine()) as db, db.begin():
        flag_expired(db)


def billing_cycle() -> None:
    gateway = configured_gateway()
    if gateway is not None:
        run_billing_cycle(get_engine(), gateway)


async def expiry_worker(stop: asyncio.Event) -> None:
    while not stop.is_set():
        try:
            await asyncio.to_thread(scan_expired)
        except OperationalError:
            logger.warning("Expiry scan postponed: database unavailable")
        try:
            await asyncio.to_thread(billing_cycle)
        except OperationalError:
            logger.warning("Billing postponed: database unavailable")
        except Exception:
            logger.exception("Billing cycle failed")
        try:
            await asyncio.wait_for(
                stop.wait(), get_settings().expiry_interval_seconds
            )
        except TimeoutError:
            continue


@asynccontextmanager
async def lifespan(app: FastAPI):
    get_settings()
    stop = asyncio.Event()
    task = asyncio.create_task(expiry_worker(stop))
    yield
    stop.set()
    await task
    get_engine().dispose()


app = FastAPI(title="VPS Rent", version="0.1.0", lifespan=lifespan)
app.include_router(router)
app.include_router(billing_router)
app.mount("/assets", StaticFiles(directory=STATIC_DIR), name="assets")


@app.exception_handler(IntegrityError)
async def integrity_error(request: Request, error: IntegrityError):
    return JSONResponse(
        status_code=409,
        content={"detail": "The record conflicts with another request"},
    )


@app.exception_handler(OperationalError)
async def database_error(request: Request, error: OperationalError):
    return JSONResponse(
        status_code=503,
        content={"detail": "Database unavailable. Try again shortly."},
    )


@app.middleware("http")
async def security_headers(request: Request, call_next):
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        origin = request.headers.get("origin")
        expected = f"{request.url.scheme}://{request.url.netloc}"
        if origin and origin != expected:
            return JSONResponse(
                {"detail": "Cross-origin requests are not allowed"},
                status_code=403,
            )
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "same-origin"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; script-src 'self'; "
        "style-src 'self'; font-src 'self'; img-src 'self' data:; "
        "connect-src 'self'; frame-ancestors 'none'; "
        "base-uri 'self'; form-action 'self'"
    )
    if request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    return response


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(STATIC_DIR / "index.html")
