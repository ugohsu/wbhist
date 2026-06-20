import os
import sqlite3
from datetime import datetime, timedelta, timezone

from flask import Flask, abort, g, render_template, url_for

DB_PATH = os.environ.get("DB_PATH", "/data/sessions.db")
JST = timezone(timedelta(hours=9))

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-insecure-key-for-local-testing")


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(exception=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def to_jst(value):
    if not value:
        return "-"
    for fmt in ("%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ"):
        try:
            dt = datetime.strptime(value, fmt).replace(tzinfo=timezone.utc)
            break
        except ValueError:
            continue
    else:
        return value
    return dt.astimezone(JST).strftime("%Y-%m-%d %H:%M")


app.jinja_env.filters["jst"] = to_jst


@app.route("/")
def index():
    rows = get_db().execute(
        """
        SELECT project_path, COUNT(*) AS session_count, MAX(updated_at) AS last_updated
        FROM sessions
        GROUP BY project_path
        ORDER BY last_updated DESC
        """
    ).fetchall()
    items = [
        {
            "url": project_url(row["project_path"]),
            "title": row["project_path"].rsplit("/", 1)[-1],
            "subtitle": f"{row['project_path']}（{row['session_count']} セッション）",
            "time": row["last_updated"],
        }
        for row in rows
    ]
    return render_template("index.html", heading="プロジェクト一覧", breadcrumb=None, items=items)


def project_url(project_path):
    # project_path is always an absolute path (leading "/"); the path
    # converter below needs the slash to come from the route's own
    # separator, not from the value, so strip it before building the URL.
    return url_for("project_sessions", project_path=project_path.lstrip("/"))


@app.route("/project/<path:project_path>")
def project_sessions(project_path):
    project_path = "/" + project_path
    rows = get_db().execute(
        """
        SELECT session_id, ai_title, started_at, updated_at
        FROM sessions
        WHERE project_path = ?
        ORDER BY updated_at DESC
        """,
        (project_path,),
    ).fetchall()
    if not rows:
        abort(404)
    items = [
        {
            "url": url_for("session_detail", session_id=row["session_id"]),
            "title": row["ai_title"] or "(無題)",
            "subtitle": None,
            "time": row["updated_at"],
        }
        for row in rows
    ]
    return render_template("index.html", heading=project_path, breadcrumb=project_path, items=items)


@app.route("/session/<session_id>")
def session_detail(session_id):
    session_row = get_db().execute(
        "SELECT project_path, ai_title FROM sessions WHERE session_id = ?",
        (session_id,),
    ).fetchone()
    if session_row is None:
        abort(404)
    messages = get_db().execute(
        "SELECT role, timestamp, text FROM messages WHERE session_id = ? ORDER BY id ASC",
        (session_id,),
    ).fetchall()
    return render_template(
        "session.html",
        ai_title=session_row["ai_title"],
        project_path=session_row["project_path"],
        back_url=project_url(session_row["project_path"]),
        messages=messages,
    )


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000, debug=True)
