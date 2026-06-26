from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from flask_login import (
    LoginManager, UserMixin, login_user, logout_user,
    login_required, current_user
)
from werkzeug.security import check_password_hash, generate_password_hash
from database import get_db, init_db
from datetime import date, datetime
import os

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-only-secret-key-change-in-production")

init_db()

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "login"
login_manager.login_message = "ログインが必要です。"
login_manager.login_message_category = "info"


class User(UserMixin):
    def __init__(self, row):
        self.id = row["id"]
        self.username = row["username"]
        self.role = row["role"]

    def is_admin(self):
        return self.role == "admin"


@login_manager.user_loader
def load_user(user_id):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE id = %s", (user_id,))
    row = cur.fetchone()
    cur.close()
    conn.close()
    return User(row) if row else None


@app.context_processor
def inject_globals():
    return {"today": date.today().isoformat()}


# ────────────────────────────────────────
# 認証
# ────────────────────────────────────────

@app.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("report_list"))
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT * FROM users WHERE username = %s", (username,))
        row = cur.fetchone()
        cur.close()
        conn.close()
        if row and check_password_hash(row["password_hash"], password):
            login_user(User(row))
            return redirect(request.args.get("next") or url_for("report_list"))
        flash("ユーザー名またはパスワードが正しくありません。", "danger")
    return render_template("login.html")


@app.route("/logout")
@login_required
def logout():
    logout_user()
    flash("ログアウトしました。", "info")
    return redirect(url_for("login"))


# ────────────────────────────────────────
# 日報一覧
# ────────────────────────────────────────

@app.route("/")
@login_required
def report_list():
    status_filter = request.args.get("status", "")
    date_from = request.args.get("date_from", "")
    date_to = request.args.get("date_to", "")

    conn = get_db()
    cur = conn.cursor()

    query = "SELECT * FROM molding_reports WHERE 1=1"
    params = []

    if status_filter:
        query += " AND status = %s"
        params.append(status_filter)
    if date_from:
        query += " AND report_date >= %s"
        params.append(date_from)
    if date_to:
        query += " AND report_date <= %s"
        params.append(date_to)

    query += " ORDER BY report_date DESC, id DESC"
    cur.execute(query, params)
    reports = cur.fetchall()
    cur.close()
    conn.close()

    return render_template("report_list.html",
                           reports=reports,
                           status_filter=status_filter,
                           date_from=date_from,
                           date_to=date_to)


# ────────────────────────────────────────
# 日報 新規作成
# ────────────────────────────────────────

@app.route("/reports/new", methods=["GET", "POST"])
@login_required
def report_new():
    conn = get_db()
    cur = conn.cursor()

    if request.method == "POST":
        f = request.form
        try:
            cur.execute("""
                INSERT INTO molding_reports (
                    report_date, page_no, operator_name, machine_no,
                    product_name, mold_no, cavity_count, missing_cavity,
                    material_name, material_lot, material_no,
                    injection_pressure, injection_speed, holding_pressure, holding_speed,
                    injection_time, holding_time, cooling_time, rest_time,
                    metering_mm, clamping_force, back_pressure, rotation_speed,
                    cycle_time, cushion_min, hr_output_abnormal, remarks,
                    status, created_by
                ) VALUES (
                    %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
                    %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
                    'draft',%s
                ) RETURNING id
            """, (
                f["report_date"], f.get("page_no") or 1,
                f["operator_name"], f["machine_no"],
                f["product_name"], f.get("mold_no"), f.get("cavity_count") or None,
                f.get("missing_cavity"),
                f.get("material_name"), f.get("material_lot"), f.get("material_no"),
                _num(f.get("injection_pressure")), _num(f.get("injection_speed")),
                _num(f.get("holding_pressure")), _num(f.get("holding_speed")),
                _num(f.get("injection_time")), _num(f.get("holding_time")),
                _num(f.get("cooling_time")), _num(f.get("rest_time")),
                _num(f.get("metering_mm")), _num(f.get("clamping_force")),
                _num(f.get("back_pressure")), _num(f.get("rotation_speed")),
                _num(f.get("cycle_time")), _num(f.get("cushion_min")),
                bool(f.get("hr_output_abnormal")),
                f.get("remarks"),
                current_user.username
            ))
            report_id = cur.fetchone()["id"]

            # ヒーター温度の保存
            _save_heater_temps(cur, report_id, f)

            # 生産実績の保存
            _save_production_records(cur, report_id, f)

            # 品質記録の保存
            _save_quality_records(cur, report_id, f)

            conn.commit()
            flash("日報を保存しました。", "success")
            return redirect(url_for("report_detail", report_id=report_id))

        except Exception as e:
            conn.rollback()
            flash(f"保存中にエラーが発生しました: {e}", "danger")

    cur.execute("SELECT name FROM products ORDER BY name")
    products = cur.fetchall()
    cur.execute("SELECT name FROM operators ORDER BY name")
    operators = cur.fetchall()
    cur.close()
    conn.close()
    return render_template("report_form.html",
                           report=None, heater_temps=[], production_records=[], quality_records=[],
                           products=products, operators=operators)


