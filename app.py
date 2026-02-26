from flask import Flask, request, jsonify, render_template,session
import mysql.connector
from datetime import datetime

app = Flask(__name__)
app.secret_key = "library_secret_key"

# ---------------- DB CONFIG ----------------


def get_db():
    return mysql.connector.connect(
        host="localhost",
        user="root",
        password="root123",          # change if needed
        database="library_db"
    )

@app.route("/")
def home(): return render_template("index.html")

@app.route("/index.html")
def index_page(): return render_template("index.html")

@app.route("/admin.html")
def admin_page(): return render_template("admin.html")

@app.route("/user.html")
def user_page(): return render_template("user.html")

# ---------------- AUTH ----------------
@app.route("/login", methods=["POST"])
def login():
    data = request.json
    u, p = data["username"], data["password"]

    # ADMIN
    if u == "admin" and p == "admin123":
        session["user"] = "admin"
        session["role"] = "admin"
        return jsonify(success=True, role="admin")

    con = get_db()
    c = con.cursor(dictionary=True)
    c.execute("SELECT * FROM users WHERE username=%s AND password=%s", (u, p))
    user = c.fetchone()

    if user:
        session["user"] = user["username"]
        session["role"] = "user"

        c.execute(
            "INSERT INTO login_activity(user_id,username) VALUES(%s,%s)",
            (user["user_id"], user["username"])
        )
        con.commit()
        con.close()
        return jsonify(success=True)

    con.close()
    return jsonify(success=False, message="Invalid credentials")

@app.route("/register", methods=["POST"])
def register():
    data = request.json
    try:
        con = get_db()
        c = con.cursor()
        c.execute(
            "INSERT INTO users(username,password) VALUES(%s,%s)",
            (data["username"], data["password"])
        )
        con.commit()
        con.close()
        return jsonify(success=True, message="Registered successfully")
    except:
        return jsonify(success=False, message="User already exists")

@app.route("/api/logout", methods=["POST"])
def logout():
    session.clear()
    return jsonify(success=True)

@app.route("/api/me")
def me():
    if "user" in session:
        return jsonify(loggedIn=True, username=session["user"], role=session["role"])
    return jsonify(loggedIn=False)

# ---------------- BOOKS ----------------
@app.route("/api/add-book", methods=["POST"])
def add_book():
    if session.get("role") != "admin":
        return jsonify(success=False)

    d = request.json
    con = get_db()
    c = con.cursor()
    c.execute(
        "INSERT INTO books(book_name,author,quantity) VALUES(%s,%s,%s)",
        (d["name"], d["author"], d["qty"])
    )
    con.commit()
    con.close()

    return jsonify(success=True, message="📘 Book added successfully")

@app.route("/api/books")
def books():
    con = get_db()
    c = con.cursor(dictionary=True)
    c.execute("SELECT book_name AS name, author, quantity AS qty FROM books")
    data = c.fetchall()
    con.close()
    return jsonify(data)

# ---------------- ISSUE REQUEST ----------------
@app.route("/api/issue-book", methods=["POST"])
def issue_book():
    if session.get("role") != "user":
        return jsonify(message="Not logged in"), 401

    book_name = request.json.get("bookName")
    if not book_name:
        return jsonify(message="Book name required"), 400

    con = get_db()
    c = con.cursor(dictionary=True,buffered=True)

    c.execute("SELECT user_id FROM users WHERE username=%s", (session["user"],))
    user = c.fetchone()
    if user is None:
        con.close()
        return jsonify(message="User not found"), 404

    c.execute("SELECT book_id, quantity FROM books WHERE book_name=%s", (book_name,))
    book = c.fetchone()
    if book is None:
        con.close()
        return jsonify(message="Book not found"), 404

    if book["quantity"] <= 0:
        con.close()
        return jsonify(message="Book out of stock"), 400

    c.execute("""
        INSERT INTO issue_requests (user_id, username, book_id, book_name, status)
        VALUES (%s, %s, %s, %s, 'Requested')
    """, (user["user_id"], session["user"], book["book_id"], book_name))

    con.commit()
    con.close()

    return jsonify(message="📥 Request sent for admin approval")


# ---------------- ADMIN APPROVAL ----------------
@app.route("/api/admin-requests")
def admin_requests():
    con = get_db()
    c = con.cursor(dictionary=True)
    c.execute("""
        SELECT request_id, user_id, username, book_name, request_date, status
        FROM issue_requests
        WHERE status='Requested'
    """)
    data = c.fetchall()
    con.close()
    return jsonify(data)

@app.route("/api/approve-issue/<int:rid>", methods=["POST"])
def approve_issue(rid):
    con = get_db()
    c = con.cursor(dictionary=True)

    c.execute("SELECT * FROM issue_requests WHERE request_id=%s", (rid,))
    r = c.fetchone()

    # Insert issued book
    c.execute("""
        INSERT INTO issued_books(request_id,user_id,username,book_id,book_name)
        VALUES(%s,%s,%s,%s,%s)
    """, (rid, r["user_id"], r["username"], r["book_id"], r["book_name"]))

    # Update request
    c.execute("UPDATE issue_requests SET status='Approved' WHERE request_id=%s", (rid,))

    # Reduce quantity
    c.execute("UPDATE books SET quantity=quantity-1 WHERE book_id=%s", (r["book_id"],))

    con.commit()
    con.close()

    return jsonify(success=True)

