"""
工具函数模块 - 通用工具函数集合

设计理念 (CleanRL哲学):
- 单文件自包含: 所有工具函数集中管理
- 透明的处理流程: 函数功能清晰单一
- 最小化抽象: 直接的函数实现
- 便于调试: 每个函数独立可测试
"""

import re
import sys
import json
import hashlib
import traceback
from typing import List, Dict, Any, Optional, Tuple
from urllib.parse import urlparse, urljoin, urldefrag
from pathlib import Path
from datetime import datetime

from loguru import logger


# ============================================================================
# 错误处理
# ============================================================================

def get_err_message() -> str:
    """
    获取详细的错误信息
    
    Returns:
        格式化的错误信息字符串
    """
    exc_type, exc_value, exc_traceback = sys.exc_info()
    error_message = repr(
        traceback.format_exception(exc_type, exc_value, exc_traceback)
    )
    return error_message


def safe_execute(func, *args, default=None, **kwargs):
    """
    安全执行函数，捕获异常
    
    Args:
        func: 要执行的函数
        *args: 位置参数
        default: 异常时的默认返回值
        **kwargs: 关键字参数
        
    Returns:
        函数返回值或默认值
    """
    try:
        return func(*args, **kwargs)
    except Exception as e:
        logger.warning(f"函数 {func.__name__} 执行失败: {e}")
        return default


# ============================================================================
# URL处理
# ============================================================================

def normalize_url(url: str, base_url: str = None) -> Optional[str]:
    """
    规范化URL
    
    Args:
        url: 原始URL
        base_url: 基础URL (用于相对路径)
        
    Returns:
        规范化后的URL
    """
    if not url:
        return None
    
    # 去除空白字符
    url = url.strip()
    
    # 移除URL片段 (如 #section)
    url, _ = urldefrag(url)
    
    # 处理相对路径
    if base_url and not url.startswith(('http://', 'https://')):
        url = urljoin(base_url, url)
    
    # 验证URL
    try:
        parsed = urlparse(url)
        if not parsed.scheme or not parsed.netloc:
            return None
        return url
    except Exception:
        return None


def extract_domain(url: str) -> Optional[str]:
    """
    提取URL的域名
    
    Args:
        url: URL字符串
        
    Returns:
        域名字符串
    """
    try:
        parsed = urlparse(url)
        return parsed.netloc
    except Exception:
        return None


def is_same_domain(url1: str, url2: str) -> bool:
    """
    检查两个URL是否属于同一域名
    
    Args:
        url1: 第一个URL
        url2: 第二个URL
        
    Returns:
        是否同域
    """
    domain1 = extract_domain(url1)
    domain2 = extract_domain(url2)
    
    if not domain1 or not domain2:
        return False
    
    # 比较主域名 (忽略子域名差异)
    parts1 = domain1.split('.')[-2:]
    parts2 = domain2.split('.')[-2:]
    
    return parts1 == parts2


def filter_urls(
    urls: List[str],
    base_url: str,
    allowed_domains: List[str] = None,
    exclude_patterns: List[str] = None
) -> List[str]:
    """
    过滤URL列表
    
    Args:
        urls: URL列表
        base_url: 基础URL
        allowed_domains: 允许的域名列表
        exclude_patterns: 排除的URL模式列表
        
    Returns:
        过滤后的URL列表
    """
    filtered = []
    seen = set()
    
    for url in urls:
        # 规范化
        normalized = normalize_url(url, base_url)
        if not normalized:
            continue
        
        # 去重
        if normalized in seen:
            continue
        seen.add(normalized)
        
        # 域名检查
        if allowed_domains:
            domain = extract_domain(normalized)
            if not any(d in domain for d in allowed_domains):
                continue
        
        # 排除模式检查
        if exclude_patterns:
            if any(pattern in normalized for pattern in exclude_patterns):
                continue
        
        filtered.append(normalized)
    
    return filtered


def url_to_filename(url: str, max_length: int = 100) -> str:
    """
    将URL转换为合法的文件名
    
    Args:
        url: URL字符串
        max_length: 最大长度
        
    Returns:
        文件名字符串
    """
    # 移除协议
    name = re.sub(r'^https?://', '', url)
    
    # 替换非法字符
    name = re.sub(r'[<>:"/\\|?*]', '_', name)
    
    # 截断
    if len(name) > max_length:
        # 保留URL的哈希以确保唯一性
        url_hash = hashlib.md5(url.encode()).hexdigest()[:8]
        name = name[:max_length - 9] + '_' + url_hash
    
    return name


# ============================================================================
# 文本处理
# ============================================================================

def clean_text(text: str) -> str:
    """
    清理文本内容
    
    Args:
        text: 原始文本
        
    Returns:
        清理后的文本
    """
    if not text:
        return ""
    
    # 替换多个空白字符为单个空格
    text = re.sub(r'\s+', ' ', text)
    
    # 移除控制字符
    text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', text)
    
    # 去除首尾空白
    text = text.strip()
    
    return text


