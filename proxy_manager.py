"""
proxy_manager.py - 代理管理器

解析Clash配置，管理代理节点，支持随机选择和故障转移
CleanRL设计: 单一职责，显式状态

使用方法:
    from proxy_manager import get_proxy_manager
    
    proxy_manager = get_proxy_manager()
    proxy_url = proxy_manager.get_proxy()  # http://127.0.0.1:7890
    proxy_dict = proxy_manager.get_proxy_dict()  # {'http': ..., 'https': ...}

Author: AI Assistant
Date: 2024
"""

import yaml
import time
import random
import socket
from pathlib import Path
from typing import List, Optional, Dict, Any
from dataclasses import dataclass, field
from concurrent.futures import ThreadPoolExecutor, as_completed

from loguru import logger


# ============================================================================
# 配置
# ============================================================================

@dataclass
class ProxySettings:
    """代理设置"""
    # Clash配置
    clash_config_path: str = "config.yaml"
    clash_port: int = 7890
    use_local_clash: bool = True
    
    # 测试配置
    proxy_test_timeout: float = 5.0
    proxy_test_url: str = "http://www.gstatic.com/generate_204"
    
    # 并发配置
    concurrency: int = 10
    request_timeout: float = 30.0
    
    # User-Agent
    user_agent: str = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"


# 默认设置
settings = ProxySettings()


# ============================================================================
# 代理节点
# ============================================================================

@dataclass
class ProxyNode:
    """代理节点"""
    name: str
    server: str
    port: int
    type: str
    password: str = ""
    cipher: str = ""
    uuid: str = ""
    alterId: int = 0
    latency: float = float('inf')
    fail_count: int = 0
    last_test_time: float = 0
    
    def to_requests_proxy(self, use_local_clash: bool = True, 
                          local_port: int = 7890) -> Dict[str, str]:
        """转换为requests/aiohttp代理格式"""
        if use_local_clash:
            proxy_url = f"http://127.0.0.1:{local_port}"
            return {"http": proxy_url, "https": proxy_url}
        
        if self.type in ["http", "https"]:
            proxy_url = f"{self.type}://{self.server}:{self.port}"
        elif self.type == "socks5":
            proxy_url = f"socks5://{self.server}:{self.port}"
        else:
            raise ValueError(f"协议 '{self.type}' 不支持直接连接")
        
        return {"http": proxy_url, "https": proxy_url}
    
    def __repr__(self):
        return f"<ProxyNode {self.name} - {self.server}:{self.port} ({self.latency:.0f}ms)>"


# ============================================================================
# 代理管理器
# ============================================================================

