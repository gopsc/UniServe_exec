# UniServe_exec

WebSocket 终端服务器，为每个客户端提供交互式 Shell。

## 功能特性

- **交互式终端**：每个客户端分配独立的 bash 终端会话
- **WebSocket 通信**：支持命令发送、终端 resize、心跳检测
- **HTTP API**：提供命令执行、健康检查、会话管理接口
- **CORS 支持**：跨域访问配置完整

## 服务端口

- HTTP API: `http://127.0.0.1:5004`
- WebSocket: `ws://127.0.0.1:5006`

## WebSocket 消息协议

| 消息类型 | 说明 |
|---------|------|
| `command` | 向终端发送命令 |
| `resize` | 调整终端大小 (cols, rows) |
| `ping` | 心跳检测 |
| `disconnect` | 关闭会话 |

接收消息类型：
- `connected` - 连接成功
- `output` - 终端输出
- `disconnected` - 会话结束

## HTTP API

| 端点 | 方法 | 说明 |
|------|------|------|
| `/exec` | POST | 执行 shell 命令 |
| `/health` | GET | 健康检查 |
| `/sessions` | GET | 列出活跃会话 |
| `/api/auth/me` | GET | 获取当前用户信息 |

## 安装依赖

```bash
pip install flask flask-cors websockets
```

## 运行

```bash
python main.py
```

