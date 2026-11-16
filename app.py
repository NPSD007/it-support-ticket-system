"""IT Support Ticket System.

A small Flask + SQLite application for creating, searching, filtering and
managing IT support tickets.

The SQLite file location is read from the DATABASE_PATH environment variable
(default: /data/tickets.db) so the database can live on a persistent Podman
volume mounted at /data.
"""

import os
import secrets
import signal
import sqlite3
import sys
from datetime import datetime, timezone
from urllib.parse import urlsplit

from flask import (
    Flask,
    abort,
    flash,
    g,
    redirect,
    render_template,
    request,
    url_for,
)

# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #
DATABASE_PATH = os.environ.get("DATABASE_PATH") or "/data/tickets.db"

PRIORITIES = ["Low", "Medium", "High", "Critical"]
STATUSES = ["Open", "In Progress", "Resolved", "Closed"]
CATEGORIES = [
    "Hardware",
    "Software",
    "Network",
    "Email",
    "Account & Access",
    "Printing",
    "Security",
    "Other",
]

# Status workflow: each status maps to the only status it may advance to.
# "Closed" is set separately through the /close/<id> route.
NEXT_STATUS = {"Open": "In Progress", "In Progress": "Resolved"}

# Statuses a ticket can be sent back to "Open" from (see /reopen/<id>).
REOPENABLE = ("Resolved", "Closed")

MAX_CATEGORY_LEN = 50
MAX_DESCRIPTION_LEN = 2000
MAX_KEYWORD_LEN = 100
MAX_SEARCH_TERMS = 10

app = Flask(__name__)
# The secret key only signs the session cookie that carries flash messages.
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY") or secrets.token_hex(32)
app.config["MAX_CONTENT_LENGTH"] = 64 * 1024  # reject oversized form posts


