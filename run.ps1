# 汽水音乐脚本 · 一键运行
#
# 用法：
#   .\run.ps1 <手机IP>            启动并实时看日志
#   .\run.ps1 <手机IP> stop       停止

param(
    [string]$PhoneIp = "",
    [string]$Action = "run"
)

if (-not $PhoneIp) {
    Write-Host "用法: .\run.ps1 <手机IP> [stop]"
    Write-Host "  手机IP 在 AScript App -> 开发者选项 里查看（形如 192.168.1.20）"
    exit 1
}

Set-Location $PSScriptRoot
node run.js $PhoneIp $Action
