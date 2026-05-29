import os
import time
import json
import psycopg2
from contextlib import contextmanager
from flask import Flask, render_template, render_template_string, request, redirect, url_for, session, flash, send_from_directory
from flask_socketio import SocketIO, emit
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.config['SECRET_KEY'] = 'super_secret_key_123' 
socketio = SocketIO(app, cors_allowed_origins="*")

app.config['UPLOAD_FOLDER'] = 'static/uploads'
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True) 

# ==========================================
# ⚙️ ADMIN CONFIGURATION & DATABASE URL
# ==========================================
ADMIN_USERNAME = "X13"      
ADMIN_PASSWORD = "X13@1013" 

# Fetches the Supabase URL from Render Environment Variables
DATABASE_URL = os.environ.get('DATABASE_URL')

@contextmanager
def get_db():
    # Helper function to open and close Supabase connections safely
    conn = psycopg2.connect(DATABASE_URL, sslmode='require')
    try:
        yield conn
    finally:
        conn.close()

online_users = {}
active_calls = {}

# --- EMBEDDED ADMIN HTML TEMPLATES ---
ADMIN_LOGIN_HTML = """
<!DOCTYPE html><html><head><title>Admin Login</title><style>
    body { background: #030508; color: white; font-family: sans-serif; display: flex; justify-content: center; align-items: center; height: 100vh; margin: 0; }
    .box { background: rgba(255,255,255,0.05); padding: 40px; border-radius: 20px; border: 1px solid rgba(255,255,255,0.1); width: 300px; text-align: center; }
    input { width: 90%; padding: 12px; margin-bottom: 15px; border-radius: 10px; border: none; background: rgba(0,0,0,0.5); color: white; }
    button { width: 100%; padding: 12px; border-radius: 10px; background: #ef4444; color: white; border: none; font-weight: bold; cursor: pointer; }
    .flash { background: rgba(239, 68, 68, 0.2); padding: 10px; margin-bottom: 15px; border-radius: 8px; color: #ef4444; font-size: 14px;}
</style></head><body>
    <div class="box">
        <h2 style="margin-top:0; color:#ef4444;">Admin Portal</h2>
        {% with messages = get_flashed_messages() %}{% if messages %}{% for msg in messages %}<div class="flash">{{ msg }}</div>{% endfor %}{% endif %}{% endwith %}
        <form method="POST">
            <input type="text" name="username" placeholder="Admin Username" required autocomplete="off">
            <input type="password" name="password" placeholder="Password" required>
            <button type="submit">Access Dashboard</button>
            <a href="/login" style="display:block; margin-top:20px; color:#64748b; text-decoration:none; font-size:12px;">← Back to App</a>
        </form>
    </div>
</body></html>
"""

