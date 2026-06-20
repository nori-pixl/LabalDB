import os
import json
import psycopg
from psycopg.rows import dict_row
from flask import Flask, render_template, request, redirect, url_for

app = Flask(__name__)

# Renderの環境変数からシステムDBのURLを読み込みます
DATABASE_URL = os.environ.get("DATABASE_URL")

def get_db_connection():
    if not DATABASE_URL:
        raise ValueError("環境変数 DATABASE_URL が設定されていません。")
    return psycopg.connect(DATABASE_URL)

def init_system_db():
    """管理用テーブルの初期化"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # 1. クエリ管理用テーブル
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS query_managers (
                id SERIAL PRIMARY KEY,
                list_name TEXT,
                queries JSONB
            )
        """)
        
        # 2. データベース管理用テーブル
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS database_managers (
                id SERIAL PRIMARY KEY,
                list_name TEXT,
                db_list JSONB
            )
        """)
        conn.commit()
        
        # 初期サンプルデータ投入（クエリ）
        cursor.execute("SELECT COUNT(*) FROM query_managers;")
        if cursor.fetchone()[0] == 0:
            sample_queries = [
                {"id": 1, "title": "PostgreSQLバージョン確認", "sql": "SELECT version();"},
                {"id": 2, "title": "サンプルテーブル作成", "sql": "CREATE TABLE IF NOT EXISTS items (id SERIAL PRIMARY KEY, item_name TEXT, price INT, status TEXT);"},
                {"id": 3, "title": "サンプルデータ挿入", "sql": "INSERT INTO items (item_name, price, status) VALUES ('ノートPC', 120000, 'available'), ('モニター', 35000, 'sold_out');"},
                {"id": 4, "title": "全データ取得", "sql": "SELECT * FROM items;"}
            ]
            cursor.execute("INSERT INTO query_managers (list_name, queries) VALUES (%s, %s);", ("マイお気に入りSQL", json.dumps(sample_queries, ensure_ascii=False)))
            conn.commit()

        # 初期サンプルデータ投入（データベース）
        cursor.execute("SELECT COUNT(*) FROM database_managers;")
        if cursor.fetchone()[0] == 0:
            sample_dbs = [
                {"id": 1, "title": "デフォルトシステムDB", "url": DATABASE_URL}
            ]
            cursor.execute("INSERT INTO database_managers (list_name, db_list) VALUES (%s, %s);", ("マイDB一覧", json.dumps(sample_dbs, ensure_ascii=False)))
            conn.commit()

        cursor.close()
        conn.close()
    except Exception as e:
        print(f"データベース初期化エラー: {e}")

@app.route('/', methods=['GET', 'POST'])
def index():
    saved_queries = []
    registered_dbs = []
    error_message = ""
    
    target_db = request.args.get('target_db', DATABASE_URL or '')
    sql_query = request.form.get('sql_code', '')
    edit_id = request.args.get('edit_id', '')

    try:
        conn = get_db_connection()
        cursor = conn.cursor(row_factory=dict_row)
        
        cursor.execute("SELECT queries FROM query_managers WHERE id = 1;")
        row_q = cursor.fetchone()
        if row_q and row_q['queries']:
            saved_queries = row_q['queries']
            
        cursor.execute("SELECT db_list FROM database_managers WHERE id = 1;")
        row_db = cursor.fetchone()
        if row_db and row_db['db_list']:
            registered_dbs = row_db['db_list']

        cursor.close()
        conn.close()
    except Exception as e:
        error_message = f"管理システムへの接続エラー: {e}"

    edit_query = None
    if edit_id and saved_queries:
        for q in saved_queries:
            if str(q['id']) == edit_id:
                edit_query = q
                break

    result_headers = []
    result_rows = []

    # POSTリクエストは「別ウィンドウ」から送信され、指定したターゲットDBに対して動きます
    if request.method == 'POST' and 'sql_code' in request.form:
        if sql_query.strip():
            try:
                target_conn = psycopg.connect(target_db)
                target_cursor = target_conn.cursor()
                target_cursor.execute(sql_query)
                
                if target_cursor.description:
                    result_headers = [desc.name for desc in target_cursor.description]
                    result_rows = target_cursor.fetchall()
                else:
                    target_conn.commit()
                    result_headers = ["処理結果"]
                    result_rows = [[f"成功（影響を受けた行数: {target_cursor.rowcount}）"]]
                target_cursor.close()
                target_conn.close()
            except Exception as e:
                error_message = str(e)

    return render_template('index.html', 
                           saved_queries=saved_queries, 
                           registered_dbs=registered_dbs,
                           sql_query=sql_query, 
                           headers=result_headers, 
                           rows=result_rows, 
                           error_message=error_message,
                           target_db=target_db,
                           edit_query=edit_query)

@app.route('/add-database', methods=['POST'])
def add_database():
    db_title = request.form.get('db_title', '無題のデータベース')
    db_url = request.form.get('db_url')
    save_switch = request.form.get('save_switch')  # 'on' なら保存する
    target_db = db_url  # 新しいURLをカレントにする

    # スイッチがオンの場合のみクラウドPostgreSQLに永続保存
    if save_switch == 'on' and db_url:
        try:
            conn = get_db_connection()
            cursor = conn.cursor(row_factory=dict_row)
            cursor.execute("SELECT db_list FROM database_managers WHERE id = 1;")
            row = cursor.fetchone()
            db_list = row['db_list'] if row and row['db_list'] else []

            # 🚨 データベース上限10個制限ロジック
            if len(db_list) >= 10:
                # 10個以上の場合は一番古いものを1つ削除して枠を空ける
                db_list.pop(0)

            new_id = max([d['id'] for d in db_list]) + 1 if db_list else 1
            db_list.append({"id": new_id, "title": db_title, "url": db_url})

            cursor.execute("UPDATE database_managers SET db_list = %s WHERE id = 1;", (json.dumps(db_list, ensure_ascii=False),))
            conn.commit()
            cursor.close()
            conn.close()
        except Exception as e:
            print(f"データベース保存エラー: {e}")
        
    return redirect(url_for('index', target_db=target_db))

@app.route('/delete-database/<int:db_id>', methods=['GET'])
def delete_database(db_id):
    target_db = request.args.get('target_db', DATABASE_URL or '')
    try:
        conn = get_db_connection()
        cursor = conn.cursor(row_factory=dict_row)
        cursor.execute("SELECT db_list FROM database_managers WHERE id = 1;")
        row = cursor.fetchone()
        db_list = row['db_list'] if row and row['db_list'] else []
        
        db_list = [d for d in db_list if d['id'] != db_id]
        
        cursor.execute("UPDATE database_managers SET db_list = %s WHERE id = 1;", (json.dumps(db_list, ensure_ascii=False),))
        conn.commit()
        cursor.close()
        conn.close()
    except Exception as e:
        print(f"データベース削除エラー: {e}")
    return redirect(url_for('index', target_db=target_db))

@app.route('/save-query', methods=['POST'])
def save_query():
    title = request.form.get('title')
    sql = request.form.get('sql_code')
    q_id = request.form.get('query_id')
    target_db = request.form.get('target_db', DATABASE_URL or '')

    if title and sql:
        try:
            conn = get_db_connection()
            cursor = conn.cursor(row_factory=dict_row)
            cursor.execute("SELECT queries FROM query_managers WHERE id = 1;")
            row = cursor.fetchone()
            queries_list = row['queries'] if row and row['queries'] else []

            if q_id:
                for q in queries_list:
                    if str(q['id']) == q_id:
                        q['title'] = title
                        q['sql'] = sql
                        break
            else:
                new_id = max([q['id'] for q in queries_list]) + 1 if queries_list else 1
                queries_list.append({"id": new_id, "title": title, "sql": sql})

            cursor.execute("UPDATE query_managers SET queries = %s WHERE id = 1;", (json.dumps(queries_list, ensure_ascii=False),))
            conn.commit()
            cursor.close()
            conn.close()
        except Exception as e:
            print(f"保存エラー: {e}")
    return redirect(url_for('index', target_db=target_db))

@app.route('/delete-query/<int:q_id>', methods=['GET'])
def delete_query(q_id):
    target_db = request.args.get('target_db', DATABASE_URL or '')
    try:
        conn = get_db_connection()
        cursor = conn.cursor(row_factory=dict_row)
        cursor.execute("SELECT queries FROM query_managers WHERE id = 1;")
        row = cursor.fetchone()
        queries_list = row['queries'] if row and row['queries'] else []
        queries_list = [q for q in queries_list if q['id'] != q_id]
        cursor.execute("UPDATE query_managers SET queries = %s WHERE id = 1;", (json.dumps(queries_list, ensure_ascii=False),))
        conn.commit()
        cursor.close()
        conn.close()
    except Exception as e:
        print(f"削除エラー: {e}")
    return redirect(url_for('index', target_db=target_db))

if __name__ == '__main__':
    init_system_db()
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
