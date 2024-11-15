import asyncio
import json
import random
import ssl
import time
import uuid
import re
from websockets_proxy import Proxy, proxy_connect
from fake_useragent import UserAgent
from loguru import logger
from enum import Enum
from datetime import datetime
from typing import Optional
import socks
import websockets
from urllib.parse import urlparse

# 代理池和其他常量配置
user_agent = UserAgent()
random_user_agent = user_agent.random

nstProxyAppId = "F680F8381EB0D52B"

# 连接状态管理
class Status(Enum):
    disconnect = 0
    connecting = 1
    connected = 2

# 日志记录类
class AsyncGrassWs:
    def __init__(self, user_id, proxy_url=None):
        self.user_id = user_id
        self.user_agent = random_user_agent
        self.device_id = str(uuid.uuid3(uuid.NAMESPACE_DNS, proxy_url or ""))
        self.proxy_url = proxy_url
        self.ws: Optional[websockets.WebSocketCommonProtocol] = None
        self.status: Status = Status.disconnect
        self._stop = False
        self._stopped = False
        self._ping_stopped = False
        self.server_hostname = "proxy.wynd.network"
        self.server_port = 4444
        self.server_url = f"wss://{self.server_hostname}:{self.server_port}/"
        self.proxy_timeout = 60
        self.logs = []

        # 配置日志输出
        logger.remove()  # 移除默认的控制台输出处理器
        logger.add(sys.stdout, level="INFO")  # 添加新的控制台输出处理器

    def log(self, level, message):
        logger.log(logger.level(level).name, message)
        self.logs.append((datetime.now().strftime("%Y-%m-%d %H:%M:%S"), message))
        if len(self.logs) >= 100:
            self.logs = self.logs[-100:]

    async def send_ping(self):
        await asyncio.sleep(5)
        while not self._stop:
            try:
                send_message = json.dumps(
                    {"id": str(uuid.uuid4()), "version": "1.0.0", "action": "PING", "data": {}})
                if self.ws:
                    self.log("DEBUG", f'[发送消息] [{self.user_id}] [{self.proxy_url}] [{send_message}]')
                    await self.ws.send(send_message)
            except Exception as e:
                self.log("DEBUG", f'[PING Error] {e}')
            for i in range(20):
                if self._stop:
                    break
                await asyncio.sleep(1)
            self._ping_stopped = True

    def auth_response(self, message):
        return {
            "id": message["id"],
            "origin_action": "AUTH",
            "result": {
                "browser_id": self.device_id,
                "user_id": self.user_id,
                "user_agent": self.user_agent,
                "timestamp": int(time.time()),
                "device_type": "desktop",
                "version": "4.28.1"
            }
        }

    async def connect_to_wss(self):
        self.log("INFO", f'[启动] [{self.user_id}] [{self.proxy_url}]')
        await asyncio.sleep(1)

        custom_headers = {"User-Agent": self.user_agent}
        ssl_context = ssl.create_default_context()
        ssl_context.check_hostname = False
        ssl_context.verify_mode = ssl.CERT_NONE

        uri_list = ["wss://proxy.wynd.network:4444/", "wss://proxy.wynd.network:4650/"]
        uri = random.choice(uri_list)

        server_hostname = "proxy.wynd.network"
        proxy = Proxy.from_url(self.proxy_url)

        # 连接 WebSocket
        try:
            async with proxy_connect(uri, proxy=proxy, ssl=ssl_context, server_hostname=server_hostname,
                                     extra_headers=custom_headers) as websocket:
                self.ws = websocket
                self.status = Status.connected
                await asyncio.create_task(self.send_ping())

                while True:
                    response = await websocket.recv()
                    message = json.loads(response)
                    self.log("INFO", f"收到消息: {message}")

                    if message.get("action") == "AUTH":
                        auth_response = self.auth_response(message)
                        await websocket.send(json.dumps(auth_response))
                        self.log("INFO", f"已发送认证响应: {auth_response}")
                        break  # 认证完成后退出连接循环

        except Exception as e:
            self.log("ERROR", f"连接失败: {e}，正在重试...")
            # 在连接失败时进行重试
            await asyncio.sleep(5)
            await self.connect_to_wss()  # 递归调用重试连接

async def load_proxies_from_file(file_path):
    """
    读取代理文件，并返回每个用户的 ID 和代理地址
    格式：
    user_id==proxy_url
    """
    with open(file_path, 'r', encoding='utf-8') as f:
        lines = f.readlines()
    
    user_proxy_pairs = []
    for line in lines:
        line = line.strip()
        if line:
            if "==" in line:
                user_id, proxy_url = line.split('==')
                user_proxy_pairs.append((user_id, proxy_url))
            else:
                user_id = line
                user_proxy_pairs.append((user_id, None))  # 如果没有代理，代理地址为 None
    return user_proxy_pairs

async def main():
    proxies_file = '/mnt/data/proxies.txt'  # 您的代理文件路径

    # 加载所有用户的ID和代理
    user_proxy_pairs = await load_proxies_from_file(proxies_file)

    # 为每个用户创建连接并运行
    tasks = []
    for user_id, proxy_url in user_proxy_pairs:
        ws = AsyncGrassWs(user_id, proxy_url)
        tasks.append(ws.connect_to_wss())

    # 并发运行所有用户的连接
    await asyncio.gather(*tasks)

# 运行
if __name__ == "__main__":
    asyncio.run(main())
