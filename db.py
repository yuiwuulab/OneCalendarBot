# db.py
import os
import logging
import psycopg2
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv

# 載入環境變數
load_dotenv()
USER = os.getenv("user")
PASSWORD = os.getenv("password")
HOST = os.getenv("host")
PORT = os.getenv("port")
DBNAME = os.getenv("dbname")

# 建立 DB 連線
def get_connection():
    try:
        conn = psycopg2.connect(
            user=USER,
            password=PASSWORD,
            host=HOST,
            port=PORT,
            dbname=DBNAME,
            cursor_factory=RealDictCursor
        )
        conn.autocommit = True
        return conn
    except Exception as e:
        logging.error(f"DB 連線失敗: {e}")
        raise

# 新增使用者 (第一次對話)
def add_user(chat_id: int):
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute('SELECT 1 FROM "User" WHERE chatid = %s', (chat_id,))
            if not cur.fetchone():
                cur.execute(
                    'INSERT INTO "User"(chatid, "Utoken", date, "Notice15", "Notice30") '  
                    'VALUES (%s, %s, CURRENT_DATE, TRUE, TRUE)',
                    (chat_id, "")
                )
    finally:
        conn.close()

# 設定或更新 API Token
def set_user_token(chat_id: int, token: str):
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                'UPDATE "User" SET "Utoken" = %s, date = CURRENT_DATE WHERE chatid = %s',
                (token, chat_id)
            )
    finally:
        conn.close()

# 取得 API Token
def get_user_token(chat_id: int) -> str:
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute('SELECT "Utoken" FROM "User" WHERE chatid = %s', (chat_id,))
            row = cur.fetchone()
    finally:
        conn.close()
    return row['Utoken'] if row and row.get('Utoken') else None

# 讀取所有使用者清單
def get_all_users() -> list:
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute('SELECT chatid FROM "User"')
            return cur.fetchall()
    finally:
        conn.close()

# 通用函式：讀取提醒旗標
# minutes: 15 或 30
def get_notice_flag(chat_id: int, minutes: int) -> bool:
    col = 'Notice15' if minutes == 15 else 'Notice30'
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(f'SELECT "{col}" FROM "User" WHERE chatid = %s', (chat_id,))
            row = cur.fetchone()
    finally:
        conn.close()
    return bool(row[col]) if row and row.get(col) is not None else True

# 設定提醒旗標
# minutes: 15 or 30, flag: True/False
def set_notice_flag(chat_id: int, minutes: int, flag: bool):
    col = 'Notice15' if minutes == 15 else 'Notice30'
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                f'UPDATE "User" SET "{col}" = %s WHERE chatid = %s',
                (flag, chat_id)
            )
    finally:
        conn.close()