def truncate_text(text: str, max_length: int, suffix: str = "...") -> str:
    """
    截断文本
    
    Args:
        text: 原始文本
        max_length: 最大长度
        suffix: 截断后缀
        
    Returns:
        截断后的文本
    """
    if len(text) <= max_length:
        return text
    
    return text[:max_length - len(suffix)] + suffix


def extract_sentences(text: str) -> List[str]:
    """
    提取文本中的句子
    
    Args:
        text: 原始文本
        
    Returns:
        句子列表
    """
    # 按句号、问号、感叹号分割
    sentences = re.split(r'[.!?。！？]+', text)
    
    # 清理并过滤空句子
    sentences = [clean_text(s) for s in sentences if clean_text(s)]
    
    return sentences


def chunk_text(
    text: str,
    chunk_size: int = 1000,
    overlap: int = 200,
    min_chunk_size: int = 50
) -> List[str]:
    """
    将文本分块
    
    Args:
        text: 原始文本
        chunk_size: 块大小
        overlap: 重叠大小
        min_chunk_size: 最小块大小
        
    Returns:
        文本块列表
    """
    if not text or len(text) < min_chunk_size:
        return [text] if text else []
    
    chunks = []
    start = 0
    
    while start < len(text):
        end = start + chunk_size
        
        # 尝试在句子边界截断
        if end < len(text):
            # 在chunk_size附近找句子结束位置
            boundary = text.rfind('.', start + chunk_size - overlap, end)
            if boundary > start:
                end = boundary + 1
        
        chunk = text[start:end].strip()
        if chunk and len(chunk) >= min_chunk_size:
            chunks.append(chunk)
        
        # 下一个块的起始位置
        start = end - overlap if end < len(text) else end
    
    return chunks


# ============================================================================
# 正则提取
# ============================================================================

def extract_emails(text: str) -> List[str]:
    """提取文本中的邮箱地址"""
    pattern = r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'
    return list(set(re.findall(pattern, text)))


def extract_phones(text: str) -> List[str]:
    """提取文本中的电话号码"""
    # 匹配多种电话格式
    patterns = [
        r'\b\d{3}[-.\s]?\d{3}[-.\s]?\d{4}\b',  # 美式格式
        r'\b\+?\d{1,3}[-.\s]?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b',  # 国际格式
        r'\b\d{4}[-.\s]?\d{4}[-.\s]?\d{4}\b',  # 其他格式
    ]
    
    phones = []
    for pattern in patterns:
        phones.extend(re.findall(pattern, text))
    
    return list(set(phones))


def extract_urls_from_text(text: str) -> List[str]:
    """提取文本中的URL"""
    pattern = r'https?://[^\s<>"\'{}|\\^`\[\]]+'
    return list(set(re.findall(pattern, text)))


def extract_json_from_text(text: str) -> Optional[Dict]:
    """
    从文本中提取JSON对象
    
    Args:
        text: 包含JSON的文本
        
    Returns:
        解析后的字典，失败返回None
    """
    # 尝试直接解析
    try:
        return json.loads(text)
    except Exception:
        pass
    
    # 尝试提取JSON块
    patterns = [
        r'```json\s*([\s\S]*?)\s*```',  # Markdown代码块
        r'\{[\s\S]*\}',  # 花括号包裹
        r'\[[\s\S]*\]',  # 方括号包裹
    ]
    
    for pattern in patterns:
        matches = re.findall(pattern, text)
        for match in matches:
            try:
                return json.loads(match)
            except Exception:
                continue
    
    return None


# ============================================================================
# 文件操作
# ============================================================================

def safe_write_file(filepath: Path, content: str, encoding: str = 'utf-8') -> bool:
    """
    安全写入文件
    
    Args:
        filepath: 文件路径
        content: 文件内容
        encoding: 编码
        
    Returns:
        是否成功
    """
    try:
        filepath = Path(filepath)
        filepath.parent.mkdir(parents=True, exist_ok=True)
        filepath.write_text(content, encoding=encoding)
        return True
    except Exception as e:
        logger.error(f"写入文件失败 ({filepath}): {e}")
        return False


def safe_read_file(filepath: Path, encoding: str = 'utf-8') -> Optional[str]:
    """
    安全读取文件
    
    Args:
        filepath: 文件路径
        encoding: 编码
        
    Returns:
        文件内容
    """
    try:
        filepath = Path(filepath)
        if filepath.exists():
            return filepath.read_text(encoding=encoding)
        return None
    except Exception as e:
        logger.error(f"读取文件失败 ({filepath}): {e}")
        return None


def safe_write_json(filepath: Path, data: Any, indent: int = 2) -> bool:
    """
    安全写入JSON文件
    
    Args:
        filepath: 文件路径
        data: 数据对象
        indent: 缩进
        
    Returns:
        是否成功
    """
    try:
        content = json.dumps(data, ensure_ascii=False, indent=indent)
        return safe_write_file(filepath, content)
    except Exception as e:
        logger.error(f"写入JSON失败 ({filepath}): {e}")
        return False