ADMIN_DASHBOARD_HTML = """
<!DOCTYPE html><html><head><title>Admin Dashboard</title><style>
    body { background: #030508; color: white; font-family: sans-serif; margin: 0; padding: 20px; max-width: 1200px; margin: auto;}
    .header { display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid rgba(255,255,255,0.1); padding-bottom: 20px; margin-bottom: 20px; margin-top: 20px;}
    table { width: 100%; border-collapse: collapse; background: rgba(255,255,255,0.05); border-radius: 12px; overflow: hidden; margin-bottom: 40px;}
    th, td { padding: 15px; text-align: left; border-bottom: 1px solid rgba(255,255,255,0.05); }
    th { background: rgba(0,0,0,0.5); color: #94a3b8; font-size: 12px; text-transform: uppercase; }
    .btn { padding: 8px 12px; border-radius: 8px; border: none; font-weight: bold; cursor: pointer; font-size: 12px; color: white; margin-right: 5px; }
    .btn-danger { background: #ef4444; } .btn-warning { background: #f59e0b; } .btn-success { background: #2ed573; }
</style></head><body>
    <div class="header">
        <h2>🛡️ Security & Reports Dashboard</h2>
        <a href="/logout" style="color: #ef4444; text-decoration: none; font-weight: bold;">Logout</a>
    </div>
    
    <h3 style="color: #94a3b8;">🚨 Pending Reports</h3>
    {% if not reports %}
        <p style="color: #64748b; margin-bottom: 40px;">No pending reports at this time. Good job!</p>
    {% else %}
        <table>
            <tr><th>Report ID</th><th>Date</th><th>Reporter</th><th>Target Type</th><th>Reported User/ID</th><th>Reason</th><th>Actions</th></tr>
            {% for r in reports %}
            <tr>
                <td>#{{ r.id }}</td>
                <td style="font-size: 12px; color: #94a3b8;">{{ r.timestamp }}</td>
                <td>{{ r.reporter }}</td>
                <td><span style="background: rgba(255,255,255,0.1); padding: 4px 8px; border-radius: 10px; font-size:11px;">{{ r.reported_type }}</span></td>
                <td style="font-weight: bold;">{{ r.reported_target }}</td>
                <td style="color: #f59e0b;">{{ r.reason }}</td>
                <td>
                    <form method="POST" action="/admin/action" style="display:inline;">
                        <input type="hidden" name="report_id" value="{{ r.id }}">
                        <input type="hidden" name="target" value="{{ r.reported_target }}">
                        
                        {% if r.reported_type == 'user' %}
                            <button class="btn btn-warning" name="action" value="freeze_user" onclick="return confirm('Freeze this user? They will be logged out.')">Freeze User</button>
                            <button class="btn btn-danger" name="action" value="delete_user" onclick="return confirm('Soft delete this user? They can reactivate if they log back in.')">Delete User</button>
                        {% elif r.reported_type == 'reel' %}
                            <button class="btn btn-danger" name="action" value="delete_reel" onclick="return confirm('Delete this Reel?')">Delete Reel</button>
                        {% endif %}
                        
                        <button class="btn btn-success" name="action" value="dismiss">Dismiss Report</button>
                    </form>
                </td>
            </tr>
            {% endfor %}
        </table>
    {% endif %}

    <h3 style="color: #94a3b8; border-top: 1px solid rgba(255,255,255,0.1); padding-top: 20px;">❄️ Frozen Accounts</h3>
    {% if not frozen_users %}
        <p style="color: #64748b; margin-bottom: 40px;">No users are currently frozen.</p>
    {% else %}
        <table style="width: 50%; margin-bottom: 40px;">
            <tr><th>Frozen Username</th><th>Action</th></tr>
            {% for u in frozen_users %}
            <tr>
                <td style="font-weight: bold; color: #f59e0b;">{{ u }}</td>
                <td>
                    <form method="POST" action="/admin/action" style="display:inline;">
                        <input type="hidden" name="target" value="{{ u }}">
                        <button class="btn btn-success" name="action" value="unfreeze_user" onclick="return confirm('Restore this users access?')">Unfreeze User</button>
                        <button class="btn btn-danger" name="action" value="delete_user" onclick="return confirm('Delete this frozen account?')">Delete User</button>
                    </form>
                </td>
            </tr>
            {% endfor %}
        </table>
    {% endif %}

    <h3 style="color: #94a3b8; border-top: 1px solid rgba(255,255,255,0.1); padding-top: 20px;">⚙️ Global Settings</h3>
    <table style="width: 50%;">
        <tr><th>Feature</th><th>Status</th><th>Action</th></tr>
        <tr>
            <td style="font-weight: bold;">Reels Feed</td>
            <td style="color: {{ '#2ed573' if reels_enabled else '#ef4444' }};">{{ '🟢 Active' if reels_enabled else '🔴 Hidden' }}</td>
            <td>
                <form method="POST" action="/admin/action" style="display:inline;">
                    <input type="hidden" name="action" value="toggle_reels">
                    <input type="hidden" name="target" value="{{ '0' if reels_enabled else '1' }}">
                    <button class="btn {{ 'btn-danger' if reels_enabled else 'btn-success' }}">{{ 'Disable' if reels_enabled else 'Enable' }}</button>
                </form>
            </td>
        </tr>
    </table>
</body></html>
"""
# ---------------------------------------------

