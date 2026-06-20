import os
import sqlite3
from flask import Flask, jsonify, request
from flask_cors import CORS

app = Flask(__name__)

# フロントエンド（Cloudflareやローカル画面）からの通信を丸ごと許可する設定（CORS対策）
CORS(app, resources={r"/api/*": {"origins": "*"}})

# 自動生成される本物のSQLiteデータベースファイル名
DB_FILE = os.environ.get("DATABASE_URL", "labeldb_local.db")


def init_management_db():
    """
    システム起動時に自動で実行される関数。
    ユーザーが画面で作った「最大10個のカスタムテーブル」のメタ情報を一括管理する
    『親テーブル（system_tables）』をSQLite内に構築します。
    """
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS system_tables (
            table_id TEXT PRIMARY KEY,
            table_name TEXT NOT NULL,
            network_type TEXT NOT NULL,
            flask_port INTEGER,
            external_sql_url TEXT,
            status TEXT DEFAULT 'ONLINE'
        )
    """
    )
    conn.commit()
    conn.close()


@app.route("/api/status", methods=["GET"])
def get_infra_status():
    """インフラ全体の健全性をチェックして送り返すヘルスチェックAPI"""
    return jsonify(
        {
            "status": "RUNNING",
            "database_engine": "SQLite3 (Isolated)",
            "max_slots": 10,
        }
    )
@app.route('/api/deploy', methods=['POST'])
def deploy_table():
    """
    フロントの画面で組み立てたコンポーネント（String/Number）を元に、
    SQLite内に物理的なテーブルを自動構築（DDL発行）するコアAPI
    """
    data = request.json
    table_name = data.get('table_name', 'unnamed_table')
    network_type = data.get('network_type', 'SHARED')
    flask_port = data.get('flask_port', 5000)
    external_sql_url = data.get('sql_url', None)
    columns = data.get('columns', []) # 画面から送られてきたブロック配列
    
    if not columns:
        return jsonify({"success": False, "error": "横の値（カラム）が定義されていません"}), 400

    # データベース内で重複しない一意の物理テーブルID（例: t_3f8a2d1e）を生成
    table_id = f"t_{int(os.urandom(4).hex(), 16)}"

    # 1. ユーザーが画面で定義した構造に合わせて、本物のSQL（テーブル作成文）を動的に組み立てる
    sql_fields = ["id INTEGER PRIMARY KEY AUTOINCREMENT"]
    
    for col in columns:
        col_name = col.get('name', 'unnamed_field')
        col_type = col.get('type', 'string')
        
        # SQLiteのデータ型に安全にマッピング (String -> TEXT, Number -> REAL)
        db_type = "TEXT" if col_type == "string" else "REAL"
        sql_fields.append(f"`{col_name}` {db_type}")
        
    create_table_sql = f"CREATE TABLE `{table_id}` ({', '.join(sql_fields)});"

    # 2. SQLiteデータベースに接続し、組み立てたSQLを実行してテーブルを切り出す
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        
        # 物理テーブルの作成を実行
        cursor.execute(create_table_sql)
        
        # 親の管理テーブルへ、新しく作ったテーブルのインフラ設定情報を記録
        cursor.execute("""
            INSERT INTO system_tables (table_id, table_name, network_type, flask_port, external_sql_url)
            VALUES (?, ?, ?, ?, ?)
        """, (table_id, table_name, network_type, flask_port, external_sql_url))
        
        conn.commit()
        conn.close()
        
        print(f"[DEPLOY SUCCESS] Table '{table_name}' generated as '{table_id}' Mode: {network_type}")
        return jsonify({
            "success": True, 
            "table_id": table_id, 
            "message": f"データベース内にテーブル「{table_name}」を構築完了しました。"
        })
        
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


if __name__ == '__main__':
    # 起動時に管理用データベースファイルを自動初期化
    init_management_db()
    
    # バックエンドサーバーをローカルホストの5000番ポートで起動
    print("\n--- LabelDB Backend Engine (Flask + SQLite) Active ---")
    print(f"Target Database File: {os.path.abspath(DB_FILE)}")
    app.run(host='127.0.0.1', port=5000, debug=True)
