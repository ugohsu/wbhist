import difflib
import json
import os
import re
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from flask import Flask, abort, flash, g, redirect, render_template, request, session, url_for

DB_PATH = os.environ.get("DB_PATH", "/data/sessions.db")
DATA_DB_PATH = os.environ.get("DATA_DB_PATH", "/app-data/wbhist.db")
APP_PASSWORD = os.environ.get("APP_PASSWORD")
JST = timezone(timedelta(hours=9))

DATA_SCHEMA = """
CREATE TABLE IF NOT EXISTS repo_links (
    project_path TEXT PRIMARY KEY,
    repo_url     TEXT NOT NULL,
    branch       TEXT NOT NULL
);
"""

REPO_URL_RE = re.compile(r"^https://github\.com/[\w.-]+/[\w.-]+$")
BRANCH_RE = re.compile(r"^[\w./-]+$")

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-insecure-key-for-local-testing")
app.permanent_session_lifetime = timedelta(days=30)


def safe_next_path(value, default):
    # Only allow redirecting back to a same-site path, never an
    # absolute/external URL, to avoid an open-redirect via the "next" param.
    if not value or not value.startswith("/") or value.startswith("//"):
        return default
    return value


@app.before_request
def require_login():
    if request.endpoint in ("login", "static") or session.get("authenticated"):
        return
    return redirect(url_for("login", next=request.path))


@app.route("/login", methods=["GET", "POST"])
def login():
    if session.get("authenticated") and request.method == "GET":
        return redirect(url_for("index"))

    next_path = safe_next_path(request.args.get("next", ""), url_for("index"))

    error = None
    if request.method == "POST":
        password = request.form.get("password", "")
        if APP_PASSWORD and secrets.compare_digest(password, APP_PASSWORD):
            session.permanent = True
            session["authenticated"] = True
            return redirect(next_path)
        error = "パスワードが正しくありません"
    return render_template("login.html", error=error, next=next_path)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
        g.db.row_factory = sqlite3.Row
    return g.db


def get_data_db():
    # Separate, writable DB for wbhist's own settings (e.g. repo_links).
    # sessions.db stays read-only and owned entirely by sync_to_sqlite.py.
    if "data_db" not in g:
        Path(DATA_DB_PATH).parent.mkdir(parents=True, exist_ok=True)
        g.data_db = sqlite3.connect(DATA_DB_PATH)
        g.data_db.execute(DATA_SCHEMA)
        g.data_db.row_factory = sqlite3.Row
    return g.data_db


