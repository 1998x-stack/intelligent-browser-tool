"""
LLM客户端模块 - Ollama API封装

设计理念 (CleanRL哲学):
- 单文件自包含: 所有LLM交互逻辑集中管理
- 透明的处理流程: 请求/响应流程清晰
- 最小化抽象: 直接的HTTP调用
- 便于调试: 详细的请求日志

支持模型:
- qwen3:0.6b - 快速处理 (意图匹配、命名)
- qwen3:1.7b - 深度分析 (意图转换、内容提取)
"""

import time
import json
import requests
from typing import Optional, Dict, Any, List, Generator
from dataclasses import dataclass, field

from loguru import logger

from config import LLMConfig, get_err_message


# ============================================================================
# 数据结构
# ============================================================================

@dataclass
class LLMResponse:
    """LLM响应数据结构"""
    content: str                    # 响应内容
    model: str                      # 使用的模型
    total_duration: float = 0.0    # 总耗时 (秒)
    load_duration: float = 0.0     # 模型加载耗时
    prompt_eval_count: int = 0     # 输入token数
    eval_count: int = 0            # 输出token数
    success: bool = True            # 是否成功
    error: str = ""                 # 错误信息
    
    @property
    def tokens_per_second(self) -> float:
        """计算每秒生成的token数"""
        if self.total_duration > 0:
            return self.eval_count / self.total_duration
        return 0.0


# ============================================================================
# LLM客户端类
# ============================================================================

class LLMClient:
    """
    LLM客户端 - 封装Ollama API调用
    
    使用方式:
        client = LLMClient(config)
        response = client.generate("What is AI?")
        print(response.content)
    """
    
    def __init__(self, config: LLMConfig):
        """
        初始化LLM客户端
        
        Args:
            config: LLM配置对象
        """
        self.config = config
        self.base_url = config.base_url
        
        # API端点
        self.generate_url = f"{self.base_url}/api/generate"
        self.chat_url = f"{self.base_url}/api/chat"
        self.tags_url = f"{self.base_url}/api/tags"
        
        # 会话设置
        self.session = requests.Session()
        self.session.headers.update({
            'Content-Type': 'application/json'
        })
        
        logger.info(f"LLM客户端初始化完成 (URL: {self.base_url})")
    
    def check_connection(self) -> bool:
        """
        检查Ollama服务是否可用
        
        Returns:
            是否可连接
        """
        try:
            response = self.session.get(self.tags_url, timeout=5)
            if response.status_code == 200:
                logger.info("Ollama服务连接正常")
                return True
            logger.warning(f"Ollama服务响应异常: {response.status_code}")
            return False
        except Exception as e:
            logger.error(f"无法连接Ollama服务: {e}")
            return False
    
    def list_models(self) -> List[str]:
        """
        获取可用模型列表
        
        Returns:
            模型名称列表
        """
        try:
            response = self.session.get(self.tags_url, timeout=10)
            if response.status_code == 200:
                data = response.json()
                models = [m.get('name', '') for m in data.get('models', [])]
                logger.debug(f"可用模型: {models}")
                return models
            return []
        except Exception as e:
            logger.error(f"获取模型列表失败: {e}")
            return []
    
    def generate(
        self,
        prompt: str,
        model: str = None,
        system: str = None,
        temperature: float = None,
        max_tokens: int = None,
        stream: bool = False,
        **kwargs
    ) -> LLMResponse:
        """
        生成文本响应
        
        Args:
            prompt: 用户提示
            model: 模型名称 (默认使用配置的analysis_model)
            system: 系统提示
            temperature: 温度参数
            max_tokens: 最大token数
            stream: 是否流式输出
            **kwargs: 其他参数
            
        Returns:
            LLMResponse对象
        """
        model = model or self.config.analysis_model
        temperature = temperature if temperature is not None else self.config.temperature
        max_tokens = max_tokens or self.config.max_tokens
        
        # 构建请求体
        payload = {
            "model": model,
            "prompt": prompt,
            "stream": stream,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
            }
        }
        
        if system:
            payload["system"] = system
        
        # 合并额外参数
        payload.update(kwargs)
        
        logger.debug(f"LLM请求 - 模型: {model}, 提示长度: {len(prompt)}")
        
        # 带重试的请求
        for attempt in range(self.config.max_retries):
            try:
                start_time = time.time()
                
                response = self.session.post(
                    self.generate_url,
                    json=payload,
                    timeout=self.config.timeout
                )
                
                if response.status_code != 200:
                    raise Exception(f"API错误: {response.status_code} - {response.text}")
                
                data = response.json()
                
                # 解析响应
                result = LLMResponse(
                    content=data.get('response', ''),
                    model=model,
                    total_duration=data.get('total_duration', 0) / 1e9,  # 纳秒转秒
                    load_duration=data.get('load_duration', 0) / 1e9,
                    prompt_eval_count=data.get('prompt_eval_count', 0),
                    eval_count=data.get('eval_count', 0),
                    success=True
                )
                
                elapsed = time.time() - start_time
                logger.debug(
                    f"LLM响应 - 耗时: {elapsed:.2f}s, "
                    f"输入tokens: {result.prompt_eval_count}, "
                    f"输出tokens: {result.eval_count}"
                )
                
                return result
                
            except Exception as e:
                logger.warning(f"LLM请求失败 (尝试 {attempt + 1}/{self.config.max_retries}): {e}")
                if attempt < self.config.max_retries - 1:
                    time.sleep(self.config.retry_delay)
        
        # 所有重试失败
        return LLMResponse(
            content="",
            model=model,
            success=False,
            error=f"LLM请求失败，已重试{self.config.max_retries}次"
        )
    
    def generate_stream(
        self,
        prompt: str,
        model: str = None,
        system: str = None,
        **kwargs
    ) -> Generator[str, None, None]:
        """
        流式生成文本
        
        Args:
            prompt: 用户提示
            model: 模型名称
            system: 系统提示
            **kwargs: 其他参数
            
        Yields:
            生成的文本片段
        """
        model = model or self.config.analysis_model
        
        payload = {
            "model": model,
            "prompt": prompt,
            "stream": True,
            "options": {
                "temperature": self.config.temperature,
                "num_predict": self.config.max_tokens,
            }
        }
        
        if system:
            payload["system"] = system
        
        payload.update(kwargs)
        
        try:
            response = self.session.post(
                self.generate_url,
                json=payload,
                timeout=self.config.timeout,
                stream=True
            )
            
            for line in response.iter_lines():
                if line:
                    data = json.loads(line)
                    if 'response' in data:
                        yield data['response']
                    if data.get('done', False):
                        break
                        
        except Exception as e:
            logger.error(f"流式生成失败: {e}")
            yield f"[错误: {e}]"
    
    def chat(
        self,
        messages: List[Dict[str, str]],
        model: str = None,
        **kwargs
    ) -> LLMResponse:
        """
        多轮对话
        
        Args:
            messages: 消息列表，格式: [{"role": "user/assistant", "content": "..."}]
            model: 模型名称
            **kwargs: 其他参数
            
        Returns:
            LLMResponse对象
        """
        model = model or self.config.analysis_model
        
        payload = {
            "model": model,
            "messages": messages,
            "stream": False,
            "options": {
                "temperature": self.config.temperature,
                "num_predict": self.config.max_tokens,
            }
        }
        
        payload.update(kwargs)
        
        logger.debug(f"Chat请求 - 模型: {model}, 消息数: {len(messages)}")
        
        try:
            response = self.session.post(
                self.chat_url,
                json=payload,
                timeout=self.config.timeout
            )
            
            if response.status_code != 200:
                raise Exception(f"API错误: {response.status_code}")
            
            data = response.json()
            
            return LLMResponse(
                content=data.get('message', {}).get('content', ''),
                model=model,
                total_duration=data.get('total_duration', 0) / 1e9,
                eval_count=data.get('eval_count', 0),
                success=True
            )
            
        except Exception as e:
            logger.error(f"Chat请求失败: {e}")
            return LLMResponse(
                content="",
                model=model,
                success=False,
                error=str(e)
            )
    
    # ========================================================================
    # 便捷方法 - 使用特定模型
    # ========================================================================
    
    def fast_generate(self, prompt: str, **kwargs) -> LLMResponse:
        """
        使用快速模型 (qwen3:0.6b) 生成
        
        适用于:
        - 意图匹配
        - 简单分类
        - 文件命名
        """
        return self.generate(prompt, model=self.config.fast_model, **kwargs)
    
    def intent_generate(self, prompt: str, **kwargs) -> LLMResponse:
        """
        使用意图模型 (qwen3:1.7b) 生成
        
        适用于:
        - 意图转换
        - 背景生成
        """
        return self.generate(prompt, model=self.config.intent_model, **kwargs)
    
    def analysis_generate(self, prompt: str, **kwargs) -> LLMResponse:
        """
        使用分析模型 (qwen3:1.7b) 生成
        
        适用于:
        - 内容分析
        - URL优先级排序
        - 详细提取
        """
        return self.generate(prompt, model=self.config.analysis_model, **kwargs)


