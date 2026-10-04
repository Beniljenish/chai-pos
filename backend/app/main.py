import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.api.v1 import (
    admin,
    auth,
    bills,
    catalogue,
    cron,
    customers,
    dayend,
    insights,
    messages,
    orders,
    payments,
    purchases,
    shifts,
    stock,
)
from app.core.config import get_settings
from app.db.session import engine

logging.basicConfig(level=logging.INFO, format='{"level":"%(levelname)s","msg":"%(message)s"}')


def create_app() -> FastAPI:
    s = get_settings()
    app = FastAPI(title="Taptallow API", version="0.1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=s.cors_origins,
        allow_methods=["*"],
        allow_headers=["Authorization", "Content-Type"],
    )
    app.include_router(auth.router, prefix="/api/v1")
    app.include_router(admin.router, prefix="/api/v1")
    app.include_router(catalogue.router, prefix="/api/v1")
    app.include_router(stock.router, prefix="/api/v1")
    app.include_router(bills.router, prefix="/api/v1")
    app.include_router(dayend.router, prefix="/api/v1")
    app.include_router(cron.router, prefix="/api/v1")
    app.include_router(shifts.router, prefix="/api/v1")
    app.include_router(orders.router, prefix="/api/v1")
    app.include_router(insights.router, prefix="/api/v1")
    app.include_router(purchases.router, prefix="/api/v1")
    app.include_router(customers.router, prefix="/api/v1")
    app.include_router(messages.router, prefix="/api/v1")
    app.include_router(payments.router, prefix="/api/v1")

    @app.get("/health", tags=["ops"])
    def health() -> dict:
        with engine.connect() as conn:
            conn.execute(text("select 1"))
        return {"status": "ok"}

    return app


app = create_app()