@app.teardown_appcontext
def close_db(exception=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()
    data_db = g.pop("data_db", None)
    if data_db is not None:
        data_db.close()


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
app.jinja_env.filters["fromjson"] = json.loads


def project_url(project_path):
    # project_path is always an absolute path (leading "/"); the path
    # converter below needs the slash to come from the route's own
    # separator, not from the value, so strip it before building the URL.
    return url_for("project_sessions", project_path=project_path.lstrip("/"))


def fetch_repo_link(project_path):
    row = get_data_db().execute(
        "SELECT repo_url, branch FROM repo_links WHERE project_path = ?",
        (project_path,),
    ).fetchone()
    return {"repo_url": row["repo_url"], "branch": row["branch"]} if row else None


def save_repo_link(project_path, repo_url, branch):
    db = get_data_db()
    db.execute(
        "INSERT INTO repo_links (project_path, repo_url, branch) VALUES (?, ?, ?) "
        "ON CONFLICT(project_path) DO UPDATE SET repo_url = excluded.repo_url, branch = excluded.branch",
        (project_path, repo_url, branch),
    )
    db.commit()


def delete_repo_link(project_path):
    db = get_data_db()
    db.execute("DELETE FROM repo_links WHERE project_path = ?", (project_path,))
    db.commit()


def validate_repo_link(repo_url, branch):
    repo_url = repo_url.strip().rstrip("/")
    branch = branch.strip() or "main"
    if not REPO_URL_RE.match(repo_url):
        return None, "GitHubリポジトリのURL（https://github.com/<org>/<repo>）を入力してください"
    if not BRANCH_RE.match(branch):
        return None, "ブランチ名に使えない文字が含まれています"
    return (repo_url, branch), None


def build_github_url(repo_link, project_path, file_path):
    # file_path (Edit tool_use の絶対パス) が project_path の配下にある場合のみ、
    # リポジトリ相対パスに変換してリンクを組み立てる。配下でなければリンクしない。
    if not repo_link:
        return None
    root = project_path.rstrip("/") + "/"
    if not file_path.startswith(root):
        return None
    relative_path = file_path[len(root):]
    return f"{repo_link['repo_url']}/blob/{repo_link['branch']}/{relative_path}"


def fetch_projects():
    rows = get_db().execute(
        """
        SELECT project_path, COUNT(*) AS session_count, MAX(updated_at) AS last_updated
        FROM sessions
        GROUP BY project_path
        ORDER BY last_updated DESC
        """
    ).fetchall()
    return [
        {
            "url": project_url(row["project_path"]),
            "title": row["project_path"].rsplit("/", 1)[-1],
            "title_attr": row["project_path"],
            "extra": f"{row['session_count']} セッション",
            "time": row["last_updated"],
        }
        for row in rows
    ]


def fetch_sessions(project_path, active_session_id=None):
    rows = get_db().execute(
        """
        SELECT session_id, ai_title, updated_at
        FROM sessions
        WHERE project_path = ?
        ORDER BY updated_at DESC
        """,
        (project_path,),
    ).fetchall()
    return [
        {
            "url": url_for("session_detail", session_id=row["session_id"]),
            "title": row["ai_title"] or "(無題)",
            "time": row["updated_at"],
            "active": row["session_id"] == active_session_id,
        }
        for row in rows
    ]


@app.route("/")
def index():
    return render_template("index.html", projects=fetch_projects())


@app.route("/project/<path:project_path>")
def project_sessions(project_path):
    project_path = "/" + project_path
    sessions = fetch_sessions(project_path)
    if not sessions:
        abort(404)
    return render_template(
        "project.html",
        project_path=project_path,
        project_name=project_path.rsplit("/", 1)[-1],
        sessions=sessions,
        repo_link=fetch_repo_link(project_path),
    )


@app.route("/project/<path:project_path>/repo-link", methods=["POST"])
def repo_link_save(project_path):
    project_path = "/" + project_path
    next_path = safe_next_path(request.form.get("next", ""), project_url(project_path))
    repo_url = request.form.get("repo_url", "")
    branch = request.form.get("branch", "")
    if not repo_url.strip():
        # 空欄で保存した場合は連携解除と同じ扱いにする。
        delete_repo_link(project_path)
        return redirect(next_path)
    validated, error = validate_repo_link(repo_url, branch)
    if error:
        flash(error)
        return redirect(next_path)
    save_repo_link(project_path, *validated)
    return redirect(next_path)


@app.route("/project/<path:project_path>/repo-link/delete", methods=["POST"])
def repo_link_delete(project_path):
    project_path = "/" + project_path
    next_path = safe_next_path(request.form.get("next", ""), project_url(project_path))
    delete_repo_link(project_path)
    return redirect(next_path)


def build_diff_lines(old_text, new_text):
    # Edit の old_string/new_string が変更の正確な記録になっているので、
    # ファイル全体を知らなくてもこの2文字列だけで diff を組み立てられる
    # （ベースライン管理が不要な理由。README.md の「Phase 2」節参照）。
    diff = difflib.unified_diff(old_text.splitlines(), new_text.splitlines(), lineterm="", n=2)
    lines = []
    for line in diff:
        if line.startswith("+++") or line.startswith("---"):
            continue
        if line.startswith("@@"):
            lines.append(("hunk", line))
        elif line.startswith("+"):
            lines.append(("add", line[1:]))
        elif line.startswith("-"):
            lines.append(("del", line[1:]))
        else:
            lines.append(("ctx", line[1:]))
    return lines


def fetch_edits_by_timestamp(session_id, project_path, repo_link):
    rows = get_db().execute(
        "SELECT timestamp, file_path, old_string, new_string, replace_all "
        "FROM file_edits WHERE session_id = ? ORDER BY id ASC",
        (session_id,),
    ).fetchall()
    grouped = {}
    for row in rows:
        grouped.setdefault(row["timestamp"], []).append(
            {
                "file_path": row["file_path"],
                "replace_all": bool(row["replace_all"]),
                "lines": build_diff_lines(row["old_string"], row["new_string"]),
                "github_url": build_github_url(repo_link, project_path, row["file_path"]),
            }
        )
    return grouped


@app.route("/session/<session_id>")
def session_detail(session_id):
    session_row = get_db().execute(
        "SELECT project_path, ai_title FROM sessions WHERE session_id = ?",
        (session_id,),
    ).fetchone()
    if session_row is None:
        abort(404)
    project_path = session_row["project_path"]
    messages = get_db().execute(
        "SELECT role, timestamp, text FROM messages WHERE session_id = ? ORDER BY id ASC",
        (session_id,),
    ).fetchall()
    repo_link = fetch_repo_link(project_path)
    return render_template(
        "session.html",
        ai_title=session_row["ai_title"],
        project_path=project_path,
        project_name=project_path.rsplit("/", 1)[-1],
        sessions=fetch_sessions(project_path, active_session_id=session_id),
        messages=messages,
        edits_by_timestamp=fetch_edits_by_timestamp(session_id, project_path, repo_link),
        repo_link=repo_link,
    )


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000, debug=True)