# ────────────────────────────────────────
# 日報 詳細表示
# ────────────────────────────────────────

@app.route("/reports/<int:report_id>")
@login_required
def report_detail(report_id):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM molding_reports WHERE id = %s", (report_id,))
    report = cur.fetchone()
    if not report:
        flash("日報が見つかりません。", "danger")
        return redirect(url_for("report_list"))

    cur.execute("SELECT * FROM heater_temps WHERE report_id = %s ORDER BY id", (report_id,))
    heater_temps = cur.fetchall()

    cur.execute("SELECT * FROM production_records WHERE report_id = %s ORDER BY sort_order", (report_id,))
    production_records = cur.fetchall()

    cur.execute("SELECT * FROM quality_records WHERE report_id = %s ORDER BY sort_order", (report_id,))
    quality_records = cur.fetchall()

    cur.execute("SELECT * FROM approval_logs WHERE report_id = %s ORDER BY created_at", (report_id,))
    approval_logs = cur.fetchall()

    cur.close()
    conn.close()
    return render_template("report_detail.html",
                           report=report,
                           heater_temps=heater_temps,
                           production_records=production_records,
                           quality_records=quality_records,
                           approval_logs=approval_logs)


# ────────────────────────────────────────
# 日報 編集
# ────────────────────────────────────────

