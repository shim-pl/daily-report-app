import os
import psycopg2
import psycopg2.extras
from werkzeug.security import generate_password_hash

DATABASE_URL = os.environ.get("DATABASE_URL", "")


def get_db():
    conn = psycopg2.connect(DATABASE_URL, cursor_factory=psycopg2.extras.RealDictCursor)
    return conn


def init_db():
    conn = get_db()
    cur = conn.cursor()

    # ユーザーテーブル
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'staff',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # 製品マスタ
    cur.execute("""
        CREATE TABLE IF NOT EXISTS products (
            id SERIAL PRIMARY KEY,
            name TEXT NOT NULL,
            material TEXT,
            mold_no TEXT,
            cavity_count INTEGER DEFAULT 1
        )
    """)

    # 担当者マスタ
    cur.execute("""
        CREATE TABLE IF NOT EXISTS operators (
            id SERIAL PRIMARY KEY,
            name TEXT UNIQUE NOT NULL
        )
    """)

    # 成形管理日報
    cur.execute("""
        CREATE TABLE IF NOT EXISTS molding_reports (
            id SERIAL PRIMARY KEY,
            report_date DATE NOT NULL,
            page_no INTEGER DEFAULT 1,
            operator_name TEXT NOT NULL,
            machine_no TEXT NOT NULL,
            product_name TEXT NOT NULL,
            mold_no TEXT,
            cavity_count INTEGER,
            missing_cavity TEXT,
            material_name TEXT,
            material_lot TEXT,
            material_no TEXT,
            injection_pressure NUMERIC,
            injection_speed NUMERIC,
            holding_pressure NUMERIC,
            holding_speed NUMERIC,
            injection_time NUMERIC,
            holding_time NUMERIC,
            cooling_time NUMERIC,
            rest_time NUMERIC,
            metering_mm NUMERIC,
            clamping_force NUMERIC,
            back_pressure NUMERIC,
            rotation_speed NUMERIC,
            cycle_time NUMERIC,
            cushion_min NUMERIC,
            hr_output_abnormal BOOLEAN DEFAULT FALSE,
            remarks TEXT,
            status TEXT NOT NULL DEFAULT 'draft',
            approved_by TEXT,
            approved_at TIMESTAMP,
            submitted_at TIMESTAMP,
            created_by TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # ヒーター温度
    cur.execute("""
        CREATE TABLE IF NOT EXISTS heater_temps (
            id SERIAL PRIMARY KEY,
            report_id INTEGER REFERENCES molding_reports(id) ON DELETE CASCADE,
            zone_name TEXT NOT NULL,
            temperature NUMERIC
        )
    """)

    # 時間別生産実績
    cur.execute("""
        CREATE TABLE IF NOT EXISTS production_records (
            id SERIAL PRIMARY KEY,
            report_id INTEGER REFERENCES molding_reports(id) ON DELETE CASCADE,
            time_from TEXT,
            time_to TEXT,
            shot_count INTEGER,
            cycle_per_shot NUMERIC,
            sort_order INTEGER DEFAULT 0
        )
    """)

    # 品質記録
    cur.execute("""
        CREATE TABLE IF NOT EXISTS quality_records (
            id SERIAL PRIMARY KEY,
            report_id INTEGER REFERENCES molding_reports(id) ON DELETE CASCADE,
            record_time TEXT,
            defect_weld INTEGER DEFAULT 0,
            defect_flash INTEGER DEFAULT 0,
            defect_short INTEGER DEFAULT 0,
            defect_gate INTEGER DEFAULT 0,
            defect_scratch INTEGER DEFAULT 0,
            defect_foreign INTEGER DEFAULT 0,
            defect_pl INTEGER DEFAULT 0,
            defect_color INTEGER DEFAULT 0,
            defect_other INTEGER DEFAULT 0,
            sort_order INTEGER DEFAULT 0
        )
    """)

    # 承認ログ
    cur.execute("""
        CREATE TABLE IF NOT EXISTS approval_logs (
            id SERIAL PRIMARY KEY,
            report_id INTEGER NOT NULL,
            report_type TEXT NOT NULL DEFAULT 'molding',
            action TEXT NOT NULL,
            actor TEXT NOT NULL,
            comment TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # 初期管理者ユーザー
    admin_user = os.environ.get("INITIAL_ADMIN_USERNAME", "admin")
    admin_pass = os.environ.get("INITIAL_ADMIN_PASSWORD", "changeme123")
    cur.execute("SELECT id FROM users WHERE username = %s", (admin_user,))
    if not cur.fetchone():
        cur.execute(
            "INSERT INTO users (username, password_hash, role) VALUES (%s, %s, 'admin')",
            (admin_user, generate_password_hash(admin_pass))
        )

    conn.commit()
    cur.close()
    conn.close()
