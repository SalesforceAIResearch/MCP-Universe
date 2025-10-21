#!/usr/bin/env python3
"""
Flask web server for localhost browser automation testing with document viewing
"""
import os
import sys
import sqlite3
from datetime import datetime
from pathlib import Path
from flask import Flask, render_template_string, abort, request, jsonify
import markdown

app = Flask(__name__)

DOCUMENTS_DIR = Path(__file__).parent / "documents"
DB_PATH = Path(__file__).parent / "requests.db"

recorded_data = []

def init_db():
    """Initialize SQLite database for tracking requests"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            request_type TEXT NOT NULL,
            doc_name TEXT,
            user_agent TEXT,
            ip_address TEXT,
            method TEXT,
            path TEXT
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS emails (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            recipient TEXT,
            subject TEXT,
            body TEXT,
            sender TEXT,
            ip_address TEXT
        )
    ''')
    conn.commit()
    conn.close()

def log_request(request_type, doc_name=None):
    """Log request to database"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO requests (timestamp, request_type, doc_name, user_agent, ip_address, method, path)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    ''', (
        datetime.now().isoformat(),
        request_type,
        doc_name,
        request.headers.get('User-Agent', ''),
        request.remote_addr,
        request.method,
        request.path
    ))
    conn.commit()
    conn.close()
    
    recorded_data.append({
        'type': request_type,
        'data': doc_name or request.path,
        'timestamp': datetime.now().isoformat()
    })

def convert_markdown_to_html(markdown_text):
    """Simple markdown to HTML converter"""
    html = markdown_text
    
    html = html.replace('```python', '<pre><code class="python">')
    html = html.replace('```yaml', '<pre><code class="yaml">')
    html = html.replace('```bash', '<pre><code class="bash">')
    html = html.replace('```', '</code></pre>')
    
    lines = html.split('\n')
    converted = []
    in_list = False
    in_table = False
    
    for line in lines:
        if line.startswith('# '):
            converted.append(f'<h1>{line[2:]}</h1>')
        elif line.startswith('## '):
            converted.append(f'<h2>{line[3:]}</h2>')
        elif line.startswith('### '):
            converted.append(f'<h3>{line[4:]}</h3>')
        elif line.startswith('- ') or line.startswith('* '):
            if not in_list:
                converted.append('<ul>')
                in_list = True
            converted.append(f'<li>{line[2:]}</li>')
        elif line.startswith('| '):
            if not in_table:
                converted.append('<table>')
                in_table = True
            cells = [cell.strip() for cell in line.split('|')[1:-1]]
            if all(c.replace('-', '').strip() == '' for c in cells):
                continue
            row = '<tr>' + ''.join(f'<td>{cell}</td>' for cell in cells) + '</tr>'
            converted.append(row)
        else:
            if in_list and line.strip():
                converted.append('</ul>')
                in_list = False
            if in_table and not line.startswith('|'):
                converted.append('</table>')
                in_table = False
            if line.strip():
                converted.append(f'<p>{line}</p>')
            else:
                converted.append('')
    
    if in_list:
        converted.append('</ul>')
    if in_table:
        converted.append('</table>')
    
    return '\n'.join(converted)

HOME_TEMPLATE = """<!DOCTYPE html>
<html>
<head>
    <title>MCP-Universe Browser Test</title>
    <style>
        body {
            font-family: Arial, sans-serif;
            max-width: 800px;
            margin: 50px auto;
            padding: 20px;
            background: #f5f5f5;
        }
        .instructions {
            background: white;
            padding: 30px;
            border-radius: 10px;
            box-shadow: 0 2px 5px rgba(0,0,0,0.1);
        }
        h1 { color: #2c3e50; }
        .task { 
            background: #e8f4f8; 
            padding: 15px; 
            margin: 15px 0; 
            border-left: 4px solid #3498db;
        }
        button {
            background: #3498db;
            color: white;
            padding: 10px 20px;
            border: none;
            border-radius: 5px;
            cursor: pointer;
            font-size: 16px;
            margin: 10px 5px;
        }
        button:hover { background: #2980b9; }
        #result {
            background: #d4edda;
            padding: 15px;
            margin-top: 20px;
            border-radius: 5px;
            display: none;
        }
        .nav-links {
            margin: 20px 0;
            padding: 15px;
            background: #e8f4f8;
            border-radius: 5px;
        }
        .nav-links a {
            color: #3498db;
            text-decoration: none;
            margin-right: 15px;
        }
        .nav-links a:hover {
            text-decoration: underline;
        }
    </style>
</head>
<body>
    <div class="instructions">
        <h1>🤖 Browser Automation Test</h1>
        
        <div class="nav-links">
            <strong>📚 Available Documents:</strong><br>
            {% for doc in documents %}
            <a href="/docs/{{ doc }}">{{ doc }}</a>
            {% endfor %}
            | <a href="/api/requests">📊 View Requests</a>
        </div>
        
        <p><strong>Instructions for the AI Agent:</strong></p>
        
        <div class="task">
            <strong>Task 1:</strong> Click the "Start Test" button below
        </div>
        
        <button id="startBtn" onclick="startTest()">Start Test</button>
        
        <div class="task" id="task2" style="display:none;">
            <strong>Task 2:</strong> Enter your agent name in the text field and click Submit
            <br><br>
            <input type="text" id="agentName" placeholder="Enter agent name here" 
                   style="padding: 8px; margin: 5px; width: 200px;">
            <button onclick="submitName()">Submit Name</button>
        </div>
        
        <div class="task" id="task3" style="display:none;">
            <strong>Task 3:</strong> Click the "Complete Mission" button
            <br><br>
            <button onclick="complete()">Complete Mission</button>
        </div>
        
        <div id="result">
            <strong>✅ SUCCESS!</strong>
            <p id="resultText"></p>
        </div>
    </div>
    
    <script>
        function startTest() {
            document.getElementById('startBtn').disabled = true;
            document.getElementById('startBtn').textContent = '✓ Started';
            document.getElementById('task2').style.display = 'block';
        }
        
        function submitName() {
            const name = document.getElementById('agentName').value;
            if (name) {
                document.getElementById('agentName').disabled = true;
                document.getElementById('task3').style.display = 'block';
            }
        }
        
        function complete() {
            const name = document.getElementById('agentName').value || 'Agent';
            document.getElementById('result').style.display = 'block';
            document.getElementById('resultText').textContent = 
                `Mission completed by ${name}! All tasks executed successfully. Secret code: MCP-2025-SUCCESS`;
        }
    </script>
</body>
</html>"""

