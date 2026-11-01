from flask import Flask, render_template, request, jsonify, session, redirect, url_for
import sqlite3
import os
from datetime import datetime
import uuid

app = Flask(__name__)
app.secret_key = 'hoyo_super_secret_key_123'

# 配置图片上传路径
app.config['UPLOAD_FOLDER'] = os.path.join(app.root_path, 'static', 'uploads')
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024 # 限制最大 16MB

def get_db():
    # 使用 row_factory 让查询结果可以通过列名访问
    conn = sqlite3.connect('paotui.db')
    conn.row_factory = sqlite3.Row
    return conn

# ================= 初始化数据库 =================
def init_db():
    conn = get_db()
    cursor = conn.cursor()
    
    # 1. 普通用户表
    cursor.execute('''CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE NOT NULL, password TEXT NOT NULL, nickname TEXT, role TEXT DEFAULT 'user', created_at TEXT)''')
    
    # 2. 代理表
    cursor.execute('''CREATE TABLE IF NOT EXISTS agents (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE NOT NULL, password TEXT NOT NULL, nickname TEXT, company TEXT, created_at TEXT)''')
    
    # 3. 配送员表
    cursor.execute('''CREATE TABLE IF NOT EXISTS runners (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE NOT NULL, password TEXT NOT NULL, nickname TEXT, created_at TEXT)''')
    
    # 4. 任务表
    cursor.execute('''CREATE TABLE IF NOT EXISTS tasks (id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL, desc TEXT, reward REAL, publisher TEXT, taker TEXT DEFAULT '', status TEXT DEFAULT '待接单')''')

    # 给任务表动态添加 delivery_image 字段（如果不存在的话）
    try:
        cursor.execute('ALTER TABLE tasks ADD COLUMN delivery_image TEXT DEFAULT ""')
        conn.commit()
    except sqlite3.OperationalError:
        pass # 字段已存在，忽略

    # 自动创建默认管理员
    try:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cursor.execute('INSERT INTO users (username, password, role, nickname, created_at) VALUES ("hoyo", "xd87060+", "admin", "超级管理员", ?)', (now,))
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
def check_user_exists(cursor, username):
    cursor.execute('SELECT id FROM users WHERE username = ?', (username,))
    if cursor.fetchone(): return True
    cursor.execute('SELECT id FROM agents WHERE username = ?', (username,))
    if cursor.fetchone(): return True
    cursor.execute('SELECT id FROM runners WHERE username = ?', (username,))
    if cursor.fetchone(): return True
    return False

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
        if check_user_exists(cursor, username):
            return jsonify({"error": "该账号已被注册"}), 400
            
        cursor.execute('INSERT INTO users (username, password, nickname, created_at) VALUES (?, ?, ?, ?)', (username, password, nickname, now))
        conn.commit()
        return jsonify({"message": "注册成功！请登录"})
    finally:
        conn.close()