# ============================================================================
# 工厂函数
# ============================================================================

def create_llm_client(config: LLMConfig = None) -> LLMClient:
    """
    创建LLM客户端实例
    
    Args:
        config: LLM配置，为None时使用默认配置
        
    Returns:
        LLMClient实例
    """
    if config is None:
        config = LLMConfig()
    return LLMClient(config)


# ============================================================================
# 模块测试
# ============================================================================

if __name__ == "__main__":
    print("=" * 60)
    print("LLM客户端模块测试")
    print("=" * 60)
    
    # 创建客户端
    config = LLMConfig()
    client = create_llm_client(config)
    
    # 检查连接
    print("\n--- 检查Ollama连接 ---")
    if not client.check_connection():
        print("无法连接Ollama服务，请确保Ollama正在运行")
        print("可以通过 'ollama serve' 启动服务")
        exit(1)
    
    # 列出模型
    print("\n--- 可用模型 ---")
    models = client.list_models()
    for m in models:
        print(f"  - {m}")
    
    # 测试生成
    print("\n--- 测试生成 ---")
    prompt = "用一句话介绍斯坦福大学"
    response = client.generate(prompt)
    
    if response.success:
        print(f"提示: {prompt}")
        print(f"响应: {response.content}")
        print(f"耗时: {response.total_duration:.2f}秒")
        print(f"Tokens/秒: {response.tokens_per_second:.1f}")
    else:
        print(f"生成失败: {response.error}")
    
    # 测试快速模型
    print("\n--- 测试快速模型 ---")
    fast_response = client.fast_generate("分类: 这是一条关于招生的信息")
    if fast_response.success:
        print(f"快速响应: {fast_response.content}")
        print(f"耗时: {fast_response.total_duration:.2f}秒")
    
    print("\n" + "=" * 60)
    print("测试完成!")
