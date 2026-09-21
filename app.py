import math
import os
import sqlite3
from functools import wraps

import click
from flask import (
    Flask,
    abort,
    flash,
    g,
    redirect,
    render_template,
    request,
    session,
    url_for,
)


app = Flask(__name__)

app.config.update(
    SECRET_KEY=os.getenv("SECRET_KEY", "dev-change-me"),
    DATABASE=os.getenv(
        "DATABASE",
        os.path.join(app.root_path, "prediction_market.db"),
    ),
)


# DATABASE

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
    table = db().execute(
        "SELECT name FROM sqlite_master "
        "WHERE type='table' AND name='users'"
    ).fetchone()

    if table is None:
        init_db()


@app.cli.command("init-db")
def init_db_command():
    init_db()
    click.echo("Initialized database.")


# USER

@app.before_request
def load_user():
    ensure_db()

    g.user = None

    if session.get("user_id"):
        g.user = db().execute(
            "SELECT * FROM users WHERE id=?",
            (session["user_id"],),
        ).fetchone()


def login_required(view):
    @wraps(view)
    def wrapped(**kwargs):
        if g.user is None:
            return redirect(url_for("login"))

        return view(**kwargs)

    return wrapped


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()

        if not 2 <= len(username) <= 24 or not username.replace("_", "").isalnum():
            flash("Use 2–24 letters, numbers, or underscores.", "error")
            return render_template("login.html")

        connection = db()

        connection.execute(
            "INSERT OR IGNORE INTO users(username) VALUES(?)",
            (username,),
        )
        connection.commit()

        user = connection.execute(
            "SELECT * FROM users WHERE username=? COLLATE NOCASE",
            (username,),
        ).fetchone()

        session.clear()
        session["user_id"] = user["id"]

        return redirect(url_for("index"))

    return render_template("login.html")