@app.route("/reports/<int:report_id>/edit", methods=["GET", "POST"])
@login_required
def report_edit(report_id):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM molding_reports WHERE id = %s", (report_id,))
    report = cur.fetchone()
    if not report:
        flash("日報が見つかりません。", "danger")
        return redirect(url_for("report_list"))

    # 承認済みは編集不可
    if report["status"] == "approved":
        flash("承認済みの日報は編集できません。", "warning")
        return redirect(url_for("report_detail", report_id=report_id))

    if request.method == "POST":
        f = request.form
        try:
            cur.execute("""
                UPDATE molding_reports SET
                    report_date=%s, page_no=%s, operator_name=%s, machine_no=%s,
                    product_name=%s, mold_no=%s, cavity_count=%s, missing_cavity=%s,
                    material_name=%s, material_lot=%s, material_no=%s,
                    injection_pressure=%s, injection_speed=%s, holding_pressure=%s, holding_speed=%s,
                    injection_time=%s, holding_time=%s, cooling_time=%s, rest_time=%s,
                    metering_mm=%s, clamping_force=%s, back_pressure=%s, rotation_speed=%s,
                    cycle_time=%s, cushion_min=%s, hr_output_abnormal=%s, remarks=%s
                WHERE id=%s
            """, (
                f["report_date"], f.get("page_no") or 1,
                f["operator_name"], f["machine_no"],
                f["product_name"], f.get("mold_no"), f.get("cavity_count") or None,
                f.get("missing_cavity"),
                f.get("material_name"), f.get("material_lot"), f.get("material_no"),
                _num(f.get("injection_pressure")), _num(f.get("injection_speed")),
                _num(f.get("holding_pressure")), _num(f.get("holding_speed")),
                _num(f.get("injection_time")), _num(f.get("holding_time")),
                _num(f.get("cooling_time")), _num(f.get("rest_time")),
                _num(f.get("metering_mm")), _num(f.get("clamping_force")),
                _num(f.get("back_pressure")), _num(f.get("rotation_speed")),
                _num(f.get("cycle_time")), _num(f.get("cushion_min")),
                bool(f.get("hr_output_abnormal")),
                f.get("remarks"),
                report_id
            ))

            # 関連データの再保存
            cur.execute("DELETE FROM heater_temps WHERE report_id = %s", (report_id,))
            cur.execute("DELETE FROM production_records WHERE report_id = %s", (report_id,))
            cur.execute("DELETE FROM quality_records WHERE report_id = %s", (report_id,))
            _save_heater_temps(cur, report_id, f)
            _save_production_records(cur, report_id, f)
            _save_quality_records(cur, report_id, f)

            conn.commit()
            flash("日報を更新しました。", "success")
            return redirect(url_for("report_detail", report_id=report_id))

        except Exception as e:
            conn.rollback()
            flash(f"更新中にエラーが発生しました: {e}", "danger")

    cur.execute("SELECT * FROM heater_temps WHERE report_id = %s ORDER BY id", (report_id,))
    heater_temps = cur.fetchall()
    cur.execute("SELECT * FROM production_records WHERE report_id = %s ORDER BY sort_order", (report_id,))
    production_records = cur.fetchall()
    cur.execute("SELECT * FROM quality_records WHERE report_id = %s ORDER BY sort_order", (report_id,))
    quality_records = cur.fetchall()
    cur.execute("SELECT name FROM products ORDER BY name")
    products = cur.fetchall()
    cur.execute("SELECT name FROM operators ORDER BY name")
    operators = cur.fetchall()
    cur.close()
    conn.close()
    return render_template("report_form.html",
                           report=report,
                           heater_temps=heater_temps,
                           production_records=production_records,
                           quality_records=quality_records,
                           products=products, operators=operators)


# ────────────────────────────────────────
# 承認フロー
# ────────────────────────────────────────

@app.route("/reports/<int:report_id>/submit", methods=["POST"])
@login_required
def report_submit(report_id):
    """スタッフが承認申請する"""
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT status FROM molding_reports WHERE id = %s", (report_id,))
    report = cur.fetchone()
    if not report or report["status"] != "draft":
        flash("この操作はできません。", "warning")
        cur.close(); conn.close()
        return redirect(url_for("report_detail", report_id=report_id))

    cur.execute(
        "UPDATE molding_reports SET status='pending', submitted_at=%s WHERE id=%s",
        (datetime.now(), report_id)
    )
    cur.execute(
        "INSERT INTO approval_logs (report_id, action, actor) VALUES (%s, '承認申請', %s)",
        (report_id, current_user.username)
    )
    conn.commit()
    cur.close(); conn.close()
    flash("承認申請しました。", "success")
    return redirect(url_for("report_detail", report_id=report_id))


@app.route("/reports/<int:report_id>/approve", methods=["POST"])
@login_required
def report_approve(report_id):
    """管理者が承認する"""
    if not current_user.is_admin():
        flash("承認権限がありません。", "danger")
        return redirect(url_for("report_detail", report_id=report_id))

    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT status FROM molding_reports WHERE id = %s", (report_id,))
    report = cur.fetchone()
    if not report or report["status"] != "pending":
        flash("この操作はできません。", "warning")
        cur.close(); conn.close()
        return redirect(url_for("report_detail", report_id=report_id))

    comment = request.form.get("comment", "")
    cur.execute(
        "UPDATE molding_reports SET status='approved', approved_by=%s, approved_at=%s WHERE id=%s",
        (current_user.username, datetime.now(), report_id)
    )
    cur.execute(
        "INSERT INTO approval_logs (report_id, action, actor, comment) VALUES (%s, '承認', %s, %s)",
        (report_id, current_user.username, comment)
    )
    conn.commit()
    cur.close(); conn.close()
    flash("承認しました。", "success")
    return redirect(url_for("report_detail", report_id=report_id))