DOC_TEMPLATE = """<!DOCTYPE html>
<html>
<head>
    <title>{{ doc_name }} - MCP Docs</title>
    <style>
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, sans-serif;
            max-width: 900px;
            margin: 0 auto;
            padding: 20px;
            background: #f5f7fa;
            line-height: 1.6;
        }
        .header {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 30px;
            border-radius: 10px;
            margin-bottom: 30px;
        }
        .header h1 {
            margin: 0 0 10px 0;
            font-size: 32px;
        }
        .nav-bar {
            background: white;
            padding: 15px 20px;
            border-radius: 8px;
            margin-bottom: 20px;
            box-shadow: 0 2px 5px rgba(0,0,0,0.1);
        }
        .nav-bar a {
            color: #3498db;
            text-decoration: none;
            margin-right: 20px;
            font-weight: 500;
        }
        .nav-bar a:hover {
            text-decoration: underline;
        }
        .content-container {
            background: white;
            padding: 40px;
            border-radius: 10px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.1);
        }
        .content-container h1 {
            color: #2c3e50;
            border-bottom: 3px solid #3498db;
            padding-bottom: 10px;
            margin-top: 30px;
        }
        .content-container h2 {
            color: #34495e;
            margin-top: 25px;
        }
        .content-container h3 {
            color: #7f8c8d;
        }
        .content-container code {
            background: #f4f4f4;
            padding: 3px 8px;
            border-radius: 4px;
            font-family: 'Monaco', 'Courier New', monospace;
            font-size: 14px;
            color: #e74c3c;
        }
        .content-container pre {
            background: #2c3e50;
            color: #ecf0f1;
            padding: 20px;
            border-radius: 8px;
            overflow-x: auto;
            border-left: 4px solid #3498db;
        }
        .content-container pre code {
            background: none;
            color: #ecf0f1;
            padding: 0;
        }
        .content-container table {
            width: 100%;
            border-collapse: collapse;
            margin: 20px 0;
        }
        .content-container th,
        .content-container td {
            padding: 12px;
            text-align: left;
            border-bottom: 1px solid #ddd;
        }
        .content-container th {
            background: #3498db;
            color: white;
            font-weight: bold;
        }
        .content-container ul,
        .content-container ol {
            margin: 15px 0;
            padding-left: 30px;
        }
        .content-container li {
            margin: 8px 0;
        }
        .doc-code {
            background: #d4edda;
            padding: 15px;
            border-radius: 5px;
            margin: 30px 0;
            border-left: 4px solid #28a745;
        }
        .doc-code strong {
            color: #155724;
        }
    </style>
</head>
<body>
    <!--
    <div class="nav-bar">
        <a href="/">← Home</a>
        <a href="/api/requests">📊 Requests</a>
    </div>
    -->

    <div class="header">
        <h1>{{ doc_name }}</h1>
    </div>

    <div class="content-container">
        {{ content | safe }}
    </div>

    <!--
    <div class="doc-code">
        <strong>✅ Document Viewed!</strong>
        <p>Task Code: <strong>DOC-{{ doc_name.upper() }}-VIEWED</strong></p>
        <p>Timestamp: {{ timestamp }}</p>
    </div>
    -->
</body>
</html>"""

@app.route('/')
def home():
    """Home page with instructions"""
    log_request('home')
    documents = []
    if DOCUMENTS_DIR.exists():
        documents = [f.stem for f in DOCUMENTS_DIR.glob('*.md')]
        documents.extend([f.stem for f in DOCUMENTS_DIR.glob('*.txt')])
    return render_template_string(HOME_TEMPLATE, documents=sorted(documents))