def safe_read_json(filepath: Path) -> Optional[Any]:
    """
    安全读取JSON文件
    
    Args:
        filepath: 文件路径
        
    Returns:
        解析后的数据
    """
    content = safe_read_file(filepath)
    if content:
        try:
            return json.loads(content)
        except Exception as e:
            logger.error(f"解析JSON失败 ({filepath}): {e}")
    return None


# ============================================================================
# 数据结构处理
# ============================================================================

def flatten_dict(d: Dict, parent_key: str = '', sep: str = '.') -> Dict:
    """
    扁平化嵌套字典
    
    Args:
        d: 嵌套字典
        parent_key: 父键名
        sep: 分隔符
        
    Returns:
        扁平化后的字典
    """
    items = []
    for k, v in d.items():
        new_key = f"{parent_key}{sep}{k}" if parent_key else k
        if isinstance(v, dict):
            items.extend(flatten_dict(v, new_key, sep).items())
        else:
            items.append((new_key, v))
    return dict(items)


def merge_dicts(*dicts: Dict) -> Dict:
    """
    合并多个字典
    
    Args:
        *dicts: 要合并的字典
        
    Returns:
        合并后的字典
    """
    result = {}
    for d in dicts:
        if d:
            result.update(d)
    return result


# ============================================================================
# 时间处理
# ============================================================================

def get_timestamp() -> str:
    """获取当前时间戳字符串"""
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def format_duration(seconds: float) -> str:
    """
    格式化持续时间
    
    Args:
        seconds: 秒数
        
    Returns:
        格式化的时间字符串
    """
    if seconds < 60:
        return f"{seconds:.1f}秒"
    elif seconds < 3600:
        minutes = seconds / 60
        return f"{minutes:.1f}分钟"
    else:
        hours = seconds / 3600
        return f"{hours:.1f}小时"


# ============================================================================
# 哈希计算
# ============================================================================

def compute_hash(content: str, algorithm: str = 'md5') -> str:
    """
    计算内容哈希值
    
    Args:
        content: 内容字符串
        algorithm: 哈希算法 (md5, sha1, sha256)
        
    Returns:
        哈希值字符串
    """
    if algorithm == 'md5':
        hasher = hashlib.md5()
    elif algorithm == 'sha1':
        hasher = hashlib.sha1()
    elif algorithm == 'sha256':
        hasher = hashlib.sha256()
    else:
        raise ValueError(f"不支持的哈希算法: {algorithm}")
    
    hasher.update(content.encode('utf-8'))
    return hasher.hexdigest()


def is_content_duplicate(content: str, seen_hashes: set, algorithm: str = 'md5') -> bool:
    """
    检查内容是否重复
    
    Args:
        content: 内容字符串
        seen_hashes: 已见哈希集合
        algorithm: 哈希算法
        
    Returns:
        是否重复
    """
    content_hash = compute_hash(content, algorithm)
    if content_hash in seen_hashes:
        return True
    seen_hashes.add(content_hash)
    return False


# ============================================================================
# 模块测试
# ============================================================================

if __name__ == "__main__":
    print("=" * 60)
    print("工具函数模块测试")
    print("=" * 60)
    
    # 测试URL处理
    print("\n--- URL处理测试 ---")
    test_url = "https://www.stanford.edu/admission/apply#section"
    print(f"原始URL: {test_url}")
    print(f"规范化: {normalize_url(test_url)}")
    print(f"域名: {extract_domain(test_url)}")
    print(f"文件名: {url_to_filename(test_url)}")
    
    # 测试文本处理
    print("\n--- 文本处理测试 ---")
    test_text = "  Hello   World!  This is a test.  What do you think?  "
    print(f"原始文本: '{test_text}'")
    print(f"清理后: '{clean_text(test_text)}'")
    print(f"句子: {extract_sentences(test_text)}")
    
    # 测试分块
    print("\n--- 文本分块测试 ---")
    long_text = "This is sentence one. " * 250
    chunks = chunk_text(long_text, chunk_size=100, overlap=20)
    print(f"原文长度: {len(long_text)}")
    print(f"分块数量: {len(chunks)}")
    print(f"第一块长度: {len(chunks[0])}")
    
    # 测试正则提取
    print("\n--- 正则提取测试 ---")
    mixed_text = "Contact us at info@stanford.edu or call 650-723-2300. Visit https://www.stanford.edu"
    print(f"文本: {mixed_text}")
    print(f"邮箱: {extract_emails(mixed_text)}")
    print(f"电话: {extract_phones(mixed_text)}")
    print(f"URL: {extract_urls_from_text(mixed_text)}")
    
    # 测试JSON提取
    print("\n--- JSON提取测试 ---")
    json_text = 'Some text ```json{"key": "value", "number": 123}``` more text'
    print(f"文本: {json_text}")
    print(f"JSON: {extract_json_from_text(json_text)}")
    
    # 测试哈希
    print("\n--- 哈希测试 ---")
    content = "Test content"
    print(f"内容: {content}")
    print(f"MD5: {compute_hash(content, 'md5')}")
    print(f"SHA256: {compute_hash(content, 'sha256')}")
    
    print("\n" + "=" * 60)
    print("测试完成!")