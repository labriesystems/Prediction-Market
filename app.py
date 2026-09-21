import math
import os
import sqlite3
from datetime import datetime, timezone
from functools import wraps

import click
from flask import Flask, abort, flash, g, redirect, render_template, request, session, url_for

app = Flask(__name__)
app.config.update(
    SECRET_KEY=os.getenv("SECRET_KEY", "dev-change-me"),
DATABASE=os.getenv("DATABASE", os.path.join(app.root_path, "prediction_market.db")),

def db():
    if "db" not in g:
        g.db = sqlite3.connect(app.config["DATABASE"])
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


@app.teardown_appcontext
def close_db(_error=None):
    connection = g.pop("db", None)
    if connection is not None:
        connection.close()


def init_db():
    with app.open_resource("schema.sql") as schema:
        db().executescript(schema.read().decode("utf8"))
    db().commit()


def ensure_db():
    connection = db()
    table = connection.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='users'"
    ).fetchone()

    if table is None:
        init_db()

@app.cli.command("init-db")
def init_db_command():
    init_db()
    click.echo("Initialized database.")


@app.cli.command("seed")
def seed_command():
    init_db()
    examples = [
        ("Will an AI-generated song reach Billboard's Hot 100 top 10 before 2028?", "Resolves YES if Billboard credits a substantially AI-generated recording in the top 10 before 2028-01-01.", "Music", "2027-12-31T23:59", "Billboard Hot 100 archive"),
        ("Will a private company land humans on the Moon before 2030?", "Resolves YES when a privately operated mission lands at least one living human on the Moon.", "Technology", "2029-12-31T23:59", "NASA and mission operator confirmation"),
        ("Will a new company enter the S&P 500 with an AI-first product before 2028?", "Resolves YES if an AI-first company is newly added to the index before 2028-01-01.", "Business", "2027-12-31T23:59", "S&P Dow Jones Indices announcement"),
    ]
    db().executemany("INSERT OR IGNORE INTO markets(question,description,category,closes_at,resolution_source) VALUES(?,?,?,?,?)", examples)
    db().commit()
    click.echo("Seeded demo markets.")


@app.before_request
def load_user():
    ensure_db()
    g.user = None

def login_required(view):
    @wraps(view)
    def wrapped(**kwargs):
        if g.user is None:
            return redirect(url_for("login"))
        return view(**kwargs)
    return wrapped


def lmsr_cost(q_yes, q_no, liquidity):
    high = max(q_yes, q_no) / liquidity
    return liquidity * (high + math.log(math.exp(q_yes / liquidity - high) + math.exp(q_no / liquidity - high)))


def market_probability(market):
    ey = math.exp(market["q_yes"] / market["liquidity"])
    en = math.exp(market["q_no"] / market["liquidity"])
    return ey / (ey + en)


def quote_trade(market, side, shares):
    before = lmsr_cost(market["q_yes"], market["q_no"], market["liquidity"])
    y = market["q_yes"] + (shares if side == "YES" else 0)
    n = market["q_no"] + (shares if side == "NO" else 0)
    return (lmsr_cost(y, n, market["liquidity"]) - before) * 100


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        if not 2 <= len(username) <= 24 or not username.replace("_", "").isalnum():
            flash("Use 2–24 letters, numbers, or underscores.", "error")
            return render_template("login.html")
        connection = db()
        connection.execute("INSERT OR IGNORE INTO users(username) VALUES(?)", (username,))
        connection.commit()
        user = connection.execute("SELECT * FROM users WHERE username=? COLLATE NOCASE", (username,)).fetchone()
        session.clear()
        session["user_id"] = user["id"]
        return redirect(url_for("index"))
    return render_template("login.html")


@app.post("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/")
@login_required
def index():
    markets = db().execute("SELECT * FROM markets ORDER BY status, closes_at").fetchall()
    cards = []
    for market in markets:
        forecast = db().execute("SELECT * FROM forecasts WHERE user_id=? AND market_id=?", (g.user["id"], market["id"])).fetchone()
        cards.append({"market": market, "forecast": forecast, "probability": market_probability(market) if forecast else None})
    return render_template("index.html", cards=cards)


@app.route("/market/<int:market_id>")
@login_required
def market(market_id):
    market_row = db().execute("SELECT * FROM markets WHERE id=?", (market_id,)).fetchone()
    if not market_row:
        abort(404)
    forecast = db().execute("SELECT * FROM forecasts WHERE user_id=? AND market_id=?", (g.user["id"], market_id)).fetchone()
    trades = db().execute("SELECT * FROM trades WHERE user_id=? AND market_id=? ORDER BY created_at DESC", (g.user["id"], market_id)).fetchall()
    position = db().execute("SELECT side, COALESCE(SUM(shares),0) shares, COALESCE(SUM(cost),0) cost FROM trades WHERE user_id=? AND market_id=? GROUP BY side", (g.user["id"], market_id)).fetchall()
    probability = market_probability(market_row) if forecast else None
    crowd_forecasts = None
    if forecast:
        crowd_forecasts = db().execute("SELECT AVG(probability) avg_probability, COUNT(*) count FROM forecasts WHERE market_id=?", (market_id,)).fetchone()
    return render_template("market.html", market=market_row, forecast=forecast, trades=trades, position=position, probability=probability, crowd=crowd_forecasts)