def init_db():
    if not DATABASE_URL: return
    with get_db() as conn:
        c = conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS users (id SERIAL PRIMARY KEY, username TEXT UNIQUE, password TEXT, avatar TEXT DEFAULT '/static/WS.jpg', bio TEXT DEFAULT 'Available')''')
        c.execute('''CREATE TABLE IF NOT EXISTS messages (id SERIAL PRIMARY KEY, sender TEXT, recipient TEXT, message TEXT)''')
        c.execute('''CREATE TABLE IF NOT EXISTS custom_groups (id SERIAL PRIMARY KEY, name TEXT, members TEXT)''')
        c.execute('''CREATE TABLE IF NOT EXISTS blocked_users (id SERIAL PRIMARY KEY, blocker TEXT, blocked TEXT)''')
        c.execute('''CREATE TABLE IF NOT EXISTS reels (id SERIAL PRIMARY KEY, username TEXT, video_url TEXT, caption TEXT, views INTEGER DEFAULT 0)''')
        c.execute('''CREATE TABLE IF NOT EXISTS calls (id SERIAL PRIMARY KEY, caller TEXT, receiver TEXT, call_type TEXT, status TEXT, timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
        c.execute('''CREATE TABLE IF NOT EXISTS statuses (id SERIAL PRIMARY KEY, username TEXT, media_url TEXT, caption TEXT, timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
        c.execute('''CREATE TABLE IF NOT EXISTS friendships (id SERIAL PRIMARY KEY, sender TEXT, receiver TEXT, status TEXT)''')
        c.execute('''CREATE TABLE IF NOT EXISTS reports (id SERIAL PRIMARY KEY, reporter TEXT, reported_type TEXT, reported_target TEXT, reason TEXT, status TEXT DEFAULT 'pending', timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
        c.execute('''CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)''')

        c.execute("INSERT INTO settings (key, value) VALUES ('reels_enabled', '0') ON CONFLICT (key) DO NOTHING")

        # Safely add columns for Postgres
        c.execute("ALTER TABLE messages ADD COLUMN IF NOT EXISTS is_read INTEGER DEFAULT 0")
        c.execute("ALTER TABLE calls ADD COLUMN IF NOT EXISTS is_read INTEGER DEFAULT 0")
        c.execute("ALTER TABLE statuses ADD COLUMN IF NOT EXISTS viewers TEXT DEFAULT ''")
        c.execute("ALTER TABLE messages ADD COLUMN IF NOT EXISTS reactions TEXT DEFAULT '{}'")
        c.execute("ALTER TABLE reels ADD COLUMN IF NOT EXISTS likes INTEGER DEFAULT 0")
        c.execute("ALTER TABLE reels ADD COLUMN IF NOT EXISTS liked_by TEXT DEFAULT ''")
        c.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS role TEXT DEFAULT 'user'")
        c.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS account_status TEXT DEFAULT 'active'")
        c.execute("ALTER TABLE reports ADD COLUMN IF NOT EXISTS status TEXT DEFAULT 'pending'")

        # Admin Account Check
        hashed_admin_pw = generate_password_hash(ADMIN_PASSWORD)
        c.execute("SELECT * FROM users WHERE role='admin'")
        if not c.fetchone():
            c.execute("INSERT INTO users (username, password, role) VALUES (%s, %s, 'admin')", (ADMIN_USERNAME.lower(), hashed_admin_pw))
        else:
            c.execute("UPDATE users SET username=%s, password=%s WHERE role='admin'", (ADMIN_USERNAME.lower(), hashed_admin_pw))
        conn.commit()

init_db()

@app.route('/sw.js')
def sw():
    return send_from_directory('static', 'sw.js', mimetype='application/javascript')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if 'username' in session: 
        return redirect(url_for('index'))

    if request.method == 'POST':
        username = request.form['username'].strip().lower()
        password = request.form['password']
        hashed_pw = generate_password_hash(password) 
        try:
            with get_db() as conn:
                c = conn.cursor()
                c.execute("INSERT INTO users (username, password, avatar, bio) VALUES (%s, %s, '/static/WS.jpg', 'Available')", (username, hashed_pw))
                conn.commit()
            flash("Account created successfully! Please log in.")
            return redirect(url_for('login'))
        except psycopg2.IntegrityError:
            flash("Username already exists! Try another.")
            return redirect(url_for('register'))
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if 'username' in session: 
        return redirect(url_for('index'))

    if request.method == 'POST':
        username = request.form['username'].strip().lower()
        password = request.form['password']
        with get_db() as conn:
            c = conn.cursor()
            c.execute("SELECT password, account_status, role FROM users WHERE username=%s", (username,))
            user = c.fetchone()
        
        if user and check_password_hash(user[0], password):
            if user[1] == 'frozen':
                flash("This account has been suspended by an Administrator.")
                return redirect(url_for('login'))
            
            if user[1] == 'deleted':
                with get_db() as conn:
                    c = conn.cursor()
                    c.execute("UPDATE users SET account_status='active' WHERE username=%s", (username,))
                    conn.commit()
                flash("Welcome back! Your account has been successfully reactivated.")
                
            session['username'] = username 
            session['role'] = user[2]
            return redirect(url_for('index'))
        else:
            flash("Invalid Username or Password!")
            return redirect(url_for('login'))
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.pop('username', None) 
    session.pop('role', None) 
    return redirect(url_for('login'))

@app.route('/')
def index():
    if 'username' not in session: return redirect(url_for('login'))
    username = session['username']
    
    with get_db() as conn:
        c = conn.cursor()
        c.execute("SELECT avatar, bio, account_status, role FROM users WHERE username=%s", (username,))
        row = c.fetchone()
        
        if row and row[2] == 'frozen':
            return redirect(url_for('logout'))
            
        avatar = row[0] if row and row[0] else '/static/WS.jpg'
        bio = row[1] if row and row[1] else 'Available'
        role = row[3] if row and len(row) > 3 else 'user'
        
        c.execute("SELECT value FROM settings WHERE key='reels_enabled'")
        setting = c.fetchone()
        reels_enabled = True if setting and setting[0] == '1' else False
        
    return render_template('index.html', my_name=username, my_avatar=avatar, my_bio=bio, my_role=role, reels_enabled=reels_enabled)

# ==========================================
# ADMIN ROUTES
# ==========================================
@app.route('/my_secret_vault_99', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        username = request.form['username'].strip().lower()
        password = request.form['password']
        with get_db() as conn:
            c = conn.cursor()
            c.execute("SELECT password, role FROM users WHERE username=%s", (username,))
            user = c.fetchone()
        
        if user and check_password_hash(user[0], password) and user[1] == 'admin':
            session['username'] = username 
            session['role'] = 'admin'
            return redirect(url_for('admin_dashboard'))
        else:
            flash("Access Denied: Invalid Admin Credentials.")
            return redirect(url_for('admin_login'))
    return render_template_string(ADMIN_LOGIN_HTML)

@app.route('/admin/dashboard')
def admin_dashboard():
    if session.get('role') != 'admin':
        return redirect(url_for('admin_login'))
        
    with get_db() as conn:
        c = conn.cursor()
        c.execute("SELECT id, reporter, reported_type, reported_target, reason, timestamp FROM reports WHERE status='pending' ORDER BY id DESC")
        reports = [{'id': r[0], 'reporter': r[1], 'reported_type': r[2], 'reported_target': r[3], 'reason': r[4], 'timestamp': r[5].strftime('%Y-%m-%d %H:%M') if r[5] else ''} for r in c.fetchall()]
        
        c.execute("SELECT username FROM users WHERE account_status='frozen'")
        frozen_users = [r[0] for r in c.fetchall()]
        
        c.execute("SELECT value FROM settings WHERE key='reels_enabled'")
        setting = c.fetchone()
        reels_enabled = True if setting and setting[0] == '1' else False
        
    return render_template_string(ADMIN_DASHBOARD_HTML, reports=reports, frozen_users=frozen_users, reels_enabled=reels_enabled)

@app.route('/admin/action', methods=['POST'])
def admin_action():
    if session.get('role') != 'admin': return "Unauthorized", 403
    
    action = request.form.get('action')
    target = request.form.get('target')
    report_id = request.form.get('report_id')
    
    with get_db() as conn:
        c = conn.cursor()
        
        if action == 'freeze_user':
            c.execute("UPDATE users SET account_status='frozen' WHERE username=%s", (target,))
            if target in online_users:
                socketio.emit('force_logout', "Your account has been suspended by an Administrator.", room=online_users[target])
        
        elif action == 'unfreeze_user':
            c.execute("UPDATE users SET account_status='active' WHERE username=%s", (target,))
            
        elif action == 'delete_user':
            c.execute("UPDATE users SET account_status='deleted' WHERE username=%s", (target,))
            c.execute("DELETE FROM messages WHERE sender=%s OR recipient=%s", (target, target))
            if target in online_users:
                socketio.emit('force_logout', "Your account has been deleted by an Administrator.", room=online_users[target])
        
        elif action == 'delete_reel':
            c.execute("DELETE FROM reels WHERE id=%s", (target,))
            socketio.emit('reel_deleted', target, broadcast=True)

        elif action == 'toggle_reels':
            c.execute("UPDATE settings SET value=%s WHERE key='reels_enabled'", (target,))
            socketio.emit('reels_state_changed', target == '1')

        if report_id:
            c.execute("UPDATE reports SET status='resolved' WHERE id=%s", (report_id,))
            
        conn.commit()
        
    return redirect(url_for('admin_dashboard'))

# ==========================================
# STANDARD ROUTES
# ==========================================
@app.route('/upload', methods=['POST'])
def upload_file():
    if 'file' not in request.files: return "No file", 400
    file = request.files['file']
    if file.filename == '': return "No file selected", 400
    if file:
        original_name = secure_filename(file.filename)
        filename = f"{int(time.time())}_{original_name}"
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(filepath)
        web_url = f"/static/uploads/{filename}"
        return f"{web_url}|{original_name}", 200

@app.route('/block_user', methods=['POST'])
def block_user():
    blocker = session.get('username')
    blocked = request.form.get('target')
    if not blocker or not blocked: return "Error", 400
    with get_db() as conn:
        c = conn.cursor()
        c.execute("INSERT INTO blocked_users (blocker, blocked) VALUES (%s, %s)", (blocker, blocked))
        conn.commit()
    return "OK", 200

@app.route('/unblock_user', methods=['POST'])
def unblock_user():
    blocker = session.get('username')
    blocked = request.form.get('target')
    if not blocker or not blocked: return "Error", 400
    with get_db() as conn:
        c = conn.cursor()
        c.execute("DELETE FROM blocked_users WHERE blocker=%s AND blocked=%s", (blocker, blocked))
        conn.commit()
    return "OK", 200

@app.route('/leave_group', methods=['POST'])
def leave_group():
    username = session.get('username')
    group_id_str = request.form.get('group_id')
    if not username or not group_id_str: return "Error", 400
    
    group_id = group_id_str.replace("GROUP_", "")
    with get_db() as conn:
        c = conn.cursor()
        c.execute("SELECT members FROM custom_groups WHERE id=%s", (group_id,))
        row = c.fetchone()
        if row:
            members = row[0].split(',')
            if username in members:
                members.remove(username)
                if len(members) > 0:
                    c.execute("UPDATE custom_groups SET members=%s WHERE id=%s", (",".join(members), group_id))
                else:
                    c.execute("DELETE FROM custom_groups WHERE id=%s", (group_id,))
            conn.commit()
    return "OK", 200

@socketio.on('register')
def handle_register(username):
    with get_db() as conn:
        c = conn.cursor()
        c.execute("SELECT account_status FROM users WHERE username=%s", (username,))
        row = c.fetchone()
        if row and row[0] == 'frozen':
            emit('force_logout', "Your account is frozen.", room=request.sid)
            return

    online_users[username] = request.sid
    with get_db() as conn:
        c = conn.cursor()
        c.execute("SELECT blocked FROM blocked_users WHERE blocker=%s", (username,))
        blocked_by_me = [row[0] for row in c.fetchall()]

        c.execute("SELECT username FROM users WHERE account_status='active' AND role!='admin'")
        all_users = [row[0] for row in c.fetchall()]

        c.execute("SELECT username, avatar, bio FROM users")
        profiles = {row[0]: {'avatar': row[1] or '/static/WS.jpg', 'bio': row[2] or 'Available'} for row in c.fetchall()}

        c.execute("SELECT id, name, members FROM custom_groups")
        my_groups = []
        for g in c.fetchall():
            member_list = g[2].split(',')
            if username in member_list:
                my_groups.append({'id': f"GROUP_{g[0]}", 'name': g[1], 'members': member_list})
                
        c.execute("SELECT COUNT(*) FROM calls WHERE receiver=%s AND status='Missed' AND is_read=0", (username,))
        unread_calls = c.fetchone()[0]

        c.execute("SELECT sender, receiver, status FROM friendships WHERE sender=%s OR receiver=%s", (username, username))
        friendships = [{'sender': row[0], 'receiver': row[1], 'status': row[2]} for row in c.fetchall()]

    emit('update_users', {'contacts': all_users, 'online': list(online_users.keys()), 'groups': my_groups, 'blocked': blocked_by_me, 'profiles': profiles}, broadcast=True)
    emit('load_friendships', friendships, room=request.sid)

    group_ids = [g['id'] for g in my_groups]
    query = '''SELECT id, sender, recipient, message, is_read, reactions FROM messages 
               WHERE (recipient = '' OR recipient IS NULL OR recipient = %s OR sender = %s)'''
    params = [username, username]
    if group_ids:
        placeholders = ','.join(['%s'] * len(group_ids))
        query += f" OR recipient IN ({placeholders})"
        params.extend([f"GROUP_{gid}" for gid in group_ids])
        
    with get_db() as conn:
        c = conn.cursor()
        c.execute(query, params)
        history = [{'id': row[0], 'user': row[1], 'recipient': row[2] if row[2] else None, 'message': row[3], 'is_read': row[4], 'reactions': json.loads(row[5]) if row[5] else {}} for row in c.fetchall()]
    
    emit('load_history', history, room=request.sid)
    emit('unread_calls_count', unread_calls, room=request.sid) 

@socketio.on('add_reaction')
def handle_add_reaction(data):
    msg_id = data['msg_id']
    reaction = data['reaction']
    username = data['username']
    
    with get_db() as conn:
        c = conn.cursor()
        c.execute("SELECT reactions FROM messages WHERE id=%s", (msg_id,))
        row = c.fetchone()
        if row:
            try: reactions_dict = json.loads(row[0]) if row[0] else {}
            except json.JSONDecodeError: reactions_dict = {}
            
            if reactions_dict.get(username) == reaction:
                del reactions_dict[username]
            else:
                reactions_dict[username] = reaction
                
            c.execute("UPDATE messages SET reactions=%s WHERE id=%s", (json.dumps(reactions_dict), msg_id))
            conn.commit()
            emit('reaction_updated', {'msg_id': msg_id, 'reactions': reactions_dict}, broadcast=True)

@socketio.on('mark_read')
def handle_mark_read(data):
    sender = data.get('sender')
    recipient = data.get('recipient')
    if sender and recipient:
        with get_db() as conn:
            c = conn.cursor()
            c.execute("UPDATE messages SET is_read = 1 WHERE sender = %s AND recipient = %s", (sender, recipient))
            conn.commit()
        if sender in online_users:
            emit('messages_read', {'reader': recipient}, room=online_users[sender])

@socketio.on('update_profile')
def handle_update_profile(data):
    username = data.get('username')
    avatar = data.get('avatar')
    bio = data.get('bio')
    with get_db() as conn:
        c = conn.cursor()
        c.execute("UPDATE users SET avatar=%s, bio=%s WHERE username=%s", (avatar, bio, username))
        conn.commit()
    emit('profile_updated', {'username': username, 'avatar': avatar, 'bio': bio}, broadcast=True)

@socketio.on('create_group')
def handle_create_group(data):
    name = data['name']
    members = ",".join(data['members'])
    with get_db() as conn:
        c = conn.cursor()
        c.execute("INSERT INTO custom_groups (name, members) VALUES (%s, %s) RETURNING id", (name, members))
        group_id = c.fetchone()[0]
        conn.commit()
    
    group_data = {'id': f"GROUP_{group_id}", 'name': name, 'members': data['members']}
    for member in data['members']:
        if member in online_users:
            emit('group_added', group_data, room=online_users[member])

@socketio.on('disconnect')
def handle_disconnect():
    users_to_remove = [user for user, sid in online_users.items() if sid == request.sid]
    for user in users_to_remove:
        del online_users[user]
    emit('update_users', {'online': list(online_users.keys())}, broadcast=True)

@socketio.on('send_message')
def handle_message(data):
    sender = data.get('user')
    recipient = data.get('recipient') or "" 
    message = data.get('message')

    with get_db() as conn:
        c = conn.cursor()
        if recipient and not recipient.startswith("GROUP_"):
            c.execute("SELECT 1 FROM blocked_users WHERE blocker=%s AND blocked=%s", (recipient, sender))
            if c.fetchone(): return 

        c.execute("INSERT INTO messages (sender, recipient, message, is_read, reactions) VALUES (%s, %s, %s, 0, '{}') RETURNING id", (sender, recipient, message))
        msg_id = c.fetchone()[0]
        conn.commit()
        data['id'] = msg_id 
        data['is_read'] = 0
        data['reactions'] = {}

        if recipient.startswith("GROUP_"):
            group_id = recipient.split("_")[1]
            c.execute("SELECT members FROM custom_groups WHERE id=%s", (group_id,))
            res = c.fetchone()
            if res:
                members = res[0].split(',')
                for member in members:
                    if member in online_users:
                        emit('receive_message', data, room=online_users[member])
        elif recipient:
            if recipient in online_users:
                emit('receive_message', data, room=online_users[recipient])
            emit('receive_message', data, room=request.sid)
        elif not recipient:
            emit('receive_message', data, broadcast=True)

@socketio.on('delete_message')
def handle_delete(msg_id):
    with get_db() as conn:
        c = conn.cursor()
        c.execute("DELETE FROM messages WHERE id=%s", (msg_id,))
        conn.commit()
    emit('message_deleted', msg_id, broadcast=True)

@socketio.on('typing')
def handle_typing(data):
    sender = data.get('sender')
    recipient = data.get('recipient') or ""
    if recipient.startswith("GROUP_"):
        group_id = recipient.split("_")[1]
        with get_db() as conn:
            c = conn.cursor()
            c.execute("SELECT members FROM custom_groups WHERE id=%s", (group_id,))
            res = c.fetchone()
            if res:
                members = res[0].split(',')
                for member in members:
                    if member in online_users and member != sender:
                        emit('typing', data, room=online_users[member])
    elif recipient in online_users:
        emit('typing', data, room=online_users[recipient])

# ==========================================
# STATUS (24 HOUR STORIES) ROUTES
# ==========================================
@socketio.on('publish_status')
def handle_publish_status(data):
    username = data.get('username')
    media_url = data.get('media_url')
    caption = data.get('caption')
    with get_db() as conn:
        c = conn.cursor()
        c.execute("INSERT INTO statuses (username, media_url, caption, viewers) VALUES (%s, %s, %s, '')", (username, media_url, caption))
        conn.commit()
    emit('status_updated', broadcast=True)

@socketio.on('request_statuses')
def handle_request_statuses():
    with get_db() as conn:
        c = conn.cursor()
        c.execute("SELECT id, username, media_url, caption, timestamp, viewers FROM statuses WHERE timestamp >= NOW() - INTERVAL '24 HOURS' ORDER BY timestamp ASC")
        statuses = [{'id': row[0], 'username': row[1], 'media_url': row[2], 'caption': row[3], 'time': row[4].strftime('%Y-%m-%d %H:%M:%S') if row[4] else '', 'viewers': row[5]} for row in c.fetchall()]
    emit('load_statuses', statuses, room=request.sid)

@socketio.on('view_status')
def handle_view_status(data):
    status_id = data.get('status_id')
    viewer = data.get('username')
    with get_db() as conn:
        c = conn.cursor()
        c.execute("SELECT viewers FROM statuses WHERE id=%s", (status_id,))
        row = c.fetchone()
        if row:
            viewers = row[0].split(',') if row[0] else []
            if viewer not in viewers:
                viewers.append(viewer)
                c.execute("UPDATE statuses SET viewers=%s WHERE id=%s", (",".join(viewers), status_id))
                conn.commit()

@socketio.on('delete_status')
def handle_delete_status(status_id):
    with get_db() as conn:
        c = conn.cursor()
        c.execute("DELETE FROM statuses WHERE id=%s", (status_id,))
        conn.commit()
    emit('status_updated', broadcast=True)

@socketio.on('edit_status')
def handle_edit_status(data):
    status_id = data.get('status_id')
    new_caption = data.get('caption')
    with get_db() as conn:
        c = conn.cursor()
        c.execute("UPDATE statuses SET caption=%s WHERE id=%s", (new_caption, status_id))
        conn.commit()
    emit('status_updated', broadcast=True)

# ==========================================
# REELS ROUTES
# ==========================================
@socketio.on('publish_reel')
def handle_publish_reel(data):
    username = data.get('username')
    video_url = data.get('video_url')
    caption = data.get('caption')
    with get_db() as conn:
        c = conn.cursor()
        c.execute("INSERT INTO reels (username, video_url, caption, views, likes, liked_by) VALUES (%s, %s, %s, 0, 0, '') RETURNING id", (username, video_url, caption))
        reel_id = c.fetchone()[0]
        conn.commit()
    emit('new_reel', {'id': reel_id, 'username': username, 'video_url': video_url, 'caption': caption, 'views': 0, 'likes': 0, 'liked_by': ''}, broadcast=True)

@socketio.on('request_reels')
def handle_request_reels():
    with get_db() as conn:
        c = conn.cursor()
        c.execute("SELECT id, username, video_url, caption, views, likes, liked_by FROM reels ORDER BY id DESC")
        reels = [{'id': row[0], 'username': row[1], 'video_url': row[2], 'caption': row[3], 'views': row[4], 'likes': row[5], 'liked_by': row[6]} for row in c.fetchall()]
    emit('load_reels', reels, room=request.sid)

@socketio.on('increment_view')
def handle_increment_view(reel_id):
    with get_db() as conn:
        c = conn.cursor()
        c.execute("UPDATE reels SET views = views + 1 WHERE id = %s", (reel_id,))
        conn.commit()

@socketio.on('like_reel')
def handle_like_reel(data):
    reel_id = data.get('id')
    username = data.get('username')
    with get_db() as conn:
        c = conn.cursor()
        c.execute("SELECT liked_by FROM reels WHERE id=%s", (reel_id,))
        row = c.fetchone()
        if row:
            liked_by = row[0].split(',') if row[0] else []
            if username in liked_by:
                liked_by.remove(username)
            else:
                liked_by.append(username)
            
            new_liked_by = ",".join(liked_by)
            new_likes = len(liked_by)
            c.execute("UPDATE reels SET likes=%s, liked_by=%s WHERE id=%s", (new_likes, new_liked_by, reel_id))
            conn.commit()
            emit('reel_liked', {'id': reel_id, 'likes': new_likes, 'liked_by': new_liked_by}, broadcast=True)

@socketio.on('request_my_reels')
def handle_request_my_reels(username):
    with get_db() as conn:
        c = conn.cursor()
        c.execute("SELECT id, video_url, caption, views, likes, liked_by FROM reels WHERE username = %s ORDER BY id DESC", (username,))
        my_reels = [{'id': row[0], 'video_url': row[1], 'caption': row[2], 'views': row[3], 'likes': row[4], 'liked_by': row[5]} for row in c.fetchall()]
    emit('load_my_reels', my_reels, room=request.sid)

@socketio.on('delete_reel')
def handle_delete_reel(data):
    reel_id = data.get('id')
    username = data.get('username')
    with get_db() as conn:
        c = conn.cursor()
        c.execute("DELETE FROM reels WHERE id=%s AND username=%s", (reel_id, username))
        conn.commit()
    emit('reel_deleted', reel_id, broadcast=True)
    handle_request_my_reels(username)

# ==========================================
# REPORT LOGIC
# ==========================================
@socketio.on('report_item')
def handle_report_item(data):
    reporter = data.get('reporter')
    reported_type = data.get('type')
    reported_target = data.get('target')
    reason = data.get('reason')
    
    with get_db() as conn:
        c = conn.cursor()
        c.execute("INSERT INTO reports (reporter, reported_type, reported_target, reason) VALUES (%s, %s, %s, %s)", 
                  (reporter, reported_type, str(reported_target), reason))
        conn.commit()

# ==========================================
# CALL LOGIC & WEBRTC ROUTES
# ==========================================
@socketio.on('request_call_history')
def handle_call_history(username):
    with get_db() as conn:
        c = conn.cursor()
        c.execute("UPDATE calls SET is_read = 1 WHERE receiver = %s AND status = 'Missed'", (username,))
        conn.commit()
        
        c.execute("SELECT caller, receiver, call_type, status, timestamp FROM calls WHERE caller = %s OR receiver = %s ORDER BY id DESC LIMIT 50", (username, username))
        calls = [{'caller': row[0], 'receiver': row[1], 'type': row[2], 'status': row[3], 'time': row[4].strftime('%Y-%m-%d %H:%M:%S') if row[4] else ''} for row in c.fetchall()]
    emit('load_call_history', calls, room=request.sid)
    emit('unread_calls_count', 0, room=request.sid) 

@socketio.on('webrtc_offer')
def handle_offer(data):
    caller = data['sender']
    receiver = data['recipient']
    call_type = 'Video' if data.get('isVideo') else 'Audio'
    
    with get_db() as conn:
        c = conn.cursor()
        c.execute("INSERT INTO calls (caller, receiver, call_type, status) VALUES (%s, %s, %s, 'Missed') RETURNING id", (caller, receiver, call_type))
        call_id = c.fetchone()[0]
        conn.commit()
    
    active_calls[caller] = call_id
    data['call_id'] = call_id

    if receiver in online_users: 
        emit('webrtc_offer', data, room=online_users[receiver])

@socketio.on('webrtc_answer')
def handle_answer(data):
    caller = data['recipient']
    call_id = data.get('call_id')
    if not call_id and caller in active_calls:
        call_id = active_calls[caller]

    if call_id:
        with get_db() as conn:
            c = conn.cursor()
            c.execute("UPDATE calls SET status = 'Answered', is_read = 1 WHERE id = %s", (call_id,))
            conn.commit()

    if caller in online_users: 
        emit('webrtc_answer', data, room=online_users[caller])

@socketio.on('reject_call')
def handle_reject_call(data):
    caller = data['sender']
    call_id = data.get('call_id')
    if not call_id and caller in active_calls:
        call_id = active_calls[caller]
        
    if call_id:
        with get_db() as conn:
            c = conn.cursor()
            c.execute("UPDATE calls SET status = 'Declined', is_read = 1 WHERE id = %s", (call_id,))
            conn.commit()
            
    if caller in online_users: 
        emit('call_rejected', data, room=online_users[caller])

@socketio.on('webrtc_ice_candidate')
def handle_ice_candidate(data):
    if data['recipient'] in online_users: 
        emit('webrtc_ice_candidate', data, room=online_users[data['recipient']])

@socketio.on('end_call')
def handle_end_call(data):
    if data['recipient'] in online_users: 
        emit('call_ended', data, room=online_users[data['recipient']])
        
        with get_db() as conn:
            c = conn.cursor()
            c.execute("SELECT COUNT(*) FROM calls WHERE receiver=%s AND status='Missed' AND is_read=0", (data['recipient'],))
            unread = c.fetchone()[0]
        emit('unread_calls_count', unread, room=online_users[data['recipient']])

# ==========================================
# FRIEND REQUEST ROUTES
# ==========================================
@socketio.on('send_friend_request')
def handle_send_friend_request(data):
    sender = data.get('sender')
    receiver = data.get('receiver')
    with get_db() as conn:
        c = conn.cursor()
        c.execute("SELECT 1 FROM friendships WHERE (sender=%s AND receiver=%s) OR (sender=%s AND receiver=%s)", (sender, receiver, receiver, sender))
        if not c.fetchone():
            c.execute("INSERT INTO friendships (sender, receiver, status) VALUES (%s, %s, 'pending')", (sender, receiver))
            conn.commit()
    
    update = {'sender': sender, 'receiver': receiver, 'status': 'pending'}
    if sender in online_users: emit('friendship_update', update, room=online_users[sender])
    if receiver in online_users: emit('friendship_update', update, room=online_users[receiver])

@socketio.on('accept_friend_request')
def handle_accept_friend_request(data):
    sender = data.get('sender')
    receiver = data.get('receiver')
    with get_db() as conn:
        c = conn.cursor()
        c.execute("UPDATE friendships SET status='accepted' WHERE sender=%s AND receiver=%s", (sender, receiver))
        conn.commit()
        
    update = {'sender': sender, 'receiver': receiver, 'status': 'accepted'}
    if sender in online_users: emit('friendship_update', update, room=online_users[sender])
    if receiver in online_users: emit('friendship_update', update, room=online_users[receiver])

@socketio.on('reject_friend_request')
def handle_reject_friend_request(data):
    sender = data.get('sender')
    receiver = data.get('receiver')
    with get_db() as conn:
        c = conn.cursor()
        c.execute("DELETE FROM friendships WHERE sender=%s AND receiver=%s", (sender, receiver))
        conn.commit()
        
    update = {'sender': sender, 'receiver': receiver, 'status': 'rejected'}
    if sender in online_users: emit('friendship_update', update, room=online_users[sender])
    if receiver in online_users: emit('friendship_update', update, room=online_users[receiver])

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=5000, debug=True)