class ProxyManager:
    """
    代理管理器
    
    功能:
    - 解析Clash配置文件
    - 管理代理节点列表
    - 测试节点延迟
    - 选择最快/随机节点
    - 提供代理URL/字典
    """
    
    def __init__(
        self,
        config_path: str = None,
        use_local_clash: bool = True,
        local_port: int = 7890,
    ):
        """
        初始化代理管理器
        
        Args:
            config_path: Clash配置文件路径
            use_local_clash: 是否使用本地Clash代理
            local_port: Clash本地代理端口
        """
        self.config_path = Path(config_path or settings.clash_config_path).expanduser()
        self.use_local_clash = use_local_clash
        self.local_port = local_port
        self.nodes: List[ProxyNode] = []
        self.current_node: Optional[ProxyNode] = None
        
        # 加载配置
        if self.config_path.exists():
            self._load_config()
        else:
            logger.warning(f"⚠️ Clash配置不存在: {self.config_path}")
            logger.info(f"📡 将使用本地代理: http://127.0.0.1:{local_port}")
    
    def _load_config(self):
        """加载Clash配置文件"""
        try:
            logger.info(f"📂 加载代理配置: {self.config_path}")
            with open(self.config_path, 'r', encoding='utf-8') as f:
                config = yaml.safe_load(f)
            
            # 解析代理节点
            proxies = config.get('proxies', [])
            for proxy in proxies:
                node = self._parse_proxy(proxy)
                if node:
                    self.nodes.append(node)
            
            # 读取端口配置
            if 'mixed-port' in config:
                self.local_port = config['mixed-port']
            elif 'port' in config:
                self.local_port = config['port']
            
            logger.info(f"✅ 加载了 {len(self.nodes)} 个代理节点")
            logger.info(f"📌 Clash端口: {self.local_port}")
            
        except Exception as e:
            logger.error(f"❌ 加载配置失败: {e}")
    
    def _parse_proxy(self, proxy: Dict) -> Optional[ProxyNode]:
        """解析单个代理配置"""
        try:
            proxy_type = proxy.get('type', '').lower()
            
            if proxy_type == "ss":
                return ProxyNode(
                    name=proxy['name'],
                    server=proxy['server'],
                    port=proxy['port'],
                    type=proxy_type,
                    password=proxy.get('password', ''),
                    cipher=proxy.get('cipher', '')
                )
            elif proxy_type == "vmess":
                return ProxyNode(
                    name=proxy['name'],
                    server=proxy['server'],
                    port=proxy['port'],
                    type=proxy_type,
                    uuid=proxy.get('uuid', ''),
                    alterId=proxy.get('alterId', 0)
                )
            elif proxy_type in ["http", "https", "socks5", "trojan"]:
                return ProxyNode(
                    name=proxy['name'],
                    server=proxy['server'],
                    port=proxy['port'],
                    type=proxy_type
                )
            else:
                return None
                
        except Exception as e:
            logger.debug(f"解析代理失败: {e}")
            return None
    
    def test_node(self, node: ProxyNode) -> float:
        """测试单个节点延迟（TCP连接测试）"""
        try:
            start = time.time()
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(settings.proxy_test_timeout)
            sock.connect((node.server, node.port))
            latency = (time.time() - start) * 1000
            sock.close()
            
            node.latency = latency
            node.last_test_time = time.time()
            return latency
            
        except socket.timeout:
            node.latency = float('inf')
            node.fail_count += 1
            return float('inf')
        except Exception:
            node.latency = float('inf')
            node.fail_count += 1
            return float('inf')
    
    def test_all_nodes(self, max_workers: int = 10):
        """测试所有节点延迟"""
        if not self.nodes:
            logger.warning("⚠️ 没有节点可测试")
            return
        
        logger.info(f"🔍 测试 {len(self.nodes)} 个节点...")
        
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(self.test_node, node): node for node in self.nodes}
            for future in as_completed(futures):
                try:
                    future.result()
                except Exception:
                    pass
        
        # 按延迟排序
        self.nodes.sort(key=lambda n: n.latency)
        
        # 统计
        available = [n for n in self.nodes if n.latency < float('inf')]
        logger.info(f"✅ 可用节点: {len(available)}/{len(self.nodes)}")
        
        # 显示前5个
        for i, node in enumerate(available[:5], 1):
            logger.info(f"  {i}. {node.name:30s} {node.latency:6.0f}ms")
    
    def select_fastest(self, region: Optional[str] = None) -> Optional[ProxyNode]:
        """选择最快的节点"""
        nodes = self.nodes
        
        if region:
            nodes = [n for n in nodes if region.lower() in n.name.lower()]
            if not nodes:
                nodes = self.nodes
        
        available = [n for n in nodes if n.latency < float('inf') and n.fail_count < 5]
        
        if not available:
            return None
        
        fastest = min(available, key=lambda n: n.latency)
        self.current_node = fastest
        logger.info(f"🚀 选择节点: {fastest.name} ({fastest.latency:.0f}ms)")
        return fastest
    
    def select_random(self, max_latency: float = 500) -> Optional[ProxyNode]:
        """随机选择一个节点"""
        available = [n for n in self.nodes if n.latency < max_latency and n.fail_count < 5]
        
        if not available:
            # 放宽条件
            available = [n for n in self.nodes if n.fail_count < 10]
        
        if not available:
            return None
        
        node = random.choice(available)
        self.current_node = node
        logger.debug(f"🎲 随机选择: {node.name}")
        return node
    
    def get_proxy(self) -> str:
        """
        获取代理URL
        
        Returns:
            代理URL字符串, 如 "http://127.0.0.1:7890"
        """
        return f"http://127.0.0.1:{self.local_port}"
    
    def get_proxy_dict(self) -> Dict[str, str]:
        """
        获取代理字典 (用于requests)
        
        Returns:
            代理字典, 如 {"http": "...", "https": "..."}
        """
        proxy_url = f"http://127.0.0.1:{self.local_port}"
        return {"http": proxy_url, "https": proxy_url}
    
    def mark_failed(self):
        """标记当前节点失败"""
        if self.current_node:
            self.current_node.fail_count += 1
            logger.warning(f"⚠️ 节点失败: {self.current_node.name}")
    
    def get_node_by_region(self, region: str) -> Optional[ProxyNode]:
        """
        按地区获取节点
        
        Args:
            region: 地区关键词, 如 "香港", "日本", "美国"
            
        Returns:
            ProxyNode或None
        """
        matching = [n for n in self.nodes if region in n.name]
        if matching:
            # 选择延迟最低的
            available = [n for n in matching if n.latency < float('inf')]
            if available:
                return min(available, key=lambda n: n.latency)
            return matching[0]
        return None
    
    def get_available_regions(self) -> List[str]:
        """获取可用地区列表"""
        regions = set()
        for node in self.nodes:
            # 提取地区标识
            if '香港' in node.name:
                regions.add('香港')
            elif '日本' in node.name:
                regions.add('日本')
            elif '美国' in node.name:
                regions.add('美国')
            elif '台湾' in node.name:
                regions.add('台湾')
            elif '韩国' in node.name:
                regions.add('韩国')
            elif '新加坡' in node.name:
                regions.add('新加坡')
        return sorted(regions)