@app.post("/market/<int:market_id>/forecast")
@login_required
def forecast(market_id):
    market_row = db().execute("SELECT * FROM markets WHERE id=? AND status='open'", (market_id,)).fetchone()
    if not market_row:
        abort(404)
    try:
        probability = float(request.form["probability"]) / 100
    except (KeyError, ValueError):
        probability = -1
    if not 0.01 <= probability <= 0.99:
        flash("Probability must be from 1% to 99%.", "error")
        return redirect(url_for("market", market_id=market_id))
    try:
        db().execute("INSERT INTO forecasts(user_id,market_id,probability,rationale) VALUES(?,?,?,?)", (g.user["id"], market_id, probability, request.form.get("rationale", "").strip()[:500]))
        db().commit()
    except sqlite3.IntegrityError:
        flash("Your initial forecast is locked. That preserves the experiment.", "error")
    return redirect(url_for("market", market_id=market_id))


@app.post("/market/<int:market_id>/trade")
@login_required
def trade(market_id):
    connection = db()
    market_row = connection.execute("SELECT * FROM markets WHERE id=? AND status='open'", (market_id,)).fetchone()
    forecast_row = connection.execute("SELECT 1 FROM forecasts WHERE user_id=? AND market_id=?", (g.user["id"], market_id)).fetchone()
    if not market_row or not forecast_row:
        abort(403)
    side = request.form.get("side")
    try:
        shares = float(request.form.get("shares", 0))
    except ValueError:
        shares = 0
    if side not in ("YES", "NO") or not 0.1 <= shares <= 100:
        flash("Choose YES or NO and buy 0.1–100 shares.", "error")
        return redirect(url_for("market", market_id=market_id))
    cost = quote_trade(market_row, side, shares)
    fresh_user = connection.execute("SELECT * FROM users WHERE id=?", (g.user["id"],)).fetchone()
    if cost > fresh_user["balance"]:
        flash("Not enough play credits.", "error")
        return redirect(url_for("market", market_id=market_id))
    column = "q_yes" if side == "YES" else "q_no"
    connection.execute(f"UPDATE markets SET {column}={column}+? WHERE id=?", (shares, market_id))
    connection.execute("UPDATE users SET balance=balance-? WHERE id=?", (cost, g.user["id"]))
    connection.execute("INSERT INTO trades(user_id,market_id,side,shares,cost) VALUES(?,?,?,?,?)", (g.user["id"], market_id, side, shares, cost))
    connection.commit()
    flash(f"Bought {shares:g} {side} shares for {cost:.1f} credits.", "success")
    return redirect(url_for("market", market_id=market_id))


@app.route("/profile")
@login_required
def profile():
    rows = db().execute("""
        SELECT m.category, f.probability, m.outcome
        FROM forecasts f JOIN markets m ON m.id=f.market_id
        WHERE f.user_id=? AND m.status='resolved'
    """, (g.user["id"],)).fetchall()
    categories = {}
    for row in rows:
        data = categories.setdefault(row["category"], {"count": 0, "brier": 0})
        data["count"] += 1
        data["brier"] += (row["probability"] - row["outcome"]) ** 2
    for data in categories.values():
        data["brier"] /= data["count"]
    trades = db().execute("""
        SELECT t.cost, t.shares, t.side, m.outcome
        FROM trades t JOIN markets m ON m.id=t.market_id
        WHERE t.user_id=? AND m.status='resolved'
    """, (g.user["id"],)).fetchall()
    pnl = sum((t["shares"] * 100 if (t["side"] == "YES") == bool(t["outcome"]) else 0) - t["cost"] for t in trades)
    overall = sum((r["probability"] - r["outcome"]) ** 2 for r in rows) / len(rows) if rows else None
    return render_template("profile.html", categories=categories, overall=overall, resolved=len(rows), pnl=pnl)


@app.route("/admin", methods=["GET", "POST"])
def admin():
    if request.method == "POST" and "key" in request.form:
        session["admin"] = request.form["key"] == os.getenv("ADMIN_KEY", "local-admin")
    markets = db().execute("SELECT * FROM markets WHERE status='open' ORDER BY closes_at").fetchall() if session.get("admin") else []
    return render_template("admin.html", markets=markets)


@app.post("/admin/resolve/<int:market_id>")
def resolve(market_id):
    if not session.get("admin"):
        abort(403)
    outcome = request.form.get("outcome")
    if outcome not in ("0", "1"):
        abort(400)
    connection = db()
    market_row = connection.execute("SELECT * FROM markets WHERE id=? AND status='open'", (market_id,)).fetchone()
    if not market_row:
        abort(404)
    winning_side = "YES" if outcome == "1" else "NO"
    payouts = connection.execute("SELECT user_id, SUM(shares)*100 payout FROM trades WHERE market_id=? AND side=? GROUP BY user_id", (market_id, winning_side)).fetchall()
    for payout in payouts:
        connection.execute("UPDATE users SET balance=balance+? WHERE id=?", (payout["payout"], payout["user_id"]))
    connection.execute("UPDATE markets SET status='resolved', outcome=? WHERE id=?", (int(outcome), market_id))
    connection.commit()
    flash("Market resolved and positions settled.", "success")
    return redirect(url_for("admin"))


@app.context_processor
def helpers():
    return {"pct": lambda value: f"{value * 100:.0f}%" if value is not None else "Locked"}


if __name__ == "__main__":
    app.run(debug=True)

