from flask import Flask, request, jsonify
import subprocess
import threading
import sys

app = Flask(__name__)

# 禁用Flask的访问日志输出
import logging
log = logging.getLogger('werkzeug')
log.setLevel(logging.ERROR)

@app.route('/exec', methods=['POST'])
def execute_command():
    """
    执行命令的端点
    POST /exec
    Body: {"command": "your_command_here"}
    或者直接发送纯文本命令
    """
    try:
        # 尝试从JSON中获取命令
        if request.is_json:
            command = request.json.get('command', '')
        else:
            # 否则从原始数据中获取
            command = request.data.decode('utf-8').strip()
        
        if not command:
            return jsonify({
                'status': 'error',
                'message': 'No command provided'
            }), 400
        
        # 执行命令
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=30  # 30秒超时
        )
        
        return jsonify({
            'status': 'success',
            'command': command,
            'stdout': result.stdout,
            'stderr': result.stderr,
            'return_code': result.returncode
        })
        
    except subprocess.TimeoutExpired:
        return jsonify({
            'status': 'error',
            'message': 'Command execution timeout (30s)'
        }), 408
    except Exception as e:
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500

@app.route('/health', methods=['GET'])
def health_check():
    """健康检查端点"""
    return jsonify({'status': 'ok'}), 200

@app.errorhandler(404)
def not_found(error):
    return jsonify({
        'status': 'error',
        'message': 'Endpoint not found'
    }), 404

def print_banner():
    """打印启动信息"""
    banner = """
    ╔══════════════════════════════════════╗
    ║     Command Execution Server        ║
    ║     POST Backend Only               ║
    ╠══════════════════════════════════════╣
    ║  Endpoints:                         ║
    ║  POST /exec  - Execute command      ║
    ║  GET  /health - Health check        ║
    ╚══════════════════════════════════════╝
    """
    print(banner)

if __name__ == '__main__':
    print_banner()
    print("[*] Server starting on http://127.0.0.1:5004")
    print("[*] Use Ctrl+C to stop the server\n")
    
    try:
        app.run(
            host='127.0.0.1',
            port=5004,
            debug=False,
            use_reloader=False,
            threaded=True
        )
    except KeyboardInterrupt:
        print("\n[!] Server stopped by user")
        sys.exit(0)
