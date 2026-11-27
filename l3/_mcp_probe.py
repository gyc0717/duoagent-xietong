import json, subprocess, sys, time

PY = r"C:\Users\gyc20\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe"
SRV = r"D:\数据\deepseek-harness\default-workspace\multi-agent\l3\mcp_server.py"

p = subprocess.Popen([PY, SRV], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                     stderr=subprocess.PIPE, text=True, encoding="utf-8", bufsize=1)


def send(obj):
    p.stdin.write(json.dumps(obj) + "\n")
    p.stdin.flush()


def recv(timeout=60):
    line = p.stdout.readline()
    return json.loads(line) if line.strip() else None


send({"jsonrpc": "2.0", "id": 1, "method": "initialize",
      "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                 "clientInfo": {"name": "probe", "version": "0"}}})
print("init:", json.dumps(recv()["result"]["serverInfo"], ensure_ascii=False))

send({"jsonrpc": "2.0", "method": "notifications/initialized"})
send({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
tools = recv()["result"]["tools"]
print("tools:", [t["name"] for t in tools])

send({"jsonrpc": "2.0", "id": 3, "method": "tools/call",
      "params": {"name": "l3_task_status", "arguments": {}}})
r = recv()
txt = r["result"]["content"][0]["text"]
print("status ok:", "artifacts" in txt, "| isError:", r["result"].get("isError"))
print(txt[:200])

# 负向：P0 闸
send({"jsonrpc": "2.0", "id": 4, "method": "tools/call",
      "params": {"name": "l3_register",
                 "arguments": {"node": "N1Q", "role": "qwen_search", "name": "bad",
                               "payload": {"x": 1}, "trust_level": "untrusted",
                               "channel": "instruction"}}})
r = recv()
print("P0 gate:", r["result"]["content"][0]["text"][:80], "| isError:", r["result"].get("isError"))

# 硬垂询：不确认应当被拒
send({"jsonrpc": "2.0", "id": 5, "method": "tools/call",
      "params": {"name": "l3_publish", "arguments": {"confirm": False}}})
r = recv()
print("hard inquiry:", r["result"]["content"][0]["text"][:80], "| isError:", r["result"].get("isError"))

p.stdin.close()
p.terminate()
