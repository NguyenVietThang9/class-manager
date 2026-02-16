from flask import Flask, render_template, request, redirect, jsonify
import sqlite3
from openpyxl import Workbook

app = Flask(__name__)
DB = "database.db"

# ================= DB =================
def get_db():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    db = get_db()
    db.executescript("""
    -- ===== MASTER =====
    CREATE TABLE IF NOT EXISTS group_master (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE
    );

    CREATE TABLE IF NOT EXISTS student_master (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE
    );

    -- ===== THEO THÁNG =====
    CREATE TABLE IF NOT EXISTS groups (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        month INTEGER,
        group_master_id INTEGER
    );

    CREATE TABLE IF NOT EXISTS students (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        student_master_id INTEGER,
        fee INTEGER,
        month INTEGER,
        group_id INTEGER
    );

    CREATE TABLE IF NOT EXISTS lessons (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        month INTEGER,
        group_id INTEGER,
        lesson_date TEXT
    );

    CREATE TABLE IF NOT EXISTS attendance (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        student_id INTEGER,
        lesson_id INTEGER,
        present INTEGER
    );

    -- ===== SCORE =====
    CREATE TABLE IF NOT EXISTS score_titles (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        month INTEGER,
        group_id INTEGER,
        title TEXT
    );

    CREATE TABLE IF NOT EXISTS scores (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        student_id INTEGER,
        title_id INTEGER,
        score REAL
    );
    """)
    db.commit()


# ================= INDEX =================
@app.route("/")
def index():
    return render_template("index.html")


# ================= GROUP =================
@app.route("/groups/<int:month>")
def groups(month):
    db = get_db()
    groups = db.execute("""
        SELECT g.id, gm.name
        FROM groups g
        JOIN group_master gm ON gm.id = g.group_master_id
        WHERE g.month=?
    """, (month,)).fetchall()

    return render_template("group.html", month=month, groups=groups)


@app.route("/add_group", methods=["POST"])
def add_group():
    db = get_db()
    name = request.form["name"]
    month = request.form["month"]

    gm = db.execute(
        "SELECT id FROM group_master WHERE name=?", (name,)
    ).fetchone()

    if not gm:
        db.execute("INSERT INTO group_master (name) VALUES (?)", (name,))
        db.commit()
        gm = db.execute(
            "SELECT id FROM group_master WHERE name=?", (name,)
        ).fetchone()

    db.execute(
        "INSERT INTO groups (month, group_master_id) VALUES (?,?)",
        (month, gm["id"])
    )
    db.commit()
    return redirect(f"/groups/{month}")


@app.route("/delete_group/<int:group_id>/<int:month>")
def delete_group(group_id, month):
    db = get_db()
    db.execute("DELETE FROM groups WHERE id=?", (group_id,))
    db.execute("DELETE FROM students WHERE group_id=?", (group_id,))
    db.execute("DELETE FROM lessons WHERE group_id=?", (group_id,))
    db.execute("DELETE FROM score_titles WHERE group_id=?", (group_id,))
    db.commit()
    return redirect(f"/groups/{month}")


# ================= COPY DATA =================
@app.route("/copy_month/<int:month>")
def copy_month(month):
    if month == 1:
        return redirect("/groups/1")

    db = get_db()
    prev_month = month - 1

    prev_groups = db.execute("""
        SELECT g.*, gm.name
        FROM groups g
        JOIN group_master gm ON gm.id = g.group_master_id
        WHERE g.month=?
    """, (prev_month,)).fetchall()

    for pg in prev_groups:

        # Nếu nhóm đã tồn tại trong tháng mới → bỏ qua
        existing_group = db.execute("""
            SELECT g.id
            FROM groups g
            WHERE g.month=? AND g.group_master_id=?
        """, (month, pg["group_master_id"])).fetchone()

        if existing_group:
            continue

        db.execute("""
            INSERT INTO groups (month, group_master_id)
            VALUES (?,?)
        """, (month, pg["group_master_id"]))
        db.commit()

        new_group_id = db.execute(
            "SELECT last_insert_rowid()"
        ).fetchone()[0]

        # ===== copy học sinh =====
        prev_students = db.execute("""
            SELECT * FROM students
            WHERE month=? AND group_id=?
        """, (prev_month, pg["id"])).fetchall()

        for ps in prev_students:

            # Nếu học sinh đã tồn tại → bỏ qua
            exist_student = db.execute("""
                SELECT id FROM students
                WHERE month=? AND group_id=? AND student_master_id=?
            """, (
                month,
                new_group_id,
                ps["student_master_id"]
            )).fetchone()

            if exist_student:
                continue

            db.execute("""
                INSERT INTO students (student_master_id, fee, month, group_id)
                VALUES (?,?,?,?)
            """, (
                ps["student_master_id"],
                ps["fee"],
                month,
                new_group_id
            ))

    db.commit()
    return redirect(f"/groups/{month}")


