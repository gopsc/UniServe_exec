# UniServe_exec.py - 去掉欢迎语，直接进入bash

from flask import Flask, request, jsonify
from flask_cors import CORS
import subprocess
import threading
import sys
import os
import pty
import select
import termios
import tty
import signal
import json
import logging
import uuid
import time
import websockets
from websockets.sync.server import serve

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 禁用Flask的访问日志输出
log = logging.getLogger('werkzeug')
log.setLevel(logging.ERROR)

app = Flask(__name__)
app.config['SECRET_KEY'] = 'your-secret-key-here'

# 启用 CORS
CORS(app, 
     supports_credentials=True,
     origins=['*'],
     methods=['GET', 'POST', 'PUT', 'DELETE', 'OPTIONS', 'HEAD'],
     allow_headers=['*'])

# 存储所有的终端会话
terminal_sessions = {}

class TerminalSession:
    """终端会话类，管理每个客户端的伪终端"""
    
    def __init__(self, session_id, websocket):
        self.session_id = session_id
        self.websocket = websocket
        self.process = None
        self.master_fd = None
        self.slave_fd = None
        self.running = False
        self.thread = None
        self.initialized = False
        self.old_tty_settings = None
        
    def start(self):
        """启动终端会话"""
        try:
            logger.info(f"Starting terminal session for {self.session_id}")
            
            # 创建伪终端
            self.master_fd, self.slave_fd = pty.openpty()
            
            # 设置终端属性 - 启用 echo
            self.old_tty_settings = termios.tcgetattr(self.slave_fd)
            
            # 获取当前终端设置
            tty_attrs = termios.tcgetattr(self.slave_fd)
            
            # 设置终端模式：启用 echo，启用 canonical 模式
            tty_attrs[1] = tty_attrs[1] | termios.ICRNL | termios.INLCR | termios.IGNCR
            tty_attrs[1] = tty_attrs[1] & ~termios.IXOFF & ~termios.IXON
            
            tty_attrs[2] = tty_attrs[2] | termios.OPOST
            
            tty_attrs[0] = tty_attrs[0] | termios.CREAD | termios.CS8
            tty_attrs[0] = tty_attrs[0] & ~(termios.CSIZE | termios.PARENB | termios.CSTOPB)
            tty_attrs[0] = tty_attrs[0] | termios.CS8
            
            tty_attrs[3] = tty_attrs[3] | termios.ECHO | termios.ICANON | termios.ISIG | termios.IEXTEN
            tty_attrs[3] = tty_attrs[3] & ~termios.ECHONL & ~termios.NOFLSH
            
            termios.tcsetattr(self.slave_fd, termios.TCSANOW, tty_attrs)
            
            # 设置环境变量
            env = os.environ.copy()
            env['TERM'] = 'xterm-256color'
            env['COLORTERM'] = 'truecolor'
            env['LANG'] = 'zh_CN.UTF-8'
            env['LC_ALL'] = 'zh_CN.UTF-8'
            env['HOME'] = os.environ.get('HOME', '/root')
            env['PS1'] = '\\[\\033[01;32m\\]\\u@\\h\\[\\033[00m\\]:\\[\\033[01;34m\\]\\w\\[\\033[00m\\]\\$ '
            
            # 启动子进程 - 使用 /bin/bash 交互模式
            self.process = subprocess.Popen(
                ['/bin/bash', '-i'],
                stdin=self.slave_fd,
                stdout=self.slave_fd,
                stderr=self.slave_fd,
                preexec_fn=os.setsid,
                shell=False,
                universal_newlines=False,
                bufsize=0,
                env=env
            )
            
            self.running = True
            self.initialized = True
            
            # 启动读取线程
            self.thread = threading.Thread(target=self._read_output, daemon=True)
            self.thread.start()
            
            logger.info(f"Terminal session started successfully for {self.session_id}")
            
            # 发送连接成功消息（不发送欢迎语）
            self._send_message({
                'type': 'connected',
                'session_id': self.session_id,
                'message': '终端连接成功'
            })
            
            return True
            
        except Exception as e:
            logger.error(f"Error starting terminal for {self.session_id}: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def _send_message(self, message):
        """发送消息到 WebSocket"""
        try:
            if isinstance(message, dict):
                message = json.dumps(message)
            self.websocket.send(message)
            return True
        except Exception as e:
            logger.error(f"Error sending message: {e}")
            return False
    
    def _read_output(self):
        """持续读取终端输出"""
        logger.info(f"Starting output reader for {self.session_id}")
        
        while self.running and self.process and self.process.poll() is None:
            try:
                rlist, _, _ = select.select([self.master_fd], [], [], 0.1)
                if rlist:
                    try:
                        data = os.read(self.master_fd, 4096)
                        if data:
                            try:
                                decoded_data = data.decode('utf-8', errors='replace')
                                self._send_message({
                                    'type': 'output',
                                    'session_id': self.session_id,
                                    'data': decoded_data
                                })
                            except Exception as emit_error:
                                logger.error(f"Error emitting output: {emit_error}")
                    except OSError as e:
                        if e.errno != 5:
                            logger.error(f"OS error reading from master: {e}")
                        break
            except Exception as e:
                logger.error(f"Error reading output: {e}")
                break
        
        self.running = False
        logger.info(f"Terminal session ended for {self.session_id}")
        
        self._send_message({
            'type': 'disconnected',
            'session_id': self.session_id,
            'message': '终端会话已结束'
        })
    
    def write(self, data):
        """向终端写入数据"""
        if self.master_fd and self.running:
            try:
                if isinstance(data, str):
                    data = data.encode('utf-8')
                os.write(self.master_fd, data)
                return True
            except Exception as e:
                logger.error(f"Error writing to terminal: {e}")
                return False
        return False
    
    def resize(self, rows, cols):
        """调整终端大小"""
        if self.master_fd:
            try:
                import fcntl
                import struct
                winsize = struct.pack('HHHH', rows, cols, 0, 0)
                fcntl.ioctl(self.master_fd, termios.TIOCSWINSZ, winsize)
                return True
            except Exception as e:
                logger.error(f"Error resizing terminal: {e}")
                return False
        return False
    
    def close(self):
        """关闭终端会话"""
        logger.info(f"Closing terminal session for {self.session_id}")
        self.running = False
        
        if self.process:
            try:
                self.process.terminate()
                self.process.wait(timeout=2)
            except:
                try:
                    self.process.kill()
                except:
                    pass
        
        if self.master_fd:
            try:
                os.close(self.master_fd)
            except:
                pass
        
        if self.slave_fd:
            try:
                os.close(self.slave_fd)
            except:
                pass
        
        self.initialized = False
        logger.info(f"Terminal closed for {self.session_id}")

# ========== WebSocket 处理 ==========
def handle_websocket(websocket):
    """处理 WebSocket 连接"""
    session_id = str(uuid.uuid4())[:8]
    logger.info(f"WebSocket client connected: {session_id}")
    
    terminal = None
    
    try:
        # 发送欢迎消息
        websocket.send(json.dumps({
            'type': 'info',
            'message': 'WebSocket connected',
            'session_id': session_id
        }))
        logger.info(f"Sent welcome message to {session_id}")
        
        # 创建终端会话
        terminal = TerminalSession(session_id, websocket)
        if not terminal.start():
            websocket.send(json.dumps({
                'type': 'error',
                'message': 'Failed to start terminal'
            }))
            return
        
        # 保存到全局
        terminal_sessions[session_id] = terminal
        
        # 持续接收消息
        while True:
            try:
                message = websocket.recv()
                if message is None:
                    logger.info(f"WebSocket client {session_id} disconnected")
                    break
                
                try:
                    msg = json.loads(message)
                    msg_type = msg.get('type')
                    
                    if msg_type == 'command':
                        command = msg.get('command', '')
                        if command is not None:
                            terminal.write(command)
                            
                    elif msg_type == 'resize':
                        cols = msg.get('cols', 80)
                        rows = msg.get('rows', 24)
                        terminal.resize(rows, cols)
                        
                    elif msg_type == 'ping':
                        websocket.send(json.dumps({
                            'type': 'pong',
                            'timestamp': msg.get('timestamp', time.time())
                        }))
                        
                    elif msg_type == 'disconnect':
                        logger.info(f"Client {session_id} requested disconnect")
                        break
                        
                except json.JSONDecodeError as e:
                    logger.error(f"JSON parse error: {e}")
                except Exception as e:
                    logger.error(f"Error processing message: {e}", exc_info=True)
                    
            except websockets.exceptions.ConnectionClosed:
                logger.info(f"WebSocket connection closed: {session_id}")
                break
            except Exception as e:
                logger.error(f"WebSocket receive error: {e}")
                break
                
    except Exception as e:
        logger.error(f"WebSocket handler error: {session_id}, {e}")
    finally:
        if terminal:
            terminal.close()
            if session_id in terminal_sessions:
                del terminal_sessions[session_id]
        
        logger.info(f"WebSocket client cleaned up: {session_id}")

def start_websocket_server():
    """启动 WebSocket 服务器 - 使用端口 5006"""
    try:
        with serve(handle_websocket, "127.0.0.1", 5006) as server:
            logger.info("WebSocket server started on port 5006")
            server.serve_forever()
    except Exception as e:
        logger.error(f"WebSocket server startup failed: {e}")

# ========== HTTP API 端点 ==========
@app.route('/exec', methods=['POST'])
def execute_command():
    """执行命令的端点（保留兼容性）"""
    try:
        if request.is_json:
            command = request.json.get('command', '')
        else:
            command = request.data.decode('utf-8').strip()
        
        if not command:
            return jsonify({
                'status': 'error',
                'message': 'No command provided'
            }), 400
        
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=30
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
    return jsonify({
        'status': 'ok',
        'active_terminals': len(terminal_sessions)
    }), 200

@app.route('/sessions', methods=['GET'])
def list_sessions():
    """列出所有活跃的终端会话"""
    return jsonify({
        'active_sessions': list(terminal_sessions.keys()),
        'count': len(terminal_sessions)
    })

@app.route('/api/auth/me', methods=['GET'])
def get_current_user():
    """获取当前用户信息（兼容网关）"""
    username = request.headers.get('X-Proxy-User', 'unknown')
    return jsonify({
        'username': username,
        'is_admin': True,
        'authenticated': True
    })

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
    ║     WebSocket Terminal Server       ║
    ║     Interactive Shell per Client    ║
    ╠══════════════════════════════════════╣
    ║  HTTP API:  http://127.0.0.1:5004   ║
    ║  WebSocket: ws://127.0.0.1:5006     ║
    ╠══════════════════════════════════════╣
    ║  WebSocket Messages:                ║
    ║  command   - Send command           ║
    ║  resize    - Resize terminal        ║
    ║  ping      - Heartbeat              ║
    ║  disconnect - Close session         ║
    ╠══════════════════════════════════════╣
    ║  HTTP Endpoints:                    ║
    ║  POST /exec   - Execute command     ║
    ║  GET  /health - Health check        ║
    ║  GET  /sessions - List sessions     ║
    ╚══════════════════════════════════════╝
    """
    print(banner)

if __name__ == '__main__':
    print_banner()
    print("[*] HTTP Server starting on http://127.0.0.1:5004")
    print("[*] WebSocket Server starting on ws://127.0.0.1:5006")
    print("[*] Use Ctrl+C to stop the server\n")
    
    # 启动 WebSocket 服务器线程（端口 5006）
    ws_thread = threading.Thread(target=start_websocket_server, daemon=True)
    ws_thread.start()
    
    # 启动 HTTP 服务器（端口 5004）
    try:
        app.run(
            host='127.0.0.1',
            port=5004,
            debug=False,
            threaded=True,
            use_reloader=False
        )
    except KeyboardInterrupt:
        print("\n[!] Server stopped by user")
        for session_id in list(terminal_sessions.keys()):
            terminal_sessions[session_id].close()
        sys.exit(0)