# --------------------------------------------------------------------------- #
# Database helpers
# --------------------------------------------------------------------------- #
def get_db():
    """Return the SQLite connection for the current request (opened lazily)."""
    if "db" not in g:
        g.db = sqlite3.connect(DATABASE_PATH, timeout=10)
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(exc=None):
    """Close the request's database connection, if one was opened."""
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    """Create the database directory and the tables on first run."""
    directory = os.path.dirname(os.path.abspath(DATABASE_PATH))
    os.makedirs(directory, exist_ok=True)

    conn = sqlite3.connect(DATABASE_PATH, timeout=10)
    try:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS tickets (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                category    TEXT NOT NULL,
                description TEXT NOT NULL,
                priority    TEXT NOT NULL
                            CHECK (priority IN ('Low', 'Medium', 'High', 'Critical')),
                status      TEXT NOT NULL DEFAULT 'Open'
                            CHECK (status IN ('Open', 'In Progress', 'Resolved', 'Closed')),
                created_at  TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_tickets_status   ON tickets (status);
            CREATE INDEX IF NOT EXISTS idx_tickets_priority ON tickets (priority);
            """
        )
        conn.commit()
    finally:
        conn.close()


# --------------------------------------------------------------------------- #
# Small utilities
# --------------------------------------------------------------------------- #
@app.template_filter("ticket_ref")
def ticket_ref(ticket_id):
    """Format a numeric ID as a friendly reference, e.g. 7 -> TKT-0007."""
    return f"TKT-{int(ticket_id):04d}"


def utc_now():
    """Current UTC time as 'YYYY-MM-DD HH:MM:SS'."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def escape_like(value):
    """Escape LIKE wildcards so the user's keyword is matched literally."""
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def choice_or_blank(value, allowed):
    """Return value if it is one of the allowed options, otherwise ''."""
    value = (value or "").strip()
    return value if value in allowed else ""


def redirect_back():
    """Redirect to the page an action came from (keeps search/filter state).

    Only local paths are accepted to prevent open redirects.
    """
    target = request.form.get("next", "")
    parts = urlsplit(target)
    if (
        target.startswith("/")
        and not parts.scheme
        and not parts.netloc
        and "\\" not in target
    ):
        return redirect(target)
    return redirect(url_for("index"))


def get_ticket_or_404(ticket_id):
    """Fetch a ticket's id and status, or abort with 404 if it does not exist."""
    ticket = get_db().execute(
        "SELECT id, status FROM tickets WHERE id = ?", (ticket_id,)
    ).fetchone()
    if ticket is None:
        abort(404)
    return ticket


# --------------------------------------------------------------------------- #
# Queries used by the listing page
# --------------------------------------------------------------------------- #
def fetch_tickets(keyword="", priority="", status=""):
    """Return tickets (newest first) matching the optional filters."""
    clauses, params = [], []

    # Every search word must appear in the category or in the description.
    for term in keyword.split()[:MAX_SEARCH_TERMS]:
        pattern = f"%{escape_like(term)}%"
        clauses.append(
            "(category LIKE ? ESCAPE '\\' OR description LIKE ? ESCAPE '\\')"
        )
        params.extend([pattern, pattern])

    if priority:
        clauses.append("priority = ?")
        params.append(priority)
    if status:
        clauses.append("status = ?")
        params.append(status)

    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    query = (
        "SELECT id, category, description, priority, status, created_at "
        f"FROM tickets {where} ORDER BY id DESC"
    )
    return get_db().execute(query, params).fetchall()


def status_counts():
    """Return a dict with the number of tickets per status plus a 'Total'."""
    rows = get_db().execute(
        "SELECT status, COUNT(*) AS total FROM tickets GROUP BY status"
    ).fetchall()
    counts = {status: 0 for status in STATUSES}
    counts.update({row["status"]: row["total"] for row in rows})
    counts["Total"] = sum(counts.values())
    return counts


def read_filters():
    """Read the optional q / priority / status query-string parameters."""
    keyword = request.args.get("q", "").strip()[:MAX_KEYWORD_LEN]
    priority = choice_or_blank(request.args.get("priority"), PRIORITIES)
    status = choice_or_blank(request.args.get("status"), STATUSES)
    return keyword, priority, status


def render_index(keyword="", priority="", status=""):
    """Render the ticket listing page for the given search/filter values."""
    return render_template(
        "index.html",
        tickets=fetch_tickets(keyword, priority, status),
        counts=status_counts(),
        keyword=keyword,
        selected_priority=priority,
        selected_status=status,
        priorities=PRIORITIES,
        statuses=STATUSES,
        next_status=NEXT_STATUS,
        reopenable=REOPENABLE,
    )


# --------------------------------------------------------------------------- #
# Routes
# --------------------------------------------------------------------------- #
@app.route("/")
def index():
    """List every ticket in a table (newest first)."""
    return render_index()


@app.route("/search")
def search():
    """Keyword search across category and description."""
    return render_index(*read_filters())


@app.route("/filter")
def filter_tickets():
    """Assigned variation: filter the ticket list by priority and/or status."""
    return render_index(*read_filters())


@app.route("/create", methods=["GET", "POST"])
def create():
    """Show the new-ticket form (GET) or validate and store a ticket (POST)."""
    if request.method == "POST":
        category = request.form.get("category", "").strip()
        description = (
            request.form.get("description", "").replace("\r\n", "\n").strip()
        )
        priority = request.form.get("priority", "").strip()

        errors = []
        if not category:
            errors.append("Please choose a category.")
        elif len(category) > MAX_CATEGORY_LEN:
            errors.append(f"Category must be at most {MAX_CATEGORY_LEN} characters.")
        if not description:
            errors.append("Please enter a description.")
        elif len(description) > MAX_DESCRIPTION_LEN:
            errors.append(
                f"Description must be at most {MAX_DESCRIPTION_LEN} characters."
            )
        if priority not in PRIORITIES:
            errors.append("Please choose a valid priority (Low, Medium, High or Critical).")

        if errors:
            for message in errors:
                flash(message, "error")
            return (
                render_template(
                    "create.html",
                    categories=CATEGORIES,
                    priorities=PRIORITIES,
                    form=request.form,
                ),
                400,
            )

        db = get_db()
        cursor = db.execute(
            "INSERT INTO tickets (category, description, priority, status, created_at) "
            "VALUES (?, ?, ?, 'Open', ?)",
            (category, description, priority, utc_now()),
        )
        db.commit()
        flash(f"Ticket {ticket_ref(cursor.lastrowid)} created successfully.", "success")
        return redirect(url_for("index"))

    return render_template(
        "create.html", categories=CATEGORIES, priorities=PRIORITIES, form={}
    )


@app.route("/update_status/<int:ticket_id>", methods=["POST"])
def update_status(ticket_id):
    """Advance a ticket one step: Open -> In Progress -> Resolved."""
    ticket = get_ticket_or_404(ticket_id)
    ref = ticket_ref(ticket_id)

    allowed_next = NEXT_STATUS.get(ticket["status"])
    requested = request.form.get("new_status", "").strip() or allowed_next

    if allowed_next is None:
        flash(f"{ref} is {ticket['status']} and cannot be advanced further.", "warning")
    elif requested != allowed_next:
        # The page was stale: the ticket changed after the list was loaded.
        flash(
            f"{ref} was already updated and is now {ticket['status']}. "
            "No change was made.",
            "warning",
        )
    else:
        db = get_db()
        db.execute(
            "UPDATE tickets SET status = ? WHERE id = ? AND status = ?",
            (allowed_next, ticket_id, ticket["status"]),
        )
        db.commit()
        flash(f"{ref} moved to {allowed_next}.", "success")

    return redirect_back()


@app.route("/close/<int:ticket_id>", methods=["POST"])
def close_ticket(ticket_id):
    """Set a ticket's status to Closed."""
    ticket = get_ticket_or_404(ticket_id)
    ref = ticket_ref(ticket_id)

    if ticket["status"] == "Closed":
        flash(f"{ref} is already closed.", "warning")
    else:
        db = get_db()
        db.execute("UPDATE tickets SET status = 'Closed' WHERE id = ?", (ticket_id,))
        db.commit()
        flash(f"{ref} has been closed.", "success")

    return redirect_back()


@app.route("/reopen/<int:ticket_id>", methods=["POST"])
def reopen_ticket(ticket_id):
    """Send a Resolved or Closed ticket back to Open."""
    ticket = get_ticket_or_404(ticket_id)
    ref = ticket_ref(ticket_id)

    if ticket["status"] not in REOPENABLE:
        flash(f"{ref} is {ticket['status']}, so there is nothing to reopen.", "warning")
    else:
        db = get_db()
        cursor = db.execute(
            "UPDATE tickets SET status = 'Open' WHERE id = ? AND status = ?",
            (ticket_id, ticket["status"]),
        )
        db.commit()
        if cursor.rowcount:
            flash(f"{ref} has been reopened and is now Open.", "success")
        else:
            # Someone changed the ticket between the lookup and the update.
            flash(f"{ref} was changed by someone else. No change was made.", "warning")

    return redirect_back()


# --------------------------------------------------------------------------- #
# Start-up
# --------------------------------------------------------------------------- #
# Create the tables on import so the app also works under other WSGI servers.
init_db()


def _handle_sigterm(signum, frame):
    """Exit cleanly on SIGTERM so `podman stop` returns immediately.

    Inside a container the app runs as PID 1, and Linux ignores SIGTERM for
    PID 1 unless the process installs a handler. Without this, `podman stop`
    would wait for its timeout and then kill the process.
    """
    sys.exit(0)


if __name__ == "__main__":
    signal.signal(signal.SIGTERM, _handle_sigterm)
    print(f"[ticket-system] Using database: {DATABASE_PATH}", flush=True)
    app.run(host="0.0.0.0", port=5000, debug=False)
