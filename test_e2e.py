"""端到端测试：调用 Flask API 解析小红书笔记"""
import json, sys, os, time

_root = os.path.dirname(os.path.abspath(__file__))
_backend_dir = os.path.join(_root, "backend")
if _backend_dir not in sys.path:
    sys.path.insert(0, _backend_dir)

import requests

API_URL = "http://127.0.0.1:5000/api/parse_links"
NOTE_URL = "https://www.xiaohongshu.com/explore/69ed8b790000000010001c00?xsec_token=AB_snpvFy1z6wj-BhbHeCfU5maPSyvo3tFDiSqCtrcJ1o=&xsec_source=pc_feed"
COOKIE = "abRequestId=c00ad973-e7b8-5477-a3ed-b90a3f77b13d; xsecappid=xhs-pc-web; a1=1973de7d9ed5zznr9orgloyg5cjptfv26jsgfyr1e50000289146; webId=5fecd3b0644ffba145ba7c9001b073df; gid=yjWqfdWdDJKfyjWqfdWfjVvFdf2uuIFjlFk1Mydlvk2SVk28U9ihJi888JYjy4K88JKJjqDS; ets=1777139511036; web_session=040069b042f07c5bf92a01b7d93b4b12b8cef7; id_token=VjEAAEf6iY4vfycc9xiJl/UFsP1CrxsA3wjz/2E60MTXigY8mjW5vzDZsBRJYhimxpd3mvwcL3gipTgPw4aV2sUBL5+S/wie3W6IQGKNVYxMlCKI9Ql72mUFtSzEDzumC/37oQli; webBuild=6.7.4; loadts=1777254007134; websectiga=16f444b9ff5e3d7e258b5f7674489196303a0b160e16647c6c2b4dcb609f4134; sec_poison_id=fa744b93-fb6a-4472-89af-407b9353b7ef"

payload = {
    "links": [NOTE_URL],
    "platform": "xiaohongshu",
    "xhs_cookie": COOKIE
}

print(f"Calling: {API_URL}")
print(f"Payload: links={payload['links']}, platform={payload['platform']}")
print("-" * 60)

try:
    r = requests.post(API_URL, json=payload, timeout=120)
    print(f"Status: {r.status_code}")
    data = r.json()
    print(f"Response: {json.dumps(data, ensure_ascii=False, indent=2)[:3000]}")
except requests.exceptions.ConnectionError as e:
    print(f"ERROR: Flask server not running at {API_URL}")
    print("Start with: .\\venv\\Scripts\\python backend\\app.py")
except Exception as e:
    print(f"ERROR: {e}")