@app.route('/api/login', methods=['POST'])
def login():
    data = request.json
    username = data.get('username')
    password = data.get('password')
    
    conn = get_db()
    cursor = conn.cursor()
    
    # 1. 查 users
    cursor.execute('SELECT * FROM users WHERE username = ? AND password = ?', (username, password))
    user = cursor.fetchone()
    if user:
        session['username'] = user['username']
        session['role'] = user['role']
        conn.close()
        return jsonify({"message": "登录成功", "role": user['role']})

    # 2. 查 agents
    cursor.execute('SELECT * FROM agents WHERE username = ? AND password = ?', (username, password))
    agent = cursor.fetchone()
    if agent:
        session['username'] = agent['username']
        session['role'] = 'agent'
        conn.close()
        return jsonify({"message": "登录成功", "role": "agent"})
        
    # 3. 查 runners
    cursor.execute('SELECT * FROM runners WHERE username = ? AND password = ?', (username, password))
    runner = cursor.fetchone()
    if runner:
        session['username'] = runner['username']
        session['role'] = 'runner'
        conn.close()
        return jsonify({"message": "登录成功", "role": "runner"})

    conn.close()
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
    
    # 查询代理
    cursor.execute('SELECT id, username, nickname, company, created_at FROM agents')
    for a in cursor.fetchall():
        result.append({
            "id": a['id'], "username": a['username'], "nickname": a['nickname'], 
            "role": "agent", "company": a['company'], 
            "days": (datetime.now() - datetime.strptime(a['created_at'], "%Y-%m-%d %H:%M:%S")).days if a['created_at'] else 0, 
            "orderCount": 0
        })
        
    # 查询配送员
    cursor.execute('SELECT id, username, nickname, created_at FROM runners')
    for r in cursor.fetchall():
        cursor.execute('SELECT COUNT(*) as count FROM tasks WHERE taker = ?', (r['username'],))
        order_count = cursor.fetchone()['count']
        
        result.append({
            "id": r['id'], "username": r['username'], "nickname": r['nickname'], 
            "role": "runner", "company": "", 
            "days": (datetime.now() - datetime.strptime(r['created_at'], "%Y-%m-%d %H:%M:%S")).days if r['created_at'] else 0, 
            "orderCount": order_count
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
        if check_user_exists(cursor, username):
            return jsonify({"error": "该账号已被占用"}), 400
            
        if role == 'agent':
            cursor.execute('INSERT INTO agents (username, password, nickname, company, created_at) VALUES (?, ?, ?, ?, ?)', (username, password, nickname, company, now))
        elif role == 'runner':
            cursor.execute('INSERT INTO runners (username, password, nickname, created_at) VALUES (?, ?, ?, ?)', (username, password, nickname, now))
        else:
            return jsonify({"error": "非法角色"}), 400
            
        conn.commit()
        return jsonify({"message": f"{nickname} 创建成功！"})
    finally:
        conn.close()

# ================= 业务 API =================
@app.route('/api/add_task', methods=['POST'])
def add_task():
    if 'username' not in session: return jsonify({"error": "请先登录"}), 401
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
    # 把 Row 对象转成字典列表返回
    tasks = [dict(r) for r in rows]
    return jsonify(tasks)

@app.route('/api/take_task', methods=['POST'])
def take_task():
    if 'username' not in session: return jsonify({"error": "请先登录"}), 401
    data = request.json
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('UPDATE tasks SET status = "已接单", taker = ? WHERE id = ? AND status = "待接单"', 
                   (session['username'], data.get('task_id')))
    conn.commit()
    conn.close()
    return jsonify({"message": "接单成功！"})

# 新增：上传图片接口
@app.route('/api/upload_image', methods=['POST'])
def upload_image():
    if 'username' not in session: 
        return jsonify({"error": "请先登录"}), 401
    
    if 'file' not in request.files:
        return jsonify({"error": "没有找到文件"}), 400
        
    file = request.files['file']
    task_id = request.form.get('task_id')
    
    if file.filename == '':
        return jsonify({"error": "未选择文件"}), 400

    if file:
        # 生成唯一文件名，防止冲突，并保留原后缀
        ext = file.filename.rsplit('.', 1)[1].lower() if '.' in file.filename else 'jpg'
        filename = f"{uuid.uuid4().hex}.{ext}"
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        
        # 保存文件
        file.save(filepath)
        
        # 存入数据库
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute('UPDATE tasks SET delivery_image = ? WHERE id = ? AND taker = ?', 
                       (filename, task_id, session['username']))
        conn.commit()
        conn.close()
        
        return jsonify({"message": "图片上传成功！"})

# 修改：完成订单接口，不再需要在这里改状态，上传图片后调用此接口
@app.route('/api/complete_task', methods=['POST'])
def complete_task():
    data = request.json
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('UPDATE tasks SET status = "已完成" WHERE id = ?', (data.get('task_id'),))
    conn.commit()
    conn.close()
    return jsonify({"message": "任务已完成！"})

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)