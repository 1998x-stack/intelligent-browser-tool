# Web Automation Tool / 网页自动化工具

基于Ollama LLM、Selenium/Requests和Trafilatura的智能网页爬取与分析工具。

A smart web crawling and analysis tool powered by Ollama LLM, Selenium/Requests, and Trafilatura.

## 目录 / Table of Contents

- [特性](#特性--features)
- [架构](#架构--architecture)
- [安装](#安装--installation)
- [使用方法](#使用方法--usage)
- [配置](#配置--configuration)
- [模块说明](#模块说明--modules)
- [工作流程](#工作流程--workflow)
- [示例](#示例--examples)
- [开发指南](#开发指南--development)

## 特性 / Features

### 核心功能
- **LLM驱动分析**: 使用Ollama本地模型进行意图理解和内容分析
- **双模式浏览器**: Selenium (JavaScript渲染) / Requests (轻量快速)
- **智能内容提取**: Trafilatura + BeautifulSoup 双重保障
- **优先级队列**: 基于LLM分析的URL优先级调度
- **自动报告**: 生成Markdown/JSON格式的详细报告

### 设计原则 (CleanRL Philosophy)
- **单文件自包含**: 每个模块独立完整,可单独测试
- **透明处理流程**: 所有逻辑清晰可见,便于理解
- **最小化抽象**: 直接的函数调用,简单的类层次
- **便于调试**: 详细的日志记录,完善的错误处理

## 架构 / Architecture

```
web_automation/
├── config.py              # 配置管理 - Configuration management
├── logger_config.py       # 日志配置 - Logging configuration
├── utils.py               # 工具函数 - Utility functions
├── llm_client.py          # LLM客户端 - Ollama API wrapper
├── browser_engine.py      # 浏览器引擎 - Selenium/Requests
├── content_extractor.py   # 内容提取 - Trafilatura extraction
├── intent_analyzer.py     # 意图分析 - Intent to prompt components
├── content_analyzer.py    # 内容分析 - LLM content analysis
├── file_namer.py          # 文件命名 - Semantic file naming
├── url_queue.py           # URL队列 - Priority queue management
├── storage_manager.py     # 存储管理 - Data persistence
├── report_generator.py    # 报告生成 - Markdown/JSON reports
├── crawler.py             # 主控制器 - Main orchestrator
├── requirements.txt       # 依赖包 - Dependencies
└── outputs/               # 输出目录 - Output directory
    ├── raw/               # 原始HTML
    ├── processed/         # 处理后数据
    ├── reports/           # 分析报告
    └── logs/              # 运行日志
```

## 安装 / Installation

### 1. 环境要求

- Python 3.8+
- Ollama (本地运行)
- Chrome浏览器 (如使用Selenium)

### 2. 安装Ollama

```bash
# macOS / Linux
curl -fsSL https://ollama.com/install.sh | sh

# 拉取所需模型
ollama pull qwen3:1.7b
ollama pull qwen3:0.6b

# 启动Ollama服务
ollama serve
```

### 3. 安装Python依赖

```bash
cd web_automation
pip install -r requirements.txt
```

### 4. 验证安装

```bash
# 测试LLM连接
python llm_client.py

# 测试浏览器引擎
python browser_engine.py

# 测试内容提取
python content_extractor.py
```

## 使用方法 / Usage

### 命令行使用

```bash
# 基本用法 - 爬取斯坦福大学招生信息
python crawler.py -u https://www.stanford.edu/ -i "招生信息"

# 指定最大页面数和深度
python crawler.py -u https://example.com -i "contact info" --max-pages 20 --max-depth 2

# 使用Requests代替Selenium (更快但不支持JS)
python crawler.py -u https://news.site.com -i "latest news" --no-selenium

# 调试模式
python crawler.py -u https://example.com -i "test" --debug
```

### 命令行参数

| 参数 | 简写 | 默认值 | 说明 |
|------|------|--------|------|
| `--url` | `-u` | stanford.edu | 起始URL |
| `--intent` | `-i` | 招生 | 用户意图 |
| `--max-pages` | | 50 | 最大爬取页面数 |
| `--max-depth` | | 3 | 最大爬取深度 |
| `--output-dir` | `-o` | ./outputs | 输出目录 |
| `--no-selenium` | | False | 使用Requests |
| `--no-report` | | False | 跳过报告生成 |
| `--debug` | | False | 调试模式 |

### 编程接口

```python
from crawler import WebCrawler, CrawlConfig

# 创建配置
config = CrawlConfig(
    start_url="https://www.stanford.edu/",
    intent="研究生申请",
    max_pages=30,
    max_depth=2,
    use_selenium=True,
    output_dir="./my_outputs"
)

# 运行爬虫
crawler = WebCrawler(config)
summary = crawler.run()

# 查看结果
print(f"爬取完成: {summary['successful_pages']}/{summary['total_pages']} 页")
```

## 配置 / Configuration

### config.py 配置项

```python
# 浏览器配置
BrowserConfig:
    timeout: 30                    # 页面加载超时
    retry_times: 3                 # 重试次数
    headless: True                 # 无头模式
    user_agent: "..."              # User-Agent

# LLM配置
LLMConfig:
    base_url: "http://localhost:11434"
    intent_model: "qwen3:1.7b"     # 意图分析模型
    fast_model: "qwen3:0.6b"       # 快速任务模型
    analysis_model: "qwen3:1.7b"   # 内容分析模型
    temperature: 0.7
    max_tokens: 2048

# 内容配置
ContentConfig:
    chunk_size: 1000               # 分块大小
    chunk_overlap: 200             # 分块重叠
    max_urls_per_page: 50          # 每页最大URL数

# 爬取配置
CrawlConfig:
    max_pages: 50                  # 最大页面数
    max_depth: 3                   # 最大深度
```

## 模块说明 / Modules

### 1. llm_client.py - LLM客户端

封装Ollama API,提供:
- `generate()`: 基础文本生成
- `fast_generate()`: 快速任务 (qwen3:0.6b)
- `intent_generate()`: 意图分析 (qwen3:1.7b)
- `analysis_generate()`: 内容分析 (qwen3:1.7b)

### 2. browser_engine.py - 浏览器引擎

双模式网页获取:
- `SeleniumEngine`: 完整JavaScript支持,反检测配置
- `RequestsEngine`: 轻量快速,静态页面

### 3. content_extractor.py - 内容提取器

基于Trafilatura的内容提取:
- 自动提取正文、标题、作者、日期
- 链接提取和分类
- 邮箱、电话提取
- 内容分块

### 4. intent_analyzer.py - 意图分析器

将用户意图转换为结构化组件:
- `category`: 意图类别
- `keywords`: 搜索关键词
- `search_focus`: 搜索焦点
- `priority_signals`: 优先级信号
- `prompt_background`: prompt背景

### 5. content_analyzer.py - 内容分析器

LLM驱动的内容分析:
- 相关性评分 (0-1)
- 关键发现提取
- 结构化数据提取
- URL优先级排序 (1-3级)

### 6. url_queue.py - URL队列

优先级队列管理:
- 基于heapq的最小堆实现
- URL去重和规范化
- 深度控制
- 域名过滤

### 7. storage_manager.py - 存储管理器

数据持久化:
- 原始HTML保存
- JSON数据保存
- 目录结构管理
- 文件命名

### 8. report_generator.py - 报告生成器

生成分析报告:
- Markdown格式报告
- JSON格式数据
- 统计摘要
- 页面详情

## 工作流程 / Workflow

```
┌─────────────────────────────────────────────────────────────┐
│                    1. 用户输入                              │
│                URL + Intent (意图)                          │
└─────────────────────┬───────────────────────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────────────────────┐
│                 2. 意图分析 (qwen3:1.7b)                     │
│     Intent → Category, Keywords, Search Focus, etc.         │
└─────────────────────┬───────────────────────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────────────────────┐
│               3. 页面获取 (Selenium/Requests)                │
│                    URL → HTML Content                       │
└─────────────────────┬───────────────────────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────────────────────┐
│               4. 内容提取 (Trafilatura)                      │
│            HTML → Text, Title, Links, Contacts              │
└─────────────────────┬───────────────────────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────────────────────┐
│              5. 快速匹配 (qwen3:0.6b)                        │
│           Content + Intent → Relevance Score                │
└─────────────────────┬───────────────────────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────────────────────┐
│              6. 深度分析 (qwen3:1.7b)                        │
│    Content → Key Findings, Data, Priority URLs (1-3)        │
└─────────────────────┬───────────────────────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────────────────────┐
│              7. URL队列更新                                  │
│          Priority URLs → Queue (sorted by priority)         │
└─────────────────────┬───────────────────────────────────────┘
                      │
              ┌───────┴───────┐
              │ 队列不为空?   │
              └───────┬───────┘
                      │ Yes
                      ▼
              ┌───────────────┐
              │ 循环回到步骤3 │
              └───────┬───────┘
                      │ No (队列空或达到max_pages)
                      ▼
┌─────────────────────────────────────────────────────────────┐
│              8. 报告生成                                     │
│         Results → Markdown Report + JSON Data               │
└─────────────────────────────────────────────────────────────┘
```

## 示例 / Examples

### 示例1: 爬取大学招生信息

```bash
python crawler.py \
    -u https://www.stanford.edu/ \
    -i "本科申请要求和截止日期" \
    --max-pages 30 \
    --max-depth 2
```

输出报告将包含:
- 申请截止日期
- 入学要求
- 所需材料
- 相关链接

### 示例2: 爬取企业联系信息

```bash
python crawler.py \
    -u https://company.com/ \
    -i "联系方式和办公地址" \
    --max-pages 20 \
    --no-selenium
```

### 示例3: 爬取新闻网站

```bash
python crawler.py \
    -u https://news.site.com/ \
    -i "科技新闻" \
    --max-pages 50 \
    --max-depth 1
```

## 开发指南 / Development

### 单模块测试

每个模块都有 `if __name__ == "__main__"` 测试块:

```bash
# 测试配置
python config.py

# 测试日志
python logger_config.py

# 测试工具函数
python utils.py

# 测试LLM客户端
python llm_client.py

# 测试浏览器引擎
python browser_engine.py

# 测试内容提取
python content_extractor.py

# 测试意图分析
python intent_analyzer.py

# 测试内容分析
python content_analyzer.py

# 测试文件命名
python file_namer.py

# 测试URL队列
python url_queue.py

# 测试存储管理
python storage_manager.py

# 测试报告生成
python report_generator.py
```

### 错误处理模式

所有模块使用统一的错误处理:

```python
def get_err_message() -> str:
    """获取当前异常的详细错误信息"""
    exc_type, exc_value, exc_tb = sys.exc_info()
    if exc_type is None:
        return "No exception"
    return f"{exc_type.__name__}: {exc_value} (line {exc_tb.tb_lineno})"
```

### 日志使用

```python
from loguru import logger

logger.debug("调试信息")
logger.info("一般信息")
logger.success("成功信息")
logger.warning("警告信息")
logger.error("错误信息")
```

## 注意事项 / Notes

1. **Ollama服务**: 确保Ollama服务运行在 `localhost:11434`
2. **模型下载**: 首次运行需要下载 qwen3:1.7b 和 qwen3:0.6b
3. **Chrome驱动**: Selenium模式需要Chrome浏览器,驱动会自动下载
4. **网络请求**: 请遵守目标网站的robots.txt和使用条款
5. **资源占用**: Selenium模式占用更多内存,建议合理设置max_pages

## 许可证 / License

MIT License

## 贡献 / Contributing

欢迎提交Issue和Pull Request!

---

*Built with ❤️ using CleanRL design philosophy*