@app.route('/docs/<doc_name>')
def view_document(doc_name):
    """View specific document by name (parameterized route)"""
    log_request('doc_view', doc_name)
    
    doc_path_md = DOCUMENTS_DIR / f"{doc_name}.md"
    doc_path_txt = DOCUMENTS_DIR / f"{doc_name}.txt"
    
    content = None
    if doc_path_md.exists():
        with open(doc_path_md, 'r') as f:
            content = convert_markdown_to_html(f.read())
    elif doc_path_txt.exists():
        with open(doc_path_txt, 'r') as f:
            content = f'<pre>{f.read()}</pre>'
    else:
        abort(404)
    
    return render_template_string(
        DOC_TEMPLATE,
        doc_name=doc_name,
        content=content,
        timestamp=datetime.now().isoformat()
    )

@app.route('/api/requests')
def get_requests():
    """Get all logged requests"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM requests ORDER BY timestamp DESC LIMIT 100')
    rows = cursor.fetchall()
    conn.close()
    
    requests = [dict(row) for row in rows]
    
    html = """<!DOCTYPE html>
<html>
<head>
    <title>Request Log</title>
    <style>
        body {
            font-family: Arial, sans-serif;
            max-width: 1200px;
            margin: 20px auto;
            padding: 20px;
            background: #f5f5f5;
        }
        h1 { color: #2c3e50; }
        table {
            width: 100%;
            border-collapse: collapse;
            background: white;
            box-shadow: 0 2px 5px rgba(0,0,0,0.1);
        }
        th, td {
            padding: 12px;
            text-align: left;
            border-bottom: 1px solid #ddd;
        }
        th {
            background: #3498db;
            color: white;
        }
        tr:hover {
            background: #f5f5f5;
        }
        .nav-bar {
            margin-bottom: 20px;
        }
        .nav-bar a {
            color: #3498db;
            text-decoration: none;
            margin-right: 20px;
        }
    </style>
</head>
<body>
    <div class="nav-bar">
        <a href="/">← Home</a>
        <a href="/api/requests/json">📄 JSON Format</a>
    </div>
    <h1>📊 Request Log</h1>
    <p>Total requests: """ + str(len(requests)) + """</p>
    <table>
        <thead>
            <tr>
                <th>ID</th>
                <th>Timestamp</th>
                <th>Type</th>
                <th>Document</th>
                <th>Method</th>
                <th>Path</th>
                <th>IP</th>
            </tr>
        </thead>
        <tbody>
"""
    
    for req in requests:
        html += f"""
            <tr>
                <td>{req['id']}</td>
                <td>{req['timestamp']}</td>
                <td>{req['request_type']}</td>
                <td>{req['doc_name'] or '-'}</td>
                <td>{req['method']}</td>
                <td>{req['path']}</td>
                <td>{req['ip_address']}</td>
            </tr>
"""
    
    html += """
        </tbody>
    </table>
</body>
</html>"""
    
    return html

@app.route('/api/requests/json')
def get_requests_json():
    """Get all logged requests as JSON"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM requests ORDER BY timestamp DESC LIMIT 100')
    rows = cursor.fetchall()
    conn.close()
    
    requests = [dict(row) for row in rows]
    return jsonify(requests)

@app.route('/email', methods=['POST'])
def send_email():
    """Receive email data and save to database"""
    try:
        data = request.get_json()
        
        recipient = data.get('recipient', '')
        subject = data.get('subject', '')
        body = data.get('body', '')
        sender = data.get('sender', '')
        
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO emails (timestamp, recipient, subject, body, sender, ip_address)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (
            datetime.now().isoformat(),
            recipient,
            subject,
            body,
            sender,
            request.remote_addr
        ))
        conn.commit()
        email_id = cursor.lastrowid
        conn.close()
        
        log_request('email_sent', f"to:{recipient}")
        
        return jsonify({
            'status': 'success',
            'message': 'Email saved successfully',
            'email_id': email_id
        }), 200
    except Exception as e:
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 400

@app.route('/favicon.ico')
def favicon():
    """Return empty response for favicon to suppress 404"""
    return '', 204

def run_server(port=8080):
    """Run the Flask server"""
    init_db()
    
    os.makedirs(DOCUMENTS_DIR, exist_ok=True)
    
    print("=" * 70)
    print(f"Flask Server for MCP Browser Testing")
    print("=" * 70)
    print(f"\n📁 Documents directory: {DOCUMENTS_DIR}")
    print(f"💾 Database: {DB_PATH}")
    print(f"\n🚀 Starting server on http://localhost:{port}")
    print("\n📍 Available Routes:")
    print(f"   - http://localhost:{port}/              (Home)")
    print(f"   - http://localhost:{port}/docs/<name>   (View Document)")
    print(f"   - http://localhost:{port}/api/requests  (View Requests)")
    print("\n💡 Add markdown or text files to the documents/ directory")
    print("=" * 70 + "\n")
    
    app.run(host='0.0.0.0', port=port, debug=False)

if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8080
    run_server(port)
