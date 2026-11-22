#!/usr/bin/env bash
# 汽水音乐脚本 · 一键运行
#
# 源自 https://github.com/wei6718189/qishuiAScriptProject （iOS 版，作者 wei6718189）
# Android 端为独立重写，仅沿用问题拆解与流程思路，代码不共享。
#
# 用法：
#   ./run.sh <手机IP>            启动并实时看日志
#   ./run.sh <手机IP> stop       停止

cd "$(dirname "$0")" || exit 1

if [ -z "$1" ]; then
  echo "用法: ./run.sh <手机IP> [stop]"
  echo "  手机IP 在 AScript App → 开发者选项 里查看（形如 192.168.1.20）"
  exit 1
fi

node run.js "$1" "${2:-run}"