# ============================================================================
# 全局实例
# ============================================================================

_proxy_manager: Optional[ProxyManager] = None


def get_proxy_manager(
    config_path: str = None,
    local_port: int = 7890
) -> ProxyManager:
    """
    获取全局代理管理器实例 (单例模式)
    
    Args:
        config_path: Clash配置路径 (可选)
        local_port: 本地代理端口
        
    Returns:
        ProxyManager实例
    """
    global _proxy_manager
    if _proxy_manager is None:
        _proxy_manager = ProxyManager(
            config_path=config_path,
            use_local_clash=True,
            local_port=local_port,
        )
    return _proxy_manager


def reset_proxy_manager():
    """重置全局代理管理器"""
    global _proxy_manager
    _proxy_manager = None


# ============================================================================
# 便捷函数
# ============================================================================

def get_proxy_url(port: int = 7890) -> str:
    """
    获取代理URL (便捷函数)
    
    Args:
        port: 代理端口
        
    Returns:
        代理URL
    """
    return f"http://127.0.0.1:{port}"


def get_proxy_dict(port: int = 7890) -> Dict[str, str]:
    """
    获取代理字典 (便捷函数)
    
    Args:
        port: 代理端口
        
    Returns:
        代理字典
    """
    url = f"http://127.0.0.1:{port}"
    return {"http": url, "https": url}


# ============================================================================
# 测试
# ============================================================================

if __name__ == "__main__":
    import sys
    
    # 配置日志
    logger.remove()
    logger.add(sys.stderr, level="DEBUG", format="{time:HH:mm:ss} | {level:<8} | {message}")
    
    print("=" * 60)
    print("代理管理器测试")
    print("=" * 60)
    
    # 创建管理器
    manager = ProxyManager()
    
    # 测试节点
    if manager.nodes:
        print(f"\n加载了 {len(manager.nodes)} 个节点")
        
        # 显示可用地区
        regions = manager.get_available_regions()
        print(f"可用地区: {regions}")
        
        # 测试节点延迟
        print("\n测试节点延迟...")
        manager.test_all_nodes(max_workers=5)
        
        # 选择节点
        node = manager.select_fastest()
        if node:
            print(f"\n最快节点: {node}")
        
        node = manager.select_fastest(region="香港")
        if node:
            print(f"香港最快: {node}")
        
        node = manager.select_random()
        if node:
            print(f"随机节点: {node}")
    
    # 代理配置
    print(f"\n代理URL: {manager.get_proxy()}")
    print(f"代理字典: {manager.get_proxy_dict()}")
    
    # 测试代理连接
    print("\n测试代理连接...")
    try:
        import requests
        
        proxy_url = manager.get_proxy()
        proxies = {"http": proxy_url, "https": proxy_url}
        
        response = requests.get(
            "https://www.google.com",
            proxies=proxies,
            timeout=10
        )
        
        if response.status_code == 200:
            print(f"✅ 代理测试成功! 状态码: {response.status_code}")
        else:
            print(f"⚠️ 代理返回: {response.status_code}")
            
    except Exception as e:
        print(f"❌ 代理测试失败: {e}")
    
    print("\n" + "=" * 60)
    print("测试完成!")
    print("=" * 60)