# ---------------- RETURN ----------------
@app.route("/api/return-book/<int:issue_id>", methods=["POST"])
def return_book(issue_id):
    if session.get("role") != "user":
        return jsonify(success=False)

    con = get_db()
    c = con.cursor(dictionary=True)

    # 1️⃣ Get issued book
    c.execute("""
        SELECT * FROM issued_books
        WHERE issue_id=%s AND return_status='Issued'
    """, (issue_id,))
    issue = c.fetchone()

    if issue is None:
        con.close()
        return jsonify(success=False, message="Invalid return")

    return_date = datetime.now()

    # 2️⃣ Insert into returned_books
    c.execute("""
        INSERT INTO returned_books
        (issue_id,user_id,book_id,issue_date,return_date)
        VALUES(%s,%s,%s,%s,%s)
    """, (
        issue_id,
        issue["user_id"],
        issue["book_id"],
        issue["issue_date"],
        return_date
    ))

    # 3️⃣ Update issue status
    c.execute("""
        UPDATE issued_books
        SET return_status='Returned'
        WHERE issue_id=%s
    """, (issue_id,))

    # 4️⃣ Increase book quantity
    c.execute("""
        UPDATE books
        SET quantity = quantity + 1
        WHERE book_id=%s
    """, (issue["book_id"],))

    con.commit()
    con.close()

    return jsonify(success=True, message="Book returned successfully")

@app.route("/api/my-returns")
def my_returns():
    if session.get("role") != "user":
        return jsonify([])

    con = get_db()
    c = con.cursor(dictionary=True)

    c.execute("""
        SELECT b.book_name,
               r.issue_date,
               r.return_date
        FROM returned_books r
        JOIN books b ON r.book_id = b.book_id
        WHERE r.user_id = (
            SELECT user_id FROM users WHERE username=%s
        )
    """, (session["user"],))

    data = c.fetchall()
    con.close()
    return jsonify(data)



# ---------------- DASHBOARD ----------------
@app.route("/api/admin-data")
def admin_data():
    con = get_db()
    c = con.cursor(dictionary=True)

    # Pending requests
    c.execute("SELECT COUNT(*) AS cnt FROM issue_requests WHERE status='Requested'")
    pending = c.fetchone()["cnt"]

    # Issued books
    c.execute("SELECT COUNT(*) AS cnt FROM issued_books WHERE return_status='Issued'")
    issued = c.fetchone()["cnt"]

    # Returned books
    c.execute("SELECT COUNT(*) AS cnt FROM returned_books")
    returned = c.fetchone()["cnt"]

    # Total users
    c.execute("SELECT COUNT(*) AS cnt FROM users")
    users = c.fetchone()["cnt"]

    # Books list
    c.execute("SELECT book_name AS name, author, quantity AS qty FROM books")
    books = c.fetchall()   # ✅ list of dicts (JSON safe)

    con.close()

    return jsonify({
        "pending": pending,
        "issued": issued,
        "returned": returned,
        "users": users,
        "books": books
    })

@app.route("/api/admin-returns")
def admin_returns():
    if session.get("role") != "admin":
        return jsonify([])

    con = get_db()
    c = con.cursor(dictionary=True)

    c.execute("""
        SELECT u.username,
               b.book_name,
               r.issue_date,
               r.return_date
        FROM returned_books r
        JOIN users u ON r.user_id = u.user_id
        JOIN books b ON r.book_id = b.book_id
        ORDER BY r.return_date DESC
    """)

    data = c.fetchall()
    con.close()
    return jsonify(data)

@app.route("/api/activity")
def activity():
    con = get_db()
    c = con.cursor(dictionary=True)

    c.execute("""
      SELECT u.user_id, u.username, ir.status, ir.request_date
      FROM issue_requests ir
      JOIN users u ON ir.user_id = u.user_id
      ORDER BY ir.request_date DESC
    """)

    data = c.fetchall()
    con.close()
    return jsonify(data)

@app.route("/api/my-issued")
def my_issued():
    if session.get("role") != "user":
        return jsonify([])

    con = get_db()
    c = con.cursor(dictionary=True)

    # First get user_id from session username
    c.execute("SELECT user_id FROM users WHERE username=%s", (session["user"],))
    user = c.fetchone()

    if not user:
        con.close()
        return jsonify([])

    # Then fetch issued books by user_id
    c.execute("""
        SELECT issue_id, book_name, issue_date
        FROM issued_books
        WHERE user_id=%s
    """, (user["user_id"],))

    data = c.fetchall()
    con.close()

    return jsonify(data)
@app.route("/api/all-returns")
def all_returns():
    conn = get_db()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("""
        SELECT * FROM returned_books
        ORDER BY return_date DESC
    """)

    data = cursor.fetchall()
    return jsonify(data)

# ---------------- RUN ----------------
if __name__ == "__main__":
    app.run(debug=True)
