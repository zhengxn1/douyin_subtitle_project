"""测试 xsec_token + 完整 headers"""
import json, sys, os

_root = os.path.dirname(os.path.abspath(__file__))
_backend_dir = os.path.join(_root, "backend")
if _backend_dir not in sys.path:
    sys.path.insert(0, _backend_dir)

import requests

cookie = "abRequestId=c00ad973-e7b8-5477-a3ed-b90a3f77b13d; xsecappid=xhs-pc-web; a1=1973de7d9ed5zznr9orgloyg5cjptfv26jsgfyr1e50000289146; webId=5fecd3b0644ffba145ba7c9001b073df; gid=yjWqfdWdDJKfyjWqfdWfjVvFdf2uuIFjlFk1Mydlvk2SVk28U9ihJi888JYjy4K88JKJjqDS; ets=1777139511036; web_session=040069b042f07c5bf92a01b7d93b4b12b8cef7; id_token=VjEAAEf6iY4vfycc9xiJl/UFsP1CrxsA3wjz/2E60MTXigY8mjW5vzDZsBRJYhimxpd3mvwcL3gipTgPw4aV2sUBL5+S/wie3W6IQGKNVYxMlCKI9Ql72mUFtSzEDzumC/37oQli; webBuild=6.7.4; loadts=1777254007134; websectiga=16f444b9ff5e3d7e258b5f7674489196303a0b160e16647c6c2b4dcb609f4134; sec_poison_id=fa744b93-fb6a-4472-89af-407b9353b7ef"
note_id = "69ed8b790000000010001c00"
xsec_token = "AB_snpvFy1z6wj-BhbHeCfU5maPSyvo3tFDiSqCtrcJ1o="

headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Referer": f"https://www.xiaohongshu.com/explore/{note_id}",
    "Cookie": cookie,
    "x-xray-token": xsec_token,
    "sec-ch-ua": '"Not_A Brand";v="8", "Chromium";v="120", "Google Chrome";v="120"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-origin",
}

# API 端点（yt-dlp 使用的）
api_url = f"https://www.xiaohongshu.com/api/sns/web/v1/feed"
params = {
    "source": "note",
    "item_id": note_id,
    "image_formats": "jpg,webp,avif",
    "extra": "{}",
    "xhs_content_need_hash": "1",
}

print(f"=== Testing feed API with xsec_token ===")
r = requests.get(api_url, headers=headers, params=params, timeout=15)
print(f"Status: {r.status_code}")
print(f"Content-Type: {r.headers.get('content-type')}")
print(f"Response: {r.text[:1000]}")

# 也试试 note detail API
print(f"\n=== Testing note detail API ===")
api2 = f"https://www.xiaohongshu.com/api/sns/web/v1/note/{note_id}"
r2 = requests.get(api2, headers=headers, timeout=15)
print(f"Status: {r2.status_code}")
print(f"Response: {r2.text[:1000]}")
