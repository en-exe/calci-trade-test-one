"""FastAPI dashboard serving Jinja2 HTML templates."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from src.db import Database

app = FastAPI(title="Calci-Trade Dashboard")

TEMPLATE_DIR = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATE_DIR))

# Injected at startup by main.py
db: Database | None = None
shared_state: dict = {}


def init_dashboard(database: Database, state: dict) -> None:
    global db, shared_state
    db = database
    shared_state = state


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    assert db is not None
    stats = await db.get_trade_stats()
    snapshots = await db.get_snapshots(limit=60)
    today_trades = await db.get_today_trades()
    open_trades = await db.get_open_trades()
    activity = await db.get_activity_log(limit=30)

    total = stats.get("total", 0) or 0
    wins = stats.get("wins", 0) or 0
    losses = stats.get("losses", 0) or 0
    total_pnl = stats.get("total_pnl", 0) or 0
    win_rate = (wins / (wins + losses) * 100) if (wins + losses) > 0 else 0.0

    snap_labels = [s["timestamp"][:16] for s in reversed(snapshots)]
    snap_values = [s["balance"] / 100 for s in reversed(snapshots)]

    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "balance": shared_state.get("balance", 0),
        "total_pnl": total_pnl,
        "win_rate": round(win_rate, 1),
        "wins": wins,
        "losses": losses,
        "total_trades": total,
        "today_trades": today_trades,
        "open_trades": open_trades,
        "snap_labels": snap_labels,
        "snap_values": snap_values,
        "paused": shared_state.get("paused", False),
        "activity": activity,
    })


@app.get("/trades", response_class=HTMLResponse)
async def trades_page(request: Request):
    assert db is not None
    all_trades = await db.get_all_trades(limit=500)
    return templates.TemplateResponse("trades.html", {
        "request": request,
        "trades": all_trades,
    })


@app.get("/markets", response_class=HTMLResponse)
async def markets_page(request: Request):
    assert db is not None
    recent_scans = await db.get_recent_scans(limit=10)
    opportunities = shared_state.get("opportunities", [])
    return templates.TemplateResponse("markets.html", {
        "request": request,
        "opportunities": opportunities,
        "recent_scans": recent_scans,
    })


@app.post("/toggle-pause")
async def toggle_pause():
    assert db is not None
    current = await db.get_setting("paused", "false")
    new_val = "false" if current == "true" else "true"
    await db.set_setting("paused", new_val)
    shared_state["paused"] = new_val == "true"
    return RedirectResponse("/", status_code=303)


@app.get("/api/activity")
async def api_activity():
    """JSON endpoint for live activity feed polling."""
    assert db is not None
    activity = await db.get_activity_log(limit=30)
    return JSONResponse(content={"activity": activity})
