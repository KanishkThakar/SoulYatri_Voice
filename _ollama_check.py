import json
import httpx

SYS = "You are SoulYatri, a warm assistant. Keep responses under 50 words."
payload = {
    "model": "qwen3:8b",
    "messages": [
        {"role": "system", "content": SYS},
        {"role": "user", "content": "How are we going to do that?"},
    ],
    "stream": True,
    "options": {"temperature": 0.7, "top_p": 0.9, "num_predict": 150},
}

print("=== /api/chat (STREAM, like the server) ===")
content_chars = 0
thinking_chars = 0
try:
    with httpx.stream("POST", "http://localhost:11434/api/chat", json=payload, timeout=120.0) as r:
        print("STATUS", r.status_code)
        if r.status_code != 200:
            print("BODY", r.read().decode("utf-8", "replace")[:2000])
        else:
            for line in r.iter_lines():
                if not line.strip():
                    continue
                data = json.loads(line)
                msg = data.get("message", {})
                content_chars += len(msg.get("content", "") or "")
                thinking_chars += len(msg.get("thinking", "") or "")
                if data.get("done"):
                    print("DONE reason:", data.get("done_reason"))
                    break
            print("CONTENT chars:", content_chars, "| THINKING chars:", thinking_chars)
except Exception as e:
    print("EXC", type(e).__name__, str(e))