@app.post("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


# FORECASTS

@app.route("/")
@login_required
def index():
    forecasts = db().execute(
        """
        SELECT *
        FROM forecasts
        WHERE user_id=?
        ORDER BY
            CASE WHEN status='open' THEN 0 ELSE 1 END,
            created_at DESC
        """,
        (g.user["id"],),
    ).fetchall()

    return render_template(
        "index.html",
        forecasts=forecasts,
    )


@app.route("/forecast/new", methods=["GET", "POST"])
@login_required
def new_forecast():
    if request.method == "POST":
        question = request.form.get("question", "").strip()
        category = request.form.get("category", "").strip() or "General"
        notes = request.form.get("notes", "").strip()[:1000]
        resolves_at = request.form.get("resolves_at", "").strip() or None

        try:
            probability = float(request.form.get("probability", "")) / 100
        except ValueError:
            probability = -1

        if not question:
            flash("Enter a question.", "error")
            return render_template("new_forecast.html")

        if not 0.01 <= probability <= 0.99:
            flash("Enter a probability from 1% to 99%.", "error")
            return render_template("new_forecast.html")

        cursor = db().execute(
            """
            INSERT INTO forecasts
            (
                user_id,
                question,
                probability,
                notes,
                category,
                resolves_at
            )
            VALUES(?,?,?,?,?,?)
            """,
            (
                g.user["id"],
                question,
                probability,
                notes,
                category,
                resolves_at,
            ),
        )

        db().commit()

        return redirect(
            url_for(
                "forecast_page",
                forecast_id=cursor.lastrowid,
            )
        )

    return render_template("new_forecast.html")


@app.route("/forecast/<int:forecast_id>")
@login_required
def forecast_page(forecast_id):
    forecast = db().execute(
        """
        SELECT *
        FROM forecasts
        WHERE id=? AND user_id=?
        """,
        (
            forecast_id,
            g.user["id"],
        ),
    ).fetchone()

    if not forecast:
        abort(404)

    return render_template(
        "forecast.html",
        forecast=forecast,
    )


@app.post("/forecast/<int:forecast_id>/resolve")
@login_required
def resolve_forecast(forecast_id):
    outcome = request.form.get("outcome")

    if outcome not in ("0", "1"):
        abort(400)

    forecast = db().execute(
        """
        SELECT *
        FROM forecasts
        WHERE id=?
        AND user_id=?
        AND status='open'
        """,
        (
            forecast_id,
            g.user["id"],
        ),
    ).fetchone()

    if not forecast:
        abort(404)

    db().execute(
        """
        UPDATE forecasts
        SET status='resolved',
            outcome=?
        WHERE id=?
        """,
        (
            int(outcome),
            forecast_id,
        ),
    )

    db().commit()

    return redirect(
        url_for(
            "forecast_page",
            forecast_id=forecast_id,
        )
    )


# MARKETS

def lmsr_cost(q_yes, q_no, liquidity):
    high = max(q_yes, q_no) / liquidity

    return liquidity * (
        high
        + math.log(
            math.exp(q_yes / liquidity - high)
            + math.exp(q_no / liquidity - high)
        )
    )


def market_probability(market):
    difference = (
        market["q_no"] - market["q_yes"]
    ) / market["liquidity"]

    if difference >= 0:
        exp_value = math.exp(-difference)
        return exp_value / (1 + exp_value)

    exp_value = math.exp(difference)
    return 1 / (1 + exp_value)


def quote_trade(market, side, shares):
    before = lmsr_cost(
        market["q_yes"],
        market["q_no"],
        market["liquidity"],
    )

    yes = market["q_yes"]
    no = market["q_no"]

    if side == "YES":
        yes += shares
    else:
        no += shares

    after = lmsr_cost(
        yes,
        no,
        market["liquidity"],
    )

    return (after - before) * 100


@app.route("/markets")
@login_required
def markets():
    market_rows = db().execute(
        "SELECT * FROM markets ORDER BY status, closes_at"
    ).fetchall()

    cards = []

    for market_row in market_rows:
        cards.append({
            "market": market_row,
            "probability": market_probability(market_row),
        })

    return render_template(
        "markets.html",
        cards=cards,
    )


@app.route("/market/<int:market_id>")
@login_required
def market(market_id):
    market_row = db().execute(
        "SELECT * FROM markets WHERE id=?",
        (market_id,),
    ).fetchone()

    if not market_row:
        abort(404)

    positions = db().execute(
        """
        SELECT
            side,
            COALESCE(SUM(shares), 0) AS shares,
            COALESCE(SUM(cost), 0) AS cost
        FROM trades
        WHERE user_id=? AND market_id=?
        GROUP BY side
        """,
        (
            g.user["id"],
            market_id,
        ),
    ).fetchall()

    return render_template(
        "market.html",
        market=market_row,
        probability=market_probability(market_row),
        position=positions,
    )


@app.post("/market/<int:market_id>/trade")
@login_required
def trade(market_id):
    connection = db()

    market_row = connection.execute(
        """
        SELECT *
        FROM markets
        WHERE id=? AND status='open'
        """,
        (market_id,),
    ).fetchone()

    if not market_row:
        abort(404)

    side = request.form.get("side")

    try:
        shares = float(
            request.form.get("shares", 0)
        )
    except ValueError:
        shares = 0

    if side not in ("YES", "NO") or not 0.1 <= shares <= 100:
        flash(
            "Choose YES or NO and enter 0.1–100 shares.",
            "error",
        )
        return redirect(
            url_for(
                "market",
                market_id=market_id,
            )
        )

    cost = quote_trade(
        market_row,
        side,
        shares,
    )

    user = connection.execute(
        "SELECT * FROM users WHERE id=?",
        (g.user["id"],),
    ).fetchone()

    if cost > user["balance"]:
        flash(
            "Not enough play credits.",
            "error",
        )
        return redirect(
            url_for(
                "market",
                market_id=market_id,
            )
        )

    column = (
        "q_yes"
        if side == "YES"
        else "q_no"
    )

    connection.execute(
        f"""
        UPDATE markets
        SET {column}={column}+?
        WHERE id=?
        """,
        (
            shares,
            market_id,
        ),
    )

    connection.execute(
        """
        UPDATE users
        SET balance=balance-?
        WHERE id=?
        """,
        (
            cost,
            g.user["id"],
        ),
    )

    connection.execute(
        """
        INSERT INTO trades
        (
            user_id,
            market_id,
            side,
            shares,
            cost
        )
        VALUES(?,?,?,?,?)
        """,
        (
            g.user["id"],
            market_id,
            side,
            shares,
            cost,
        ),
    )

    connection.commit()

    flash(
        f"Bought {shares:g} {side} shares for {cost:.1f} credits.",
        "success",
    )

    return redirect(
        url_for(
            "market",
            market_id=market_id,
        )
    )


# RESULTS

@app.route("/profile")
@login_required
def profile():
    forecasts = db().execute(
        """
        SELECT
            category,
            probability,
            outcome
        FROM forecasts
        WHERE user_id=?
        AND status='resolved'
        """,
        (g.user["id"],),
    ).fetchall()

    categories = {}

    for row in forecasts:
        data = categories.setdefault(
            row["category"],
            {
                "count": 0,
                "brier": 0,
            },
        )

        data["count"] += 1
        data["brier"] += (
            row["probability"] - row["outcome"]
        ) ** 2

    for data in categories.values():
        data["brier"] /= data["count"]

    overall = None

    if forecasts:
        overall = sum(
            (
                row["probability"]
                - row["outcome"]
            ) ** 2
            for row in forecasts
        ) / len(forecasts)

    return render_template(
        "profile.html",
        categories=categories,
        overall=overall,
        resolved=len(forecasts),
    )


# ADMIN — MARKET MANAGEMENT

@app.route("/admin", methods=["GET", "POST"])
def admin():
    if request.method == "POST" and "key" in request.form:
        session["admin"] = (
            request.form["key"]
            == os.getenv(
                "ADMIN_KEY",
                "local-admin",
            )
        )

    market_rows = []

    if session.get("admin"):
        market_rows = db().execute(
            """
            SELECT *
            FROM markets
            WHERE status='open'
            ORDER BY closes_at
            """
        ).fetchall()

    return render_template(
        "admin.html",
        markets=market_rows,
    )


@app.post("/admin/market/new")
def create_market():
    if not session.get("admin"):
        abort(403)

    question = request.form.get("question", "").strip()
    description = request.form.get("description", "").strip()
    category = request.form.get("category", "").strip() or "General"
    closes_at = request.form.get("closes_at", "").strip()
    resolution_source = request.form.get("resolution_source", "").strip()

    if not question or not closes_at:
        flash(
            "Question and closing date are required.",
            "error",
        )
        return redirect(url_for("admin"))

    db().execute(
        """
        INSERT INTO markets
        (
            question,
            description,
            category,
            closes_at,
            resolution_source
        )
        VALUES(?,?,?,?,?)
        """,
        (
            question,
            description,
            category,
            closes_at,
            resolution_source,
        ),
    )

    db().commit()

    flash("Market created.", "success")

    return redirect(url_for("admin"))


@app.post("/admin/resolve/<int:market_id>")
def resolve_market(market_id):
    if not session.get("admin"):
        abort(403)

    outcome = request.form.get("outcome")

    if outcome not in ("0", "1"):
        abort(400)

    connection = db()

    market_row = connection.execute(
        """
        SELECT *
        FROM markets
        WHERE id=? AND status='open'
        """,
        (market_id,),
    ).fetchone()

    if not market_row:
        abort(404)

    winning_side = (
        "YES"
        if outcome == "1"
        else "NO"
    )

    payouts = connection.execute(
        """
        SELECT
            user_id,
            SUM(shares) * 100 AS payout
        FROM trades
        WHERE market_id=? AND side=?
        GROUP BY user_id
        """,
        (
            market_id,
            winning_side,
        ),
    ).fetchall()

    for payout in payouts:
        connection.execute(
            """
            UPDATE users
            SET balance=balance+?
            WHERE id=?
            """,
            (
                payout["payout"],
                payout["user_id"],
            ),
        )

    connection.execute(
        """
        UPDATE markets
        SET status='resolved',
            outcome=?
        WHERE id=?
        """,
        (
            int(outcome),
            market_id,
        ),
    )

    connection.commit()

    flash(
        "Market resolved.",
        "success",
    )

    return redirect(url_for("admin"))


# TEMPLATE HELPERS

@app.context_processor
def helpers():
    return {
        "pct": lambda value: (
            f"{value * 100:.0f}%"
            if value is not None
            else "—"
        )
    }


if __name__ == "__main__":
    app.run(debug=True)