@app.route("/reports/<int:report_id>/reject", methods=["POST"])
@login_required
def report_reject(report_id):
    """管理者が差し戻す"""
    if not current_user.is_admin():
        flash("権限がありません。", "danger")
        return redirect(url_for("report_detail", report_id=report_id))

    conn = get_db()
    cur = conn.cursor()
    comment = request.form.get("comment", "")
    cur.execute(
        "UPDATE molding_reports SET status='draft' WHERE id=%s",
        (report_id,)
    )
    cur.execute(
        "INSERT INTO approval_logs (report_id, action, actor, comment) VALUES (%s, '差し戻し', %s, %s)",
        (report_id, current_user.username, comment)
    )
    conn.commit()
    cur.close(); conn.close()
    flash("差し戻しました。", "warning")
    return redirect(url_for("report_detail", report_id=report_id))


# ────────────────────────────────────────
# 承認待ち一覧（管理者用）
# ────────────────────────────────────────

@app.route("/pending")
@login_required
def pending_list():
    if not current_user.is_admin():
        flash("管理者のみアクセスできます。", "danger")
        return redirect(url_for("report_list"))
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM molding_reports WHERE status='pending' ORDER BY submitted_at")
    reports = cur.fetchall()
    cur.close(); conn.close()
    return render_template("pending_list.html", reports=reports)


# ────────────────────────────────────────
# マスタ管理
# ────────────────────────────────────────

@app.route("/masters")
@login_required
def masters():
    if not current_user.is_admin():
        flash("管理者のみアクセスできます。", "danger")
        return redirect(url_for("report_list"))
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM products ORDER BY name")
    products = cur.fetchall()
    cur.execute("SELECT * FROM operators ORDER BY name")
    operators = cur.fetchall()
    cur.execute("SELECT id, username, role, created_at FROM users ORDER BY id")
    users = cur.fetchall()
    cur.close(); conn.close()
    return render_template("masters.html", products=products, operators=operators, users=users)


@app.route("/masters/products/add", methods=["POST"])
@login_required
def product_add():
    f = request.form
    conn = get_db()
    cur = conn.cursor()
    cur.execute("INSERT INTO products (name, material, mold_no, cavity_count) VALUES (%s,%s,%s,%s)",
                (f["name"], f.get("material"), f.get("mold_no"), f.get("cavity_count") or None))
    conn.commit(); cur.close(); conn.close()
    flash("製品を追加しました。", "success")
    return redirect(url_for("masters"))


@app.route("/masters/products/<int:pid>/delete", methods=["POST"])
@login_required
def product_delete(pid):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("DELETE FROM products WHERE id=%s", (pid,))
    conn.commit(); cur.close(); conn.close()
    flash("製品を削除しました。", "warning")
    return redirect(url_for("masters"))


@app.route("/masters/operators/add", methods=["POST"])
@login_required
def operator_add():
    name = request.form.get("name", "").strip()
    conn = get_db()
    cur = conn.cursor()
    try:
        cur.execute("INSERT INTO operators (name) VALUES (%s)", (name,))
        conn.commit()
        flash("担当者を追加しました。", "success")
    except Exception:
        flash("その担当者名は既に登録されています。", "danger")
    cur.close(); conn.close()
    return redirect(url_for("masters"))


@app.route("/masters/operators/<int:oid>/delete", methods=["POST"])
@login_required
def operator_delete(oid):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("DELETE FROM operators WHERE id=%s", (oid,))
    conn.commit(); cur.close(); conn.close()
    flash("担当者を削除しました。", "warning")
    return redirect(url_for("masters"))


