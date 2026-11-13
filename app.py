from __future__ import annotations

import secrets
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from flask import Flask, abort, make_response, redirect, render_template, request, url_for

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "streaks.db"
DASHBOARD_COOKIE = "streakduck_dashboard"

app = Flask(__name__)

MILESTONES = [
    (10, "duck_10.png"),
    (25, "duck_25.png"),
    (50, "duck_50.png"),
    (100, "duck_100.png"),
    (300, "duck_300.png"),
    (500, "duck_500.png"),
    (700, "duck_700.png"),
    (1000, "duck_1000.png"),
]


def utc_today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


@contextmanager
def get_db() -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        with conn:
            yield conn
    finally:
        conn.close()


def init_db() -> None:
    with get_db() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS streaks (
                id TEXT PRIMARY KEY,
                created_at TEXT NOT NULL,
                streak_count INTEGER NOT NULL,
                last_increment_date TEXT,
                last_visit_user1_date TEXT,
                last_visit_user2_date TEXT,
                user1_token TEXT NOT NULL,
                user2_token TEXT NOT NULL
            )
            """
        )

        # Add names to existing databases without replacing streaks or links.
        columns = {column["name"] for column in conn.execute("PRAGMA table_info(streaks)")}
        for column, default in (("user1_name", "Duck A"), ("user2_name", "Duck B")):
            if column not in columns:
                conn.execute(f"ALTER TABLE streaks ADD COLUMN {column} TEXT NOT NULL DEFAULT '{default}'")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS dashboard_streaks (
                dashboard_id TEXT NOT NULL,
                streak_id TEXT NOT NULL,
                user_token TEXT NOT NULL,
                PRIMARY KEY (dashboard_id, streak_id)
            )
            """
        )

        # Dashboards outlive their streaks, so saved links also work when empty.
        conn.execute("CREATE TABLE IF NOT EXISTS dashboards (id TEXT PRIMARY KEY)")
        conn.execute(
            "INSERT OR IGNORE INTO dashboards (id) SELECT DISTINCT dashboard_id FROM dashboard_streaks"
        )


def remember_streak(secret_id: str, user_token: str, response):
    dashboard_id = request.cookies.get(DASHBOARD_COOKIE) or secrets.token_urlsafe(32)
    with get_db() as conn:
        conn.execute("INSERT OR IGNORE INTO dashboards (id) VALUES (?)", (dashboard_id,))
        conn.execute(
            """INSERT INTO dashboard_streaks (dashboard_id, streak_id, user_token)
               VALUES (?, ?, ?)
               ON CONFLICT(dashboard_id, streak_id)
               DO UPDATE SET user_token = excluded.user_token""",
            (dashboard_id, secret_id, user_token),
        )
    return set_dashboard_cookie(response, dashboard_id)


def set_dashboard_cookie(response, dashboard_id: str):
    response = make_response(response)
    response.set_cookie(
        DASHBOARD_COOKIE, dashboard_id, max_age=60 * 60 * 24 * 365,
        httponly=True, samesite="Lax", secure=request.is_secure,
    )
    return response


def buddy_number(row, user_token: str) -> int:
    if user_token == row["user1_token"]:
        return 1
    if user_token == row["user2_token"]:
        return 2
    abort(404)


def pick_duck_image(streak_count: int) -> str:
    selected = "duck_0.png"
    for threshold, filename in MILESTONES:
        if streak_count >= threshold:
            selected = filename
    return selected


def next_milestone(streak_count: int) -> int | None:
    for threshold, _ in MILESTONES:
        if streak_count < threshold:
            return threshold
    return None


init_db()


@app.after_request
def protect_private_links(response):
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Cache-Control"] = "no-store"
    return response


@app.route("/")
def index():
    dashboard_id = request.cookies.get(DASHBOARD_COOKIE)
    if dashboard_id:
        with get_db() as conn:
            exists = conn.execute(
                "SELECT 1 FROM dashboards WHERE id = ?",
                (dashboard_id,),
            ).fetchone()
        if exists:
            return redirect(url_for("dashboard", dashboard_id=dashboard_id))
    return render_template("index.html", streaks=[], today=utc_today())


@app.route("/d/<dashboard_id>")
def dashboard(dashboard_id: str):
    with get_db() as conn:
        if conn.execute("SELECT 1 FROM dashboards WHERE id = ?", (dashboard_id,)).fetchone() is None:
            abort(404)
        streaks = conn.execute(
            """SELECT s.*, d.user_token FROM dashboard_streaks d
               JOIN streaks s ON s.id = d.streak_id
               WHERE d.dashboard_id = ? ORDER BY s.created_at DESC, s.id""",
            (dashboard_id,),
        ).fetchall()
    return set_dashboard_cookie(
        render_template(
            "index.html", streaks=streaks, today=utc_today(),
            dashboard_link=url_for("dashboard", dashboard_id=dashboard_id, _external=True),
        ),
        dashboard_id,
    )