# ================= MONTH VIEW =================
@app.route("/month/<int:month>/<int:group_id>")
def month_view(month, group_id):
    db = get_db()

    group = db.execute("""
        SELECT g.id, gm.name
        FROM groups g
        JOIN group_master gm ON gm.id = g.group_master_id
        WHERE g.id=? AND g.month=?
    """, (group_id, month)).fetchone()

    if not group:
        return redirect(f"/groups/{month}")

    groups = db.execute("""
        SELECT g.id, gm.name
        FROM groups g
        JOIN group_master gm ON gm.id = g.group_master_id
        WHERE g.month=?
    """, (month,)).fetchall()

    students = db.execute("""
        SELECT s.*, sm.name
        FROM students s
        JOIN student_master sm ON sm.id = s.student_master_id
        WHERE s.month=? AND s.group_id=?
    """, (month, group_id)).fetchall()

    lessons = db.execute("""
        SELECT * FROM lessons
        WHERE month=? AND group_id=?
        ORDER BY lesson_date
    """, (month, group_id)).fetchall()

    titles = db.execute("""
        SELECT * FROM score_titles
        WHERE month=? AND group_id=?
    """, (month, group_id)).fetchall()

    rows = []
    for s in students:
        attendance = []
        total = 0

        for l in lessons:
            a = db.execute(
                "SELECT present FROM attendance WHERE student_id=? AND lesson_id=?",
                (s["id"], l["id"])
            ).fetchone()
            v = a["present"] if a else 0
            attendance.append(v)
            total += v

        scores = {}
        for t in titles:
            sc = db.execute(
                "SELECT score FROM scores WHERE student_id=? AND title_id=?",
                (s["id"], t["id"])
            ).fetchone()
            scores[t["id"]] = sc["score"] if sc else ""

        rows.append({
            "student": s,
            "attendance": attendance,
            "total": total,
            "money": total * s["fee"],
            "scores": scores
        })

    return render_template(
        "month.html",
        month=month,
        group_id=group_id,
        group=group,
        groups=groups,
        lessons=lessons,
        rows=rows,
        titles=titles
    )


# ================= STUDENT =================
@app.route("/add_student", methods=["POST"])
def add_student():
    db = get_db()
    name = request.form["name"]

    sm = db.execute(
        "SELECT id FROM student_master WHERE name=?", (name,)
    ).fetchone()

    if not sm:
        db.execute("INSERT INTO student_master (name) VALUES (?)", (name,))
        db.commit()
        sm = db.execute(
            "SELECT id FROM student_master WHERE name=?", (name,)
        ).fetchone()

    db.execute("""
        INSERT INTO students (student_master_id, fee, month, group_id)
        VALUES (?,?,?,?)
    """, (
        sm["id"],
        request.form["fee"],
        request.form["month"],
        request.form["group_id"]
    ))
    db.commit()

    return redirect(f"/month/{request.form['month']}/{request.form['group_id']}")


@app.route("/delete_student_select/<int:month>/<int:group_id>")
def delete_student_select(month, group_id):
    sid = request.args.get("student_id")
    if sid:
        db = get_db()
        db.execute("DELETE FROM attendance WHERE student_id=?", (sid,))
        db.execute("DELETE FROM scores WHERE student_id=?", (sid,))
        db.execute("DELETE FROM students WHERE id=?", (sid,))
        db.commit()
    return redirect(f"/month/{month}/{group_id}")


# ================= LESSON =================
@app.route("/add_lesson", methods=["POST"])
def add_lesson():
    db = get_db()
    db.execute("""
        INSERT INTO lessons (month, group_id, lesson_date)
        VALUES (?,?,?)
    """, (
        request.form["month"],
        request.form["group_id"],
        request.form["lesson_date"]
    ))
    db.commit()
    return redirect(f"/month/{request.form['month']}/{request.form['group_id']}")


@app.route("/delete_lesson_select/<int:month>/<int:group_id>")
def delete_lesson_select(month, group_id):
    lid = request.args.get("lesson_id")
    if lid:
        db = get_db()
        db.execute("DELETE FROM attendance WHERE lesson_id=?", (lid,))
        db.execute("DELETE FROM lessons WHERE id=?", (lid,))
        db.commit()
    return redirect(f"/month/{month}/{group_id}")


# ================= ATTENDANCE =================
@app.route("/toggle", methods=["POST"])
def toggle():
    db = get_db()
    sid = request.json["student_id"]
    lid = request.json["lesson_id"]

    a = db.execute(
        "SELECT * FROM attendance WHERE student_id=? AND lesson_id=?",
        (sid, lid)
    ).fetchone()

    if a:
        db.execute(
            "UPDATE attendance SET present=? WHERE id=?",
            (0 if a["present"] else 1, a["id"])
        )
    else:
        db.execute(
            "INSERT INTO attendance (student_id, lesson_id, present) VALUES (?,?,1)",
            (sid, lid)
        )
    db.commit()
    return jsonify(ok=True)


# ================= SCORE =================
@app.route("/add_score_title", methods=["POST"])
def add_score_title():
    db = get_db()
    db.execute("""
        INSERT INTO score_titles (month, group_id, title)
        VALUES (?,?,?)
    """, (
        request.json["month"],
        request.json["group_id"],
        request.json["title"]
    ))
    db.commit()
    return jsonify(ok=True)


@app.route("/save_score", methods=["POST"])
def save_score():
    db = get_db()
    sid = request.json["student_id"]
    tid = request.json["title_id"]
    score = request.json["score"]

    s = db.execute(
        "SELECT id FROM scores WHERE student_id=? AND title_id=?",
        (sid, tid)
    ).fetchone()

    if s:
        db.execute(
            "UPDATE scores SET score=? WHERE id=?",
            (score, s["id"])
        )
    else:
        db.execute(
            "INSERT INTO scores (student_id, title_id, score) VALUES (?,?,?)",
            (sid, tid, score)
        )
    db.commit()
    return jsonify(ok=True)


# ================= RUN =================
if __name__ == "__main__":
    init_db()
    app.run(debug=True)