@app.route("/masters/users/add", methods=["POST"])
@login_required
def user_add():
    if not current_user.is_admin():
        flash("権限がありません。", "danger")
        return redirect(url_for("masters"))
    f = request.form
    username = f.get("username", "").strip()
    password = f.get("password", "")
    role = f.get("role", "staff")
    if not username or len(password) < 8:
        flash("ユーザー名と8文字以上のパスワードを入力してください。", "danger")
        return redirect(url_for("masters"))
    conn = get_db()
    cur = conn.cursor()
    try:
        cur.execute("INSERT INTO users (username, password_hash, role) VALUES (%s,%s,%s)",
                    (username, generate_password_hash(password), role))
        conn.commit()
        flash(f"ユーザー「{username}」を追加しました。", "success")
    except Exception:
        flash("そのユーザー名は既に使用されています。", "danger")
    cur.close(); conn.close()
    return redirect(url_for("masters"))


@app.route("/masters/users/<int:uid>/delete", methods=["POST"])
@login_required
def user_delete(uid):
    if not current_user.is_admin():
        flash("権限がありません。", "danger")
        return redirect(url_for("masters"))
    if uid == current_user.id:
        flash("自分自身は削除できません。", "danger")
        return redirect(url_for("masters"))
    conn = get_db()
    cur = conn.cursor()
    cur.execute("DELETE FROM users WHERE id=%s", (uid,))
    conn.commit(); cur.close(); conn.close()
    flash("ユーザーを削除しました。", "warning")
    return redirect(url_for("masters"))


# ────────────────────────────────────────
# ユーティリティ
# ────────────────────────────────────────

def _num(val):
    """文字列を数値に変換。空文字はNoneを返す"""
    if val is None or str(val).strip() == "":
        return None
    try:
        return float(val)
    except ValueError:
        return None


def _save_heater_temps(cur, report_id, f):
    zones = ["N1", "N2", "1", "2", "3", "4", "5", "6", "7", "8",
             "9", "10", "11", "12", "13", "14", "15", "16",
             "マニホールド", "スプル"]
    for zone in zones:
        key = f"heater_{zone}"
        val = _num(f.get(key))
        if val is not None:
            cur.execute(
                "INSERT INTO heater_temps (report_id, zone_name, temperature) VALUES (%s,%s,%s)",
                (report_id, zone, val)
            )


def _save_production_records(cur, report_id, f):
    times_from = f.getlist("prod_time_from")
    times_to = f.getlist("prod_time_to")
    shots = f.getlist("prod_shot_count")
    cycles = f.getlist("prod_cycle")
    for i, (tf, tt, sh, cy) in enumerate(zip(times_from, times_to, shots, cycles)):
        if tf or sh:
            cur.execute("""
                INSERT INTO production_records
                    (report_id, time_from, time_to, shot_count, cycle_per_shot, sort_order)
                VALUES (%s,%s,%s,%s,%s,%s)
            """, (report_id, tf or None, tt or None,
                  _num(sh), _num(cy), i))


def _save_quality_records(cur, report_id, f):
    times = f.getlist("qual_time")
    welds = f.getlist("qual_weld")
    flashs = f.getlist("qual_flash")
    shorts = f.getlist("qual_short")
    gates = f.getlist("qual_gate")
    scratches = f.getlist("qual_scratch")
    foreigns = f.getlist("qual_foreign")
    pls = f.getlist("qual_pl")
    colors = f.getlist("qual_color")
    others = f.getlist("qual_other")

    for i, t in enumerate(times):
        def g(lst): return int(lst[i]) if i < len(lst) and lst[i] else 0
        cur.execute("""
            INSERT INTO quality_records
                (report_id, record_time,
                 defect_weld, defect_flash, defect_short, defect_gate,
                 defect_scratch, defect_foreign, defect_pl, defect_color, defect_other,
                 sort_order)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        """, (report_id, t or None,
              g(welds), g(flashs), g(shorts), g(gates),
              g(scratches), g(foreigns), g(pls), g(colors), g(others),
              i))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
