#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Web Automation Tool - 简易运行脚本
Easy-to-use entry point for the web automation tool.

Usage:
    python run.py                                    # 使用默认配置
    python run.py -u https://example.com -i "信息"  # 自定义URL和意图
    python run.py --help                            # 查看帮助
"""

import sys
import os

# 添加当前目录到路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from crawler import main

if __name__ == "__main__":
    sys.exit(main())
