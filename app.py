from flask import Flask, render_template, request, jsonify, session, redirect, url_for
import sqlite3
import os
from datetime import datetime

app = Flask(__name__)
app.secret_key = 'hoyo_super_secret_key_123'

# ================= 数据库连接 =================
def get_db():
    # 连接本地的 paotui.db 文件，允许跨线程访问
    conn = sqlite3.connect('paotui.db', check_same_thread=False)
    # 让查询结果可以通过字典键名取值 (类似 pymysql 的 DictCursor)
    conn.row_factory = sqlite3.Row
    return conn

# ================= 初始化数据库 =================
def init_db():
    conn = get_db()
    cursor = conn.cursor()
    
    # 统一用一张 users 表，通过 role 字段区分身份
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            nickname TEXT,
            role TEXT DEFAULT 'user',
            company TEXT DEFAULT '',
            created_at TEXT
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            desc TEXT,
            reward REAL,
            publisher TEXT,
            taker TEXT DEFAULT '',
            status TEXT DEFAULT '待接单'
        )
    ''')

    # 自动创建默认管理员 (hoyo / xd87060+)
    try:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cursor.execute('INSERT INTO users (username, password, role, nickname, created_at) VALUES (?, ?, "admin", "超级管理员", ?)', ("hoyo", "xd87060+", now))
        conn.commit()
    except sqlite3.IntegrityError:
        pass 
    conn.close()

init_db()

# ================= 页面路由 =================

@app.route('/')
def index():
    if 'username' not in session:
        return redirect(url_for('login_page'))
    return render_template('index.html')

@app.route('/login')
def login_page():
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login_page'))

# ================= 登录与注册 API =================

@app.route('/api/register', methods=['POST'])
def register():
    data = request.json
    username = data.get('username')
    password = data.get('password')
    nickname = data.get('nickname')
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    if not all([username, password, nickname]):
        return jsonify({"error": "所有字段均不能为空"}), 400

    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute('INSERT INTO users (username, password, nickname, created_at) VALUES (?, ?, ?, ?)', (username, password, nickname, now))
        conn.commit()
        return jsonify({"message": "注册成功！请登录"})
    except sqlite3.IntegrityError:
        return jsonify({"error": "该账号已被注册"}), 400
    finally:
        conn.close()

@app.route('/api/login', methods=['POST'])
def login():
    data = request.json
    username = data.get('username')
    password = data.get('password')
    
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM users WHERE username = ? AND password = ?', (username, password))
    user = cursor.fetchone()
    conn.close()

    if user:
        session['username'] = user['username']
        session['role'] = user['role']
        return jsonify({"message": "登录成功", "role": user['role']})
    else:
        return jsonify({"error": "账号或密码错误"}), 401

@app.route('/api/current_user')
def current_user():
    if 'username' in session:
        return jsonify({"username": session['username'], "role": session.get('role')})
    return jsonify({"error": "未登录"}), 401

# ================= 管理员平台 API =================

@app.route('/api/admin/staff_list', methods=['GET'])
def staff_list():
    if session.get('role') != 'admin':
        return jsonify({"error": "无权操作"}), 403
        
    conn = get_db()
    cursor = conn.cursor()
    result = []
    
    # 查询代理和配送员
    cursor.execute('SELECT id, username, nickname, role, company, created_at FROM users WHERE role IN ("agent", "runner")')
    for u in cursor.fetchall():
        days = 0
        if u['created_at']:
            try:
                dt = datetime.strptime(u['created_at'], "%Y-%m-%d %H:%M:%S")
                days = (datetime.now() - dt).days
            except:
                pass
                
        order_count = 0
        if u['role'] == 'runner':
            cursor.execute('SELECT COUNT(*) as count FROM tasks WHERE taker = ?', (u['username'],))
            order_count = cursor.fetchone()['count']
            
        result.append({
            "id": u['id'], "username": u['username'], "nickname": u['nickname'], 
            "role": u['role'], "company": u['company'], 
            "days": days, "orderCount": order_count
        })
        
    conn.close()
    return jsonify(result)

@app.route('/api/admin/create_staff', methods=['POST'])
def create_staff():
    if session.get('role') != 'admin':
        return jsonify({"error": "无权操作"}), 403
        
    data = request.json
    username = data.get('username')
    password = data.get('password')
    role = data.get('role')
    nickname = data.get('nickname')
    company = data.get('company', '')
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    if not all([username, password, nickname]):
         return jsonify({"error": "必填项不能为空"}), 400

    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute('INSERT INTO users (username, password, nickname, role, company, created_at) VALUES (?, ?, ?, ?, ?, ?)', 
                       (username, password, nickname, role, company, now))
        conn.commit()
        return jsonify({"message": f"{nickname} 创建成功！"})
    except sqlite3.IntegrityError:
        return jsonify({"error": "该账号已被占用"}), 400
    finally:
        conn.close()

# ================= 业务 API (任务大厅) =================

@app.route('/api/add_task', methods=['POST'])
def add_task():
    if 'username' not in session: return jsonify({"error": "请先登录"}), 401
    # 拦截：配送员不能发单
    if session.get('role') == 'runner':
        return jsonify({"error": "配送员不可发布任务"}), 403
        
    data = request.json
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('INSERT INTO tasks (title, desc, reward, publisher) VALUES (?, ?, ?, ?)', 
                   (data.get('title'), data.get('desc'), data.get('reward'), session['username']))
    conn.commit()
    conn.close()
    return jsonify({"message": "发布成功！"})

@app.route('/api/get_tasks', methods=['GET'])
def get_tasks():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM tasks ORDER BY id DESC')
    rows = cursor.fetchall()
    conn.close()
    # 将 sqlite3.Row 对象转为普通字典返回给前端
    return jsonify([dict(r) for r in rows])

@app.route('/api/take_task', methods=['POST'])
def take_task():
    if 'username' not in session: return jsonify({"error": "请先登录"}), 401
    # 拦截：非配送员不能接单
    if session.get('role') != 'runner':
        return jsonify({"error": "仅认证配送员可接单"}), 403

    data = request.json
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('UPDATE tasks SET status = "已接单", taker = ? WHERE id = ? AND status = "待接单"', 
                   (session['username'], data.get('task_id')))
    conn.commit()
    conn.close()
    return jsonify({"message": "接单成功！"})

@app.route('/api/complete_task', methods=['POST'])
def complete_task():
    data = request.json
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('UPDATE tasks SET status = "已完成" WHERE id = ?', (data.get('task_id'),))
    conn.commit()
    conn.close()
    return jsonify({"message": "任务已完成！"})

@app.route('/api/delete_task', methods=['POST'])
def delete_task():
    # 拦截：仅管理员可操作
    if session.get('role') != 'admin':
        return jsonify({"error": "无权操作，仅管理员可删除订单"}), 403
        
    data = request.json
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('DELETE FROM tasks WHERE id = ?', (data.get('task_id'),))
    conn.commit()
    conn.close()
    return jsonify({"message": "订单已彻底删除！"})

# ================= 启动 =================
if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)