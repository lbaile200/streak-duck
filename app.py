from __future__ import annotations

import secrets
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from flask import Flask, abort, redirect, render_template, request, url_for

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "streaks.db"

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


def get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


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


@app.route("/")
def index():
    return render_template("index.html")


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

    return render_template(
        "created.html",
        shared_link=shared_link,
        user1_link=user1_link,
        user2_link=user2_link,
    )


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

        if user_token == row["user1_token"]:
            user_col = "last_visit_user1_date"
            viewer = "A"
        elif user_token == row["user2_token"]:
            user_col = "last_visit_user2_date"
            viewer = "B"
        else:
            abort(404)

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

    return render_template(
        "secret.html",
        streak_count=row["streak_count"],
        duck_image=duck_image,
        milestone=milestone,
        viewer=viewer,
        both_checked_in=both_checked_in,
    )


if __name__ == "__main__":
    init_db()
    app.run(debug=True)
