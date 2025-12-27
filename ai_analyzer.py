"""
AI分析器 - 使用Ollama模型进行智能分析

设计理念:
- 双模型架构: 0.5b快速分类 + 3b/4b深度分析
- 结构化输出: 所有输出为JSON格式
- 错误容忍: 优雅处理模型错误
- 响应缓存: 减少重复调用

参考: Ollama API最佳实践
"""

import json
import re
import time
import hashlib
from typing import Dict, Optional, List, Any, Tuple
from dataclasses import dataclass

import requests
from loguru import logger

from config import Config, OllamaConfig
from prompts import PromptBuilder


@dataclass
class ModelResponse:
    """模型响应"""
    success: bool
    content: str
    parsed: Optional[Dict]
    model: str
    elapsed: float
    error: Optional[str] = None


class AIAnalyzer:
    """
    AI分析器 - 使用Ollama进行网页内容分析
    
    功能:
    1. 页面分类 (0.5b模型) - 快速判断页面类型
    2. 内容分析 (3b/4b模型) - 深度提取结构化信息
    3. URL推荐 (3b/4b模型) - 推荐下一步访问的链接
    4. 信息整合 (3b/4b模型) - 整合多页面信息
    
    使用示例:
        analyzer = AIAnalyzer(config, user_intent)
        classification = analyzer.classify_page(title, preview)
        analysis = analyzer.analyze_content(title, url, content)
    """
    
    def __init__(self, config: Config, user_intent: str = ""):
        """
        初始化AI分析器
        
        Args:
            config: 配置对象
            user_intent: 用户意图
        """
        self.config = config
        self.ollama_config = config.ollama
        self.prompt_builder = PromptBuilder(user_intent)
        self.user_intent = user_intent
        
        # 响应缓存
        self._cache: Dict[str, ModelResponse] = {}
        
        # 验证Ollama连接
        self._verify_connection()
        
        logger.info(
            f"AI分析器初始化完成 - "
            f"小模型: {self.ollama_config.small_model}, "
            f"大模型: {self.ollama_config.large_model}"
        )
    
    def _verify_connection(self):
        """验证Ollama服务连接"""
        try:
            url = f"{self.ollama_config.host}/api/tags"
            response = requests.get(url, timeout=5)
            
            if response.status_code == 200:
                models = response.json().get('models', [])
                model_names = [m['name'] for m in models]
                
                # 检查所需模型是否存在
                for model in [self.ollama_config.small_model, 
                             self.ollama_config.large_model]:
                    if not any(model in name for name in model_names):
                        logger.warning(f"模型未找到: {model}")
                
                logger.debug(f"Ollama连接成功，可用模型: {len(models)}")
            else:
                logger.warning(f"Ollama响应异常: {response.status_code}")
                
        except Exception as e:
            logger.error(f"Ollama连接失败: {e}")
            raise ConnectionError(f"无法连接Ollama服务: {self.ollama_config.host}")
    
    def _call_ollama(
        self, 
        model: str, 
        system_prompt: str, 
        user_prompt: str,
        temperature: float = None,
        max_tokens: int = None
    ) -> ModelResponse:
        """
        调用Ollama API
        
        Args:
            model: 模型名称
            system_prompt: 系统提示
            user_prompt: 用户提示
            temperature: 温度参数
            max_tokens: 最大token数
            
        Returns:
            ModelResponse对象
        """
        # 检查缓存
        cache_key = hashlib.md5(
            f"{model}{system_prompt}{user_prompt}".encode()
        ).hexdigest()
        
        if cache_key in self._cache:
            logger.debug("使用缓存响应")
            return self._cache[cache_key]
        
        # 准备请求
        url = f"{self.ollama_config.host}/api/chat"
        
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            "stream": False,
            "options": {
                "temperature": temperature or self.ollama_config.temperature,
                "num_predict": max_tokens or self.ollama_config.max_tokens
            }
        }
        
        start_time = time.time()
        
        try:
            response = requests.post(
                url, 
                json=payload, 
                timeout=self.ollama_config.timeout
            )
            
            elapsed = time.time() - start_time
            
            if response.status_code == 200:
                result = response.json()
                content = result.get('message', {}).get('content', '')
                
                # 尝试解析JSON
                parsed = self._parse_json_response(content)
                
                model_response = ModelResponse(
                    success=True,
                    content=content,
                    parsed=parsed,
                    model=model,
                    elapsed=elapsed
                )
                
                # 缓存成功响应
                self._cache[cache_key] = model_response
                
                logger.debug(f"模型调用成功: {model}, {elapsed:.2f}s")
                return model_response
                
            else:
                return ModelResponse(
                    success=False,
                    content="",
                    parsed=None,
                    model=model,
                    elapsed=elapsed,
                    error=f"HTTP {response.status_code}"
                )
                
        except requests.Timeout:
            elapsed = time.time() - start_time
            logger.warning(f"模型调用超时: {model}")
            return ModelResponse(
                success=False,
                content="",
                parsed=None,
                model=model,
                elapsed=elapsed,
                error="timeout"
            )
            
        except Exception as e:
            elapsed = time.time() - start_time
            logger.error(f"模型调用失败: {e}")
            return ModelResponse(
                success=False,
                content="",
                parsed=None,
                model=model,
                elapsed=elapsed,
                error=str(e)
            )
    
    def _parse_json_response(self, content: str) -> Optional[Dict]:
        """
        解析模型输出中的JSON
        
        处理各种情况:
        - 纯JSON
        - Markdown代码块中的JSON
        - 带有额外文本的JSON
        """
        if not content:
            return None
        
        # 尝试直接解析
        try:
            return json.loads(content)
        except:
            pass
        
        # 尝试提取代码块中的JSON
        patterns = [
            r'```json\s*([\s\S]*?)\s*```',
            r'```\s*([\s\S]*?)\s*```',
            r'\{[\s\S]*\}'
        ]
        
        for pattern in patterns:
            matches = re.findall(pattern, content)
            for match in matches:
                try:
                    # 清理匹配内容
                    clean = match.strip()
                    if not clean.startswith('{'):
                        continue
                    return json.loads(clean)
                except:
                    continue
        
        return None
    
    # ========== 0.5b模型功能 ==========
    
    def classify_page(
        self, 
        title: str, 
        text_preview: str
    ) -> Dict:
        """
        页面分类 (使用0.5b模型)
        
        快速判断页面类型和是否值得深入分析
        
        Args:
            title: 页面标题
            text_preview: 文本预览
            
        Returns:
            分类结果字典
        """
        prompt = self.prompt_builder.build_classification_prompt(
            title, text_preview
        )
        
        response = self._call_ollama(
            model=self.ollama_config.small_model,
            system_prompt=prompt['system'],
            user_prompt=prompt['user'],
            temperature=0.1,
            max_tokens=256
        )
        
        if response.success and response.parsed:
            result = response.parsed
            result['model'] = self.ollama_config.small_model
            result['elapsed'] = response.elapsed
            return result
        
        # 默认返回
        return {
            'category': 'other',
            'confidence': 0.5,
            'should_extract': True,
            'reason': 'classification_failed',
            'model': self.ollama_config.small_model,
            'elapsed': response.elapsed
        }
    
    def quick_relevance_check(self, text: str) -> bool:
        """
        快速相关性判断 (使用0.5b模型)
        
        Args:
            text: 文本内容
            
        Returns:
            是否相关
        """
        if not self.user_intent:
            return True
        
        prompt = self.prompt_builder.build_quick_relevance_prompt(text)
        
        response = self._call_ollama(
            model=self.ollama_config.small_model,
            system_prompt=prompt['system'],
            user_prompt=prompt['user'],
            temperature=0.1,
            max_tokens=10
        )
        
        if response.success:
            content = response.content.lower().strip()
            return 'yes' in content
        
        return True  # 默认相关
    
    def score_links(
        self, 
        links: List[Dict]
    ) -> List[Dict]:
        """
        链接评分 (使用0.5b模型)
        
        Args:
            links: 链接列表
            
        Returns:
            带评分的链接列表
        """
        if not links:
            return []
        
        prompt = self.prompt_builder.build_link_priority_prompt(links)
        
        response = self._call_ollama(
            model=self.ollama_config.small_model,
            system_prompt=prompt['system'],
            user_prompt=prompt['user'],
            temperature=0.1,
            max_tokens=512
        )
        
        if response.success and response.parsed:
            scores = response.parsed.get('scores', [])
            
            # 合并评分到原始链接
            score_map = {s['url']: s.get('score', 1) for s in scores}
            
            for link in links:
                link['ai_score'] = score_map.get(link['url'], 1)
            
            # 按评分排序
            links.sort(key=lambda x: x.get('ai_score', 0), reverse=True)
        
        return links
    
    # ========== 3b/4b模型功能 ==========
    
    def analyze_content(
        self, 
        title: str, 
        url: str, 
        content: str,
        metadata: Optional[Dict] = None
    ) -> Dict:
        """
        内容深度分析 (使用3b/4b模型)
        
        提取结构化信息
        
        Args:
            title: 页面标题
            url: 页面URL
            content: 页面内容
            metadata: 元数据
            
        Returns:
            分析结果字典
        """
        prompt = self.prompt_builder.build_content_analysis_prompt(
            title, url, content
        )
        
        response = self._call_ollama(
            model=self.ollama_config.large_model,
            system_prompt=prompt['system'],
            user_prompt=prompt['user'],
            temperature=0.2,
            max_tokens=1024
        )
        
        if response.success and response.parsed:
            result = response.parsed
            result['url'] = url
            result['title'] = title
            result['model'] = self.ollama_config.large_model
            result['elapsed'] = response.elapsed
            return result
        
        # 降级处理 - 返回基本信息
        return {
            'url': url,
            'title': title,
            'summary': content[:300] if content else "",
            'key_points': [],
            'entities': {},
            'facts': [],
            'keywords': [],
            'relevance_score': 0.5,
            'model': self.ollama_config.large_model,
            'elapsed': response.elapsed,
            'analysis_failed': True
        }
    
    def recommend_urls(
        self, 
        current_url: str, 
        summary: str, 
        links: List[Dict],
        visited_urls: set = None
    ) -> List[Dict]:
        """
        URL推荐 (使用3b/4b模型)
        
        推荐下一步要访问的链接
        
        Args:
            current_url: 当前页面URL
            summary: 当前页面摘要
            links: 可用链接列表
            visited_urls: 已访问的URL集合
            
        Returns:
            推荐的URL列表
        """
        # 过滤已访问的链接
        if visited_urls:
            links = [l for l in links if l['url'] not in visited_urls]
        
        if not links:
            return []
        
        prompt = self.prompt_builder.build_url_recommendation_prompt(
            current_url, summary, links
        )
        
        response = self._call_ollama(
            model=self.ollama_config.large_model,
            system_prompt=prompt['system'],
            user_prompt=prompt['user'],
            temperature=0.2,
            max_tokens=512
        )
        
        if response.success and response.parsed:
            recommended = response.parsed.get('recommended', [])
            return recommended[:5]  # 最多5个
        
        # 降级处理 - 返回优先级最高的链接
        return [{'url': l['url'], 'priority': l.get('priority', 0), 
                'reason': 'fallback'} for l in links[:3]]
    
    def synthesize_info(
        self, 
        collected_info: List[Dict]
    ) -> Dict:
        """
        信息整合 (使用3b/4b模型)
        
        将多个页面的信息整合成报告
        
        Args:
            collected_info: 收集到的信息列表
            
        Returns:
            整合后的报告
        """
        if not collected_info:
            return {}
        
        prompt = self.prompt_builder.build_synthesis_prompt(collected_info)
        
        response = self._call_ollama(
            model=self.ollama_config.large_model,
            system_prompt=prompt['system'],
            user_prompt=prompt['user'],
            temperature=0.3,
            max_tokens=2048
        )
        
        if response.success and response.parsed:
            return response.parsed
        
        return {
            'topic_summary': f"收集了 {len(collected_info)} 个页面的信息",
            'sections': [],
            'key_findings': [],
            'synthesis_failed': True
        }
    
    def generate_filename(
        self, 
        title: str, 
        category: str, 
        keywords: List[str]
    ) -> str:
        """
        生成文件名 (使用0.5b模型)
        
        Args:
            title: 页面标题
            category: 页面类别
            keywords: 关键词
            
        Returns:
            文件名（不含扩展名）
        """
        prompt = self.prompt_builder.build_file_naming_prompt(
            title, category, keywords
        )
        
        response = self._call_ollama(
            model=self.ollama_config.small_model,
            system_prompt=prompt['system'],
            user_prompt=prompt['user'],
            temperature=0.1,
            max_tokens=50
        )
        
        if response.success:
            # 清理文件名
            filename = response.content.strip()
            filename = re.sub(r'[^\w\-]', '_', filename)
            filename = re.sub(r'_+', '_', filename)
            return filename[:30].strip('_')
        
        # 降级处理
        return f"{category}_{hashlib.md5(title.encode()).hexdigest()[:8]}"
    
    def clear_cache(self):
        """清除响应缓存"""
        self._cache.clear()
        logger.debug("响应缓存已清除")
    
    def get_stats(self) -> Dict:
        """获取统计信息"""
        return {
            'cache_size': len(self._cache),
            'small_model': self.ollama_config.small_model,
            'large_model': self.ollama_config.large_model
        }


if __name__ == "__main__":
    # 测试AI分析器
    from config import get_fast_config
    
    config = get_fast_config()
    intent = "了解斯坦福大学的国际学生招生政策"
    
    try:
        analyzer = AIAnalyzer(config, intent)
        
        # 测试分类
        result = analyzer.classify_page(
            title="Stanford Admissions",
            text_preview="Apply to Stanford University..."
        )
        print(f"分类结果: {json.dumps(result, indent=2, ensure_ascii=False)}")
        
    except Exception as e:
        print(f"测试失败: {e}")