@app.post("/create")
def create():
    secret_id = secrets.token_urlsafe(16)
    user1_token = secrets.token_urlsafe(8)
    user2_token = secrets.token_urlsafe(8)

    with get_db() as conn:
        conn.execute(
            """
            INSERT INTO streaks (
                id, created_at, streak_count, user1_token, user2_token
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (
                secret_id,
                datetime.now(timezone.utc).isoformat(timespec="seconds"),
                0,
                user1_token,
                user2_token,
            ),
        )

    shared_link = url_for("choose_duck", secret_id=secret_id, _external=True)
    user1_link = url_for("secret", secret_id=secret_id, user_token=user1_token, _external=True)
    user2_link = url_for("secret", secret_id=secret_id, user_token=user2_token, _external=True)

    return remember_streak(secret_id, user1_token, render_template(
        "created.html",
        shared_link=shared_link,
        user1_link=user1_link,
        user2_link=user2_link,
    ))


@app.route("/s/<secret_id>")
def choose_duck(secret_id: str):
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM streaks WHERE id = ?",
            (secret_id,),
        ).fetchone()

    if row is None:
        abort(404)

    user1_link = url_for("secret", secret_id=secret_id, user_token=row["user1_token"])
    user2_link = url_for("secret", secret_id=secret_id, user_token=row["user2_token"])

    return render_template(
        "choose.html",
        user1_name=row["user1_name"],
        user2_name=row["user2_name"],
        user1_link=user1_link,
        user2_link=user2_link,
    )


@app.route("/s/<secret_id>/<user_token>")
def secret(secret_id: str, user_token: str):
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM streaks WHERE id = ?",
            (secret_id,),
        ).fetchone()

        if row is None:
            abort(404)

        user_number = buddy_number(row, user_token)
        user_col = f"last_visit_user{user_number}_date"

        today = utc_today()
        last_visit = row[user_col]
        if last_visit != today:
            conn.execute(
                f"UPDATE streaks SET {user_col} = ? WHERE id = ?",
                (today, secret_id),
            )

        # Re-fetch after potential update.
        row = conn.execute(
            "SELECT * FROM streaks WHERE id = ?",
            (secret_id,),
        ).fetchone()

        both_checked_in = (
            row["last_visit_user1_date"] == today
            and row["last_visit_user2_date"] == today
        )

        if both_checked_in and row["last_increment_date"] != today:
            new_streak = row["streak_count"] + 1
            conn.execute(
                """
                UPDATE streaks
                SET streak_count = ?, last_increment_date = ?
                WHERE id = ?
                """,
                (new_streak, today, secret_id),
            )
            row = conn.execute(
                "SELECT * FROM streaks WHERE id = ?",
                (secret_id,),
            ).fetchone()

    duck_image = pick_duck_image(row["streak_count"])
    milestone = next_milestone(row["streak_count"])

    return remember_streak(secret_id, user_token, render_template(
        "secret.html",
        secret_id=secret_id,
        user_token=user_token,
        buddy_name=row[f"user{user_number}_name"],
        partner_name=row[f"user{3 - user_number}_name"],
        shared_link=url_for("choose_duck", secret_id=secret_id, _external=True),
        streak_count=row["streak_count"],
        duck_image=duck_image,
        milestone=milestone,
        both_checked_in=both_checked_in,
    ))


@app.post("/s/<secret_id>/<user_token>/name")
def rename_buddy(secret_id: str, user_token: str):
    with get_db() as conn:
        row = conn.execute("SELECT * FROM streaks WHERE id = ?", (secret_id,)).fetchone()
        if row is None:
            abort(404)
        user_number = buddy_number(row, user_token)
        name = request.form.get("name", "").strip()
        if not name or len(name) > 60:
            abort(400, description="Buddy names must contain between 1 and 60 characters.")
        conn.execute(
            f"UPDATE streaks SET user{user_number}_name = ? WHERE id = ?",
            (name, secret_id),
        )
    return remember_streak(
        secret_id, user_token,
        redirect(url_for("secret", secret_id=secret_id, user_token=user_token)),
    )


@app.route("/s/<secret_id>/<user_token>/delete", methods=["GET", "POST"])
def delete_streak(secret_id: str, user_token: str):
    with get_db() as conn:
        row = conn.execute("SELECT * FROM streaks WHERE id = ?", (secret_id,)).fetchone()
        if row is None:
            abort(404)
        buddy_number(row, user_token)
        if request.method == "POST":
            if request.form.get("confirm") != "delete":
                abort(400, description="Confirm that you want to delete this streak.")
            conn.execute("DELETE FROM dashboard_streaks WHERE streak_id = ?", (secret_id,))
            conn.execute("DELETE FROM streaks WHERE id = ?", (secret_id,))
            return redirect(url_for("index"))
    return render_template("delete.html", streak=row, user_token=user_token)


if __name__ == "__main__":
    init_db()
    app.run(debug=True)
