#!/bin/sh
# 啟動時把 config 複製到 OpenClaw 設定目錄
mkdir -p /root/.openclaw
cp /root/.openclaw-init/openclaw.json /root/.openclaw/openclaw.json
exec "$@"
