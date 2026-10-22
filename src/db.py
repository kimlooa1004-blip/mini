"""SQLite storage for users, profiles and saved recipes. Every query is parameterised
and every recipe query is scoped by user_id."""
import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  email         TEXT NOT NULL UNIQUE,
  password_hash TEXT NOT NULL,
  nickname      TEXT NOT NULL,
  created_at    TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS profiles (
  user_id   INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
  allergies TEXT NOT NULL DEFAULT '[]',
  dislikes  TEXT NOT NULL DEFAULT '[]',
  diet      TEXT
);
CREATE TABLE IF NOT EXISTS recipes (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id       INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  title         TEXT NOT NULL,
  servings      INTEGER,
  cook_time_min INTEGER,
  have          TEXT NOT NULL,
  missing       TEXT NOT NULL,
  steps         TEXT NOT NULL,
  created_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_recipes_user ON recipes(user_id, created_at DESC);
"""


class DuplicateEmail(Exception):
    pass


def db_path():
    return Path(os.environ.get("APP_DB_PATH") or
                Path(__file__).resolve().parent.parent / "data" / "app.db")


@contextmanager
def connect():
    """One short-lived connection per operation, so a stale handle can never break the app."""
    path = db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    try:
        with conn:
            yield conn
    finally:
        conn.close()


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def create_user(email, password_hash, nickname):
    try:
        with connect() as c:
            cur = c.execute(
                "INSERT INTO users(email, password_hash, nickname, created_at) VALUES (?,?,?,?)",
                (email, password_hash, nickname, _now()))
            c.execute("INSERT INTO profiles(user_id) VALUES (?)", (cur.lastrowid,))
            return cur.lastrowid
    except sqlite3.IntegrityError as e:
        raise DuplicateEmail(email) from e


def get_user_by_email(email):
    with connect() as c:
        row = c.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
    return dict(row) if row else None


def get_profile(user_id):
    with connect() as c:
        row = c.execute(
            "SELECT u.nickname, p.allergies, p.dislikes, p.diet FROM users u "
            "LEFT JOIN profiles p ON p.user_id = u.id WHERE u.id = ?", (user_id,)).fetchone()
    if not row:
        return None
    return {"nickname": row["nickname"], "diet": row["diet"] or "",
            "allergies": json.loads(row["allergies"] or "[]"),
            "dislikes": json.loads(row["dislikes"] or "[]")}


def update_profile(user_id, nickname, allergies, dislikes, diet):
    with connect() as c:
        c.execute("UPDATE users SET nickname = ? WHERE id = ?", (nickname, user_id))
        c.execute(
            "INSERT INTO profiles(user_id, allergies, dislikes, diet) VALUES (?,?,?,?) "
            "ON CONFLICT(user_id) DO UPDATE SET allergies=excluded.allergies, "
            "dislikes=excluded.dislikes, diet=excluded.diet",
            (user_id, json.dumps(allergies, ensure_ascii=False),
             json.dumps(dislikes, ensure_ascii=False), diet or None))


def save_recipe(user_id, recipe):
    with connect() as c:
        return c.execute(
            "INSERT INTO recipes(user_id, title, servings, cook_time_min, have, missing, "
            "steps, created_at) VALUES (?,?,?,?,?,?,?,?)",
            (user_id, recipe["title"], recipe.get("servings"), recipe.get("cook_time_min"),
             json.dumps(recipe.get("have", []), ensure_ascii=False),
             json.dumps(recipe.get("missing", []), ensure_ascii=False),
             json.dumps(recipe["steps"], ensure_ascii=False), _now())).lastrowid


def _recipe(row):
    d = dict(row)
    for key in ("have", "missing", "steps"):
        d[key] = json.loads(d[key])
    return d


def list_recipes(user_id):
    with connect() as c:
        rows = c.execute("SELECT * FROM recipes WHERE user_id = ? ORDER BY id DESC",
                         (user_id,)).fetchall()
    return [_recipe(r) for r in rows]


def get_recipe(user_id, recipe_id):
    with connect() as c:
        row = c.execute("SELECT * FROM recipes WHERE id = ? AND user_id = ?",
                        (recipe_id, user_id)).fetchone()
    return _recipe(row) if row else None


def delete_recipe(user_id, recipe_id):
    with connect() as c:
        return c.execute("DELETE FROM recipes WHERE id = ? AND user_id = ?",
                         (recipe_id, user_id)).rowcount > 0
