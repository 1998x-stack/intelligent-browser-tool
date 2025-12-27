#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
URL队列管理器 - 基于优先级的URL队列系统

设计理念 (CleanRL Philosophy):
- 单文件自包含: 完整的优先级队列实现
- 透明的处理流程: 清晰的入队/出队逻辑
- 最小化抽象: 直接使用heapq实现优先级队列
- 便于调试: 详细的队列状态日志

功能特性:
- 优先级队列 (1=高, 2=中, 3=低)
- URL去重 (基于规范化URL)
- 深度追踪 (控制爬取深度)
- 域名过滤 (白名单/黑名单)
- 队列持久化 (支持保存/恢复)
"""

import sys
import traceback
import heapq
import json
import hashlib
from datetime import datetime
from typing import Optional, List, Dict, Set, Tuple, Any
from dataclasses import dataclass, field, asdict
from urllib.parse import urlparse, urljoin, urldefrag
from pathlib import Path
from enum import IntEnum

from loguru import logger

from config import Config, URLPriority


# ============================================================================
# 错误处理工具
# ============================================================================

def get_err_message() -> str:
    """获取详细的异常信息"""
    exc_type, exc_value, exc_traceback = sys.exc_info()
    error_message = repr(
        traceback.format_exception(exc_type, exc_value, exc_traceback)
    )
    return error_message


# ============================================================================
# 数据结构
# ============================================================================

@dataclass(order=True)
class QueueItem:
    """
    队列项 - 可排序的URL项
    
    优先级排序: priority -> depth -> timestamp
    """
    priority: int
    depth: int
    timestamp: float = field(compare=True)
    url: str = field(compare=False)
    parent_url: str = field(compare=False, default="")
    context: Dict[str, Any] = field(compare=False, default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "priority": self.priority,
            "depth": self.depth,
            "timestamp": self.timestamp,
            "url": self.url,
            "parent_url": self.parent_url,
            "context": self.context
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'QueueItem':
        """从字典创建"""
        return cls(
            priority=data.get("priority", URLPriority.MEDIUM),
            depth=data.get("depth", 0),
            timestamp=data.get("timestamp", datetime.now().timestamp()),
            url=data.get("url", ""),
            parent_url=data.get("parent_url", ""),
            context=data.get("context", {})
        )


@dataclass
class QueueStats:
    """队列统计信息"""
    total_added: int = 0
    total_processed: int = 0
    duplicates_skipped: int = 0
    filtered_out: int = 0
    current_size: int = 0
    priority_counts: Dict[int, int] = field(default_factory=dict)
    depth_counts: Dict[int, int] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "total_added": self.total_added,
            "total_processed": self.total_processed,
            "duplicates_skipped": self.duplicates_skipped,
            "filtered_out": self.filtered_out,
            "current_size": self.current_size,
            "priority_counts": self.priority_counts,
            "depth_counts": self.depth_counts
        }


# ============================================================================
# URL规范化
# ============================================================================

class URLNormalizer:
    """
    URL规范化器 - 确保URL的一致性
    
    处理:
    - 移除fragment (#后的部分)
    - 规范化路径 (移除尾部斜杠)
    - 小写域名
    - 移除默认端口
    """
    
    # 默认端口映射
    DEFAULT_PORTS = {
        "http": 80,
        "https": 443
    }
    
    @classmethod
    def normalize(cls, url: str, base_url: str = "") -> str:
        """
        规范化URL
        
        Args:
            url: 待规范化的URL
            base_url: 基础URL (用于处理相对路径)
            
        Returns:
            规范化后的URL
        """
        if not url:
            return ""
        
        try:
            # 处理相对URL
            if base_url and not url.startswith(("http://", "https://", "//")):
                url = urljoin(base_url, url)
            
            # 处理协议相对URL
            if url.startswith("//"):
                url = "https:" + url
            
            # 移除fragment
            url, _ = urldefrag(url)
            
            # 解析URL
            parsed = urlparse(url)
            
            # 小写协议和域名
            scheme = parsed.scheme.lower()
            netloc = parsed.netloc.lower()
            
            # 移除默认端口
            if ":" in netloc:
                host, port_str = netloc.rsplit(":", 1)
                try:
                    port = int(port_str)
                    if cls.DEFAULT_PORTS.get(scheme) == port:
                        netloc = host
                except ValueError:
                    pass
            
            # 规范化路径
            path = parsed.path
            if path != "/" and path.endswith("/"):
                path = path.rstrip("/")
            if not path:
                path = "/"
            
            # 重构URL
            normalized = f"{scheme}://{netloc}{path}"
            if parsed.query:
                normalized += f"?{parsed.query}"
            
            return normalized
            
        except Exception as e:
            logger.debug(f"URL规范化失败 ({url}): {e}")
            return url
    
    @classmethod
    def get_url_hash(cls, url: str) -> str:
        """
        获取URL的哈希值 (用于去重)
        
        Args:
            url: URL
            
        Returns:
            MD5哈希值
        """
        normalized = cls.normalize(url)
        return hashlib.md5(normalized.encode()).hexdigest()
    
    @classmethod
    def extract_domain(cls, url: str) -> str:
        """
        提取域名
        
        Args:
            url: URL
            
        Returns:
            域名
        """
        try:
            parsed = urlparse(url)
            return parsed.netloc.lower()
        except Exception:
            return ""
    
    @classmethod
    def is_same_domain(cls, url1: str, url2: str) -> bool:
        """
        检查两个URL是否属于同一域名
        
        Args:
            url1: 第一个URL
            url2: 第二个URL
            
        Returns:
            是否同域名
        """
        return cls.extract_domain(url1) == cls.extract_domain(url2)


# ============================================================================
# URL过滤器
# ============================================================================

class URLFilter:
    """
    URL过滤器 - 基于配置的URL过滤
    
    支持:
    - 域名白名单
    - 排除模式
    - 文件类型过滤
    """
    
    # 默认排除的文件扩展名
    DEFAULT_EXCLUDE_EXTENSIONS = {
        ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
        ".zip", ".rar", ".tar", ".gz", ".7z",
        ".jpg", ".jpeg", ".png", ".gif", ".bmp", ".svg", ".ico", ".webp",
        ".mp3", ".mp4", ".avi", ".mov", ".wmv", ".flv", ".wav",
        ".exe", ".msi", ".dmg", ".apk", ".deb", ".rpm"
    }
    
    def __init__(self, config: Config):
        """
        初始化过滤器
        
        Args:
            config: 配置对象
        """
        self.config = config
        self.allowed_domains = set(config.browser.allowed_domains or [])
        self.exclude_patterns = set(config.browser.exclude_patterns or [])
        self.exclude_extensions = self.DEFAULT_EXCLUDE_EXTENSIONS.copy()
        
        logger.debug(f"URL过滤器初始化 (白名单域名: {len(self.allowed_domains)}, "
                    f"排除模式: {len(self.exclude_patterns)})")
    
    def is_allowed(self, url: str) -> Tuple[bool, str]:
        """
        检查URL是否允许爬取
        
        Args:
            url: 待检查的URL
            
        Returns:
            (是否允许, 原因)
        """
        if not url:
            return False, "空URL"
        
        try:
            parsed = urlparse(url)
            
            # 检查协议
            if parsed.scheme not in ("http", "https"):
                return False, f"不支持的协议: {parsed.scheme}"
            
            # 检查域名白名单
            if self.allowed_domains:
                domain = parsed.netloc.lower()
                domain_match = any(
                    allowed in domain 
                    for allowed in self.allowed_domains
                )
                if not domain_match:
                    return False, f"域名不在白名单: {domain}"
            
            # 检查排除模式
            for pattern in self.exclude_patterns:
                if pattern in url:
                    return False, f"匹配排除模式: {pattern}"
            
            # 检查文件扩展名
            path_lower = parsed.path.lower()
            for ext in self.exclude_extensions:
                if path_lower.endswith(ext):
                    return False, f"排除的文件类型: {ext}"
            
            return True, "允许"
            
        except Exception as e:
            return False, f"URL解析失败: {e}"
    
    def add_exclude_pattern(self, pattern: str):
        """添加排除模式"""
        self.exclude_patterns.add(pattern)
    
    def add_allowed_domain(self, domain: str):
        """添加白名单域名"""
        self.allowed_domains.add(domain.lower())


# ============================================================================
# URL队列管理器
# ============================================================================

class URLQueue:
    """
    URL队列管理器 - 基于优先级的URL管理
    
    特性:
    - 优先级队列: 高优先级URL优先处理
    - URL去重: 避免重复爬取
    - 深度控制: 限制爬取深度
    - 状态追踪: 记录已访问、待处理URL
    - 持久化: 支持队列状态保存和恢复
    
    使用示例:
        queue = URLQueue(config)
        queue.add("https://example.com", priority=1, depth=0)
        
        while queue.has_next():
            item = queue.get_next()
            # 处理URL...
            queue.mark_processed(item.url)
    """
    
    def __init__(self, config: Config):
        """
        初始化队列
        
        Args:
            config: 配置对象
        """
        self.config = config
        self.max_depth = config.crawl.max_depth
        
        # 核心数据结构
        self._heap: List[QueueItem] = []  # 优先级队列
        self._seen_urls: Set[str] = set()  # 已见过的URL (规范化后的哈希)
        self._processed_urls: Set[str] = set()  # 已处理的URL
        self._failed_urls: Dict[str, int] = {}  # 失败的URL及重试次数
        
        # 过滤器和规范化器
        self._normalizer = URLNormalizer()
        self._filter = URLFilter(config)
        
        # 统计信息
        self._stats = QueueStats()
        
        logger.info(f"URL队列初始化完成 (最大深度: {self.max_depth})")
    
    # ========================================================================
    # 核心队列操作
    # ========================================================================
    
    def add(
        self,
        url: str,
        priority: int = URLPriority.MEDIUM,
        depth: int = 0,
        parent_url: str = "",
        context: Optional[Dict[str, Any]] = None
    ) -> bool:
        """
        添加URL到队列
        
        Args:
            url: 要添加的URL
            priority: 优先级 (1=高, 2=中, 3=低)
            depth: 爬取深度
            parent_url: 父页面URL
            context: 额外上下文信息
            
        Returns:
            是否成功添加 (False表示重复或被过滤)
        """
        # 规范化URL
        normalized_url = self._normalizer.normalize(url, parent_url)
        if not normalized_url:
            logger.debug(f"无效URL: {url}")
            return False
        
        # 检查深度限制
        if depth > self.max_depth:
            logger.debug(f"超出深度限制 ({depth} > {self.max_depth}): {normalized_url}")
            self._stats.filtered_out += 1
            return False
        
        # 检查URL过滤
        allowed, reason = self._filter.is_allowed(normalized_url)
        if not allowed:
            logger.debug(f"URL被过滤 ({reason}): {normalized_url}")
            self._stats.filtered_out += 1
            return False
        
        # 检查重复
        url_hash = self._normalizer.get_url_hash(normalized_url)
        if url_hash in self._seen_urls:
            logger.debug(f"重复URL: {normalized_url}")
            self._stats.duplicates_skipped += 1
            return False
        
        # 创建队列项
        item = QueueItem(
            priority=priority,
            depth=depth,
            timestamp=datetime.now().timestamp(),
            url=normalized_url,
            parent_url=parent_url,
            context=context or {}
        )
        
        # 加入队列
        heapq.heappush(self._heap, item)
        self._seen_urls.add(url_hash)
        
        # 更新统计
        self._stats.total_added += 1
        self._stats.current_size = len(self._heap)
        self._stats.priority_counts[priority] = \
            self._stats.priority_counts.get(priority, 0) + 1
        self._stats.depth_counts[depth] = \
            self._stats.depth_counts.get(depth, 0) + 1
        
        logger.debug(f"URL入队 [P{priority}|D{depth}]: {normalized_url}")
        
        return True
    
    def add_batch(
        self,
        urls: List[Dict[str, Any]],
        default_priority: int = URLPriority.MEDIUM,
        default_depth: int = 0,
        parent_url: str = ""
    ) -> int:
        """
        批量添加URL
        
        Args:
            urls: URL列表，每项可以是字符串或包含url/priority/context的字典
            default_priority: 默认优先级
            default_depth: 默认深度
            parent_url: 父页面URL
            
        Returns:
            成功添加的数量
        """
        added_count = 0
        
        for url_item in urls:
            if isinstance(url_item, str):
                url = url_item
                priority = default_priority
                context = {}
            elif isinstance(url_item, dict):
                url = url_item.get("url", "")
                priority = url_item.get("priority", default_priority)
                context = url_item.get("context", {})
            else:
                continue
            
            if self.add(
                url=url,
                priority=priority,
                depth=default_depth,
                parent_url=parent_url,
                context=context
            ):
                added_count += 1
        
        logger.info(f"批量添加URL: {added_count}/{len(urls)} 成功")
        return added_count
    
    def get_next(self) -> Optional[QueueItem]:
        """
        获取下一个待处理的URL
        
        Returns:
            队列项，队列为空时返回None
        """
        if not self._heap:
            return None
        
        item = heapq.heappop(self._heap)
        self._stats.current_size = len(self._heap)
        
        logger.debug(f"URL出队 [P{item.priority}|D{item.depth}]: {item.url}")
        
        return item
    
    def peek(self) -> Optional[QueueItem]:
        """
        查看下一个待处理的URL (不移除)
        
        Returns:
            队列项，队列为空时返回None
        """
        if not self._heap:
            return None
        return self._heap[0]
    
    def has_next(self) -> bool:
        """检查队列是否还有待处理的URL"""
        return len(self._heap) > 0
    
    def size(self) -> int:
        """获取当前队列大小"""
        return len(self._heap)
    
    # ========================================================================
    # 状态管理
    # ========================================================================
    
    def mark_processed(self, url: str, success: bool = True):
        """
        标记URL已处理
        
        Args:
            url: 已处理的URL
            success: 是否成功处理
        """
        normalized = self._normalizer.normalize(url)
        url_hash = self._normalizer.get_url_hash(normalized)
        
        if success:
            self._processed_urls.add(url_hash)
            self._stats.total_processed += 1
            logger.debug(f"URL处理完成: {normalized}")
        else:
            # 记录失败，可能需要重试
            retry_count = self._failed_urls.get(url_hash, 0)
            self._failed_urls[url_hash] = retry_count + 1
            logger.debug(f"URL处理失败 (重试次数: {retry_count + 1}): {normalized}")
    
    def is_processed(self, url: str) -> bool:
        """检查URL是否已处理"""
        normalized = self._normalizer.normalize(url)
        url_hash = self._normalizer.get_url_hash(normalized)
        return url_hash in self._processed_urls
    
    def is_seen(self, url: str) -> bool:
        """检查URL是否已见过 (包括待处理的)"""
        normalized = self._normalizer.normalize(url)
        url_hash = self._normalizer.get_url_hash(normalized)
        return url_hash in self._seen_urls
    
    def get_failed_urls(self) -> List[Tuple[str, int]]:
        """获取失败的URL列表及重试次数"""
        return list(self._failed_urls.items())
    
    def clear(self):
        """清空队列"""
        self._heap.clear()
        self._seen_urls.clear()
        self._processed_urls.clear()
        self._failed_urls.clear()
        self._stats = QueueStats()
        logger.info("队列已清空")
    
    # ========================================================================
    # 统计信息
    # ========================================================================
    
    def get_stats(self) -> QueueStats:
        """获取队列统计信息"""
        self._stats.current_size = len(self._heap)
        return self._stats
    
    def get_progress(self) -> Tuple[int, int, float]:
        """
        获取处理进度
        
        Returns:
            (已处理数, 总数, 进度百分比)
        """
        processed = self._stats.total_processed
        total = self._stats.total_added
        progress = (processed / total * 100) if total > 0 else 0
        return processed, total, progress
    
    # ========================================================================
    # 持久化
    # ========================================================================
    
    def save_state(self, filepath: Path) -> bool:
        """
        保存队列状态到文件
        
        Args:
            filepath: 保存路径
            
        Returns:
            是否成功
        """
        try:
            state = {
                "heap": [item.to_dict() for item in self._heap],
                "seen_urls": list(self._seen_urls),
                "processed_urls": list(self._processed_urls),
                "failed_urls": self._failed_urls,
                "stats": self._stats.to_dict(),
                "saved_at": datetime.now().isoformat()
            }
            
            filepath = Path(filepath)
            filepath.parent.mkdir(parents=True, exist_ok=True)
            
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(state, f, ensure_ascii=False, indent=2)
            
            logger.info(f"队列状态已保存: {filepath}")
            return True
            
        except Exception as e:
            logger.error(f"保存队列状态失败: {e}")
            logger.debug(get_err_message())
            return False
    
    def load_state(self, filepath: Path) -> bool:
        """
        从文件恢复队列状态
        
        Args:
            filepath: 文件路径
            
        Returns:
            是否成功
        """
        try:
            filepath = Path(filepath)
            if not filepath.exists():
                logger.warning(f"队列状态文件不存在: {filepath}")
                return False
            
            with open(filepath, "r", encoding="utf-8") as f:
                state = json.load(f)
            
            # 恢复堆
            self._heap = [QueueItem.from_dict(item) for item in state.get("heap", [])]
            heapq.heapify(self._heap)
            
            # 恢复集合
            self._seen_urls = set(state.get("seen_urls", []))
            self._processed_urls = set(state.get("processed_urls", []))
            self._failed_urls = state.get("failed_urls", {})
            
            # 恢复统计
            stats_data = state.get("stats", {})
            self._stats.total_added = stats_data.get("total_added", 0)
            self._stats.total_processed = stats_data.get("total_processed", 0)
            self._stats.duplicates_skipped = stats_data.get("duplicates_skipped", 0)
            self._stats.filtered_out = stats_data.get("filtered_out", 0)
            self._stats.current_size = len(self._heap)
            
            logger.info(f"队列状态已恢复: {filepath} (队列大小: {len(self._heap)})")
            return True
            
        except Exception as e:
            logger.error(f"恢复队列状态失败: {e}")
            logger.debug(get_err_message())
            return False
    
    # ========================================================================
    # 调试和显示
    # ========================================================================
    
    def __len__(self) -> int:
        """队列长度"""
        return len(self._heap)
    
    def __repr__(self) -> str:
        """字符串表示"""
        return (
            f"URLQueue(size={len(self._heap)}, "
            f"seen={len(self._seen_urls)}, "
            f"processed={len(self._processed_urls)})"
        )
    
    def print_status(self):
        """打印队列状态"""
        stats = self.get_stats()
        processed, total, progress = self.get_progress()
        
        print("\n" + "=" * 50)
        print("URL队列状态")
        print("=" * 50)
        print(f"当前队列大小: {stats.current_size}")
        print(f"总添加数: {stats.total_added}")
        print(f"已处理数: {stats.total_processed}")
        print(f"重复跳过: {stats.duplicates_skipped}")
        print(f"被过滤: {stats.filtered_out}")
        print(f"处理进度: {progress:.1f}%")
        print("\n优先级分布:")
        for priority, count in sorted(stats.priority_counts.items()):
            print(f"  P{priority}: {count}")
        print("\n深度分布:")
        for depth, count in sorted(stats.depth_counts.items()):
            print(f"  D{depth}: {count}")
        print("=" * 50 + "\n")


# ============================================================================
# 测试代码
# ============================================================================

if __name__ == "__main__":
    """测试URL队列管理器"""
    from config import Config
    
    print("=" * 60)
    print("URL队列管理器测试")
    print("=" * 60)
    
    # 创建配置
    config = Config()
    
    # 创建队列
    queue = URLQueue(config)
    print(f"\n初始化队列: {queue}")
    
    # 测试添加URL
    print("\n--- 测试添加URL ---")
    test_urls = [
        ("https://www.stanford.edu/", URLPriority.HIGH, 0),
        ("https://www.stanford.edu/admissions/", URLPriority.HIGH, 1),
        ("https://www.stanford.edu/academics/", URLPriority.MEDIUM, 1),
        ("https://www.stanford.edu/research/", URLPriority.MEDIUM, 1),
        ("https://www.stanford.edu/about/", URLPriority.LOW, 1),
        ("https://www.stanford.edu/contact/", URLPriority.LOW, 2),
    ]
    
    for url, priority, depth in test_urls:
        result = queue.add(url, priority=priority, depth=depth)
        print(f"  添加 [{result}]: {url}")
    
    # 测试重复检测
    print("\n--- 测试重复检测 ---")
    duplicate = queue.add("https://www.stanford.edu/admissions/")  # 重复
    print(f"  添加重复URL: {duplicate}")
    
    # 测试URL变体去重
    variant = queue.add("https://www.stanford.edu/admissions#section")  # Fragment变体
    print(f"  添加Fragment变体: {variant}")
    
    # 测试队列状态
    print("\n--- 队列状态 ---")
    queue.print_status()
    
    # 测试出队 (按优先级顺序)
    print("--- 测试出队顺序 ---")
    items = []
    while queue.has_next():
        item = queue.get_next()
        items.append(item)
        print(f"  出队 [P{item.priority}|D{item.depth}]: {item.url}")
        queue.mark_processed(item.url)
    
    # 验证优先级顺序
    print("\n--- 验证优先级顺序 ---")
    is_ordered = all(
        items[i].priority <= items[i+1].priority 
        for i in range(len(items)-1)
    )
    print(f"  优先级顺序正确: {is_ordered}")
    
    # 测试持久化
    print("\n--- 测试持久化 ---")
    
    # 重新添加URL
    for url, priority, depth in test_urls[:3]:
        queue.add(url, priority=priority, depth=depth)
    
    # 保存状态
    save_path = Path("web_automation/test_queue_state.json")
    save_result = queue.save_state(save_path)
    print(f"  保存状态: {save_result}")
    
    # 创建新队列并恢复
    queue2 = URLQueue(config)
    load_result = queue2.load_state(save_path)
    print(f"  恢复状态: {load_result}")
    print(f"  恢复后队列大小: {queue2.size()}")
    
    # 清理测试文件
    if save_path.exists():
        save_path.unlink()
    
    # 测试批量添加
    print("\n--- 测试批量添加 ---")
    queue3 = URLQueue(config)
    batch_urls = [
        {"url": "https://stanford.edu/page1", "priority": 1},
        {"url": "https://stanford.edu/page2", "priority": 2},
        {"url": "https://stanford.edu/page3"},  # 使用默认优先级
        "https://stanford.edu/page4",  # 字符串格式
    ]
    added = queue3.add_batch(batch_urls, parent_url="https://stanford.edu/")
    print(f"  批量添加: {added}/{len(batch_urls)}")
    
    print("\n" + "=" * 60)
    print("测试完成")
    print("=" * 60)