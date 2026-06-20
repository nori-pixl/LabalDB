import os
import json
import psycopg2
from psycopg2.extras import DictCursor
from flask import Flask, render_template, request, redirect, url_for

app = Flask(__name__)

# Renderの環境変数から自動でURLを読み込みます
DATABASE_URL = os.environ.get("DATABASE_URL")

def get_db_connection():
    """外部データベース（あなたのサーバー）に接続する関数"""
    if not DATABASE_URL:
        raise ValueError("環境変数 DATABASE_URL が設定されていません。RenderのDashboardで設定してください。")
    # psycopg v3 では、dict_rowを接続時に指定することも可能です
    return psycopg.connect(DATABASE_URL)

def init_system_db():
    """管理用テーブルと初期のJSONクエリを自動作成（起動時に1度だけ実行）"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # クエリ群をまるごと1つのJSONBとして管理
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS query_managers (
                id SERIAL PRIMARY KEY,
                list_name TEXT,
                queries JSONB
            )
        """)
        conn.commit()
        
        # 初期サンプルデータがなければ投入
        cursor.execute("SELECT COUNT(*) FROM query_managers;")
        if cursor.fetchone()[0] == 0:
            sample_queries = [
                {"id": 1, "title": "PostgreSQLのバージョンを確認", "sql": "SELECT version();"},
                {"id": 2, "title": "テスト用テーブル作成", "sql": "CREATE TABLE IF NOT EXISTS sample_users (id SERIAL PRIMARY KEY, name TEXT, role TEXT);"},
                {"id": 3, "title": "テストデータ挿入", "sql": "INSERT INTO sample_users (name, role) VALUES ('管理者', 'admin'), ('ゲスト', 'user');"},
                {"id": 4, "title": "データをすべて取得", "sql": "SELECT * FROM sample_users;"}
            ]
            cursor.execute(
                "INSERT INTO query_managers (list_name, queries) VALUES (%s, %s);",
                ("マイお気に入りSQL", json.dumps(sample_queries, ensure_ascii=False))
            )
            conn.commit()
        cursor.close()
        conn.close()
    except Exception as e:
        print(f"データベースの初期化に失敗しました（URLが未設定、または接続エラー）: {e}")

@app.route('/', methods=['GET', 'POST'])
def index():
    saved_queries = []
    error_message = ""
    
    # 接続文字列や各種パラメータの取得
    target_db = request.args.get('target_db', DATABASE_URL or '')
    sql_query = request.form.get('sql_code', '')
    edit_id = request.args.get('edit_id', '')

    # 1. 保存されたクエリ（JSONB）をデータベースから読み出す
    try:
        conn = get_db_connection()
        # row_factory=dict_row を指定することで辞書型で取得できます
        cursor = conn.cursor(row_factory=dict_row)
        cursor.execute("SELECT queries FROM query_managers WHERE id = 1;")
        row = cursor.fetchone()
        if row and row['queries']:
            # psycopg v3ではJSONBは自動でPythonのリスト/辞書にパースされます
            saved_queries = row['queries']
        cursor.close()
        conn.close()
    except Exception as e:
        error_message = f"管理用データベースへの接続エラー: {e}"

    # 2. 編集モードの判定
    edit_query = None
    if edit_id and saved_queries:
        for q in saved_queries:
            if str(q['id']) == edit_id:
                edit_query = q
                break

    # 3. SQLコードスペースでのクエリ実行処理
    result_headers = []
    result_rows = []

    if request.method == 'POST' and 'sql_code' in request.form and not error_message:
        if sql_query.strip():
            try:
                # 画面の入力欄から渡された「任意のPostgreSQL接続URL」へダイレクトに接続して実行
                target_conn = psycopg.connect(target_db)
                target_cursor = target_conn.cursor()
                
                # 生のSQLコードをそのまま実行
                target_cursor.execute(sql_query)
                
                if target_cursor.description:
                    # SELECT文などの結果がある場合、ヘッダーと行データを取得
                    result_headers = [desc.name for desc in target_cursor.description]
                    result_rows = target_cursor.fetchall()
                else:
                    # INSERT/UPDATE/DELETE文などの場合
                    target_conn.commit()
                    result_headers = ["処理結果"]
                    result_rows = [[f"成功しました（影響を受けた行数: {target_cursor.rowcount}）"]]
                target_cursor.close()
                target_conn.close()
            except Exception as e:
                error_message = str(e)

    return render_template('index.html', 
                           saved_queries=saved_queries, 
                           sql_query=sql_query, 
                           headers=result_headers, 
                           rows=result_rows, 
                           error_message=error_message,
                           target_db=target_db,
                           edit_query=edit_query)

@app.route('/save-query', methods=['POST'])
def save_query():
    """JSONBデータへの新規追加・上書き保存を処理"""
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

            if q_id:  # 【既存データの編集・上書き】
                for q in queries_list:
                    if str(q['id']) == q_id:
                        q['title'] = title
                        q['sql'] = sql
                        break
            else:  # 【新しいデータの新規追加】
                new_id = max([q['id'] for q in queries_list]) + 1 if queries_list else 1
                queries_list.append({"id": new_id, "title": title, "sql": sql})

            # psycopg v3 では、json.dumpsをしなくても自動でJSONB型として保存可能です
            cursor.execute("UPDATE query_managers SET queries = %s WHERE id = 1;", (json.dumps(queries_list, ensure_ascii=False),))
            conn.commit()
            cursor.close()
            conn.close()
        except Exception as e:
            print(f"保存エラー: {e}")
        
    return redirect(url_for('index', target_db=target_db))

@app.route('/delete-query/<int:q_id>', methods=['GET'])
def delete_query(q_id):
    """JSONBデータから特定のIDを持つクエリを削除"""
    target_db = request.args.get('target_db', DATABASE_URL or '')
    
    try:
        conn = get_db_connection()
        cursor = conn.cursor(row_factory=dict_row)
        cursor.execute("SELECT queries FROM query_managers WHERE id = 1;")
        row = cursor.fetchone()
        queries_list = row['queries'] if row and row['queries'] else []
        
        # 該当ID以外のデータを残す
        queries_list = [q for q in queries_list if q['id'] != q_id]
        
        cursor.execute("UPDATE query_managers SET queries = %s WHERE id = 1;", (json.dumps(queries_list, ensure_ascii=False),))
        conn.commit()
        cursor.close()
        conn.close()
    except Exception as e:
        print(f"削除エラー: {e}")
    
    return redirect(url_for('index', target_db=target_db))

if __name__ == '__main__':
    # 初回のみ起動時にテーブル作成を試みる
    init_system_db()
    # Render環境のポート（なければ5000番）で起動
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
