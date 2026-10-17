"""Quick 3-second diagnostic test for SparkProxy before full crawl."""

import argparse
import sys
import time
from curl_cffi import requests

def main():
    parser = argparse.ArgumentParser(description="Test SparkProxy connectivity and ask.39.net bypass")
    parser.add_argument("--host", default="gateway.sparkproxy.io", help="Proxy host (default: gateway.sparkproxy.io)")
    parser.add_argument("--port", type=int, default=11000, help="Proxy port (default: 11000)")
    parser.add_argument("--user", required=True, help="Proxy username")
    parser.add_argument("--password", required=True, help="Proxy password")
    args = parser.parse_args()

    proxy_url = f"http://{args.user}:{args.password}@{args.host}:{args.port}"
    print(f"Connecting to SparkProxy at {args.host}:{args.port}...")

    # Test 1: Check IP and egress country
    try:
        t0 = time.time()
        r_ip = requests.get("https://api.ipify.org?format=json", proxies={"http": proxy_url, "https": proxy_url}, timeout=8)
        elapsed = time.time() - t0
        print(f"✅ Kết nối Proxy thành công! IP xuất phát: {r_ip.json().get('ip')} ({elapsed:.2f}s)")
    except Exception as e:
        print(f"❌ Lỗi kết nối Proxy: {e}")
        sys.exit(1)

    # Test 2: Check target site ask.39.net
    target_url = "https://ask.39.net/question/30422129.html"
    print(f"Thử nghiệm gửi request tới {target_url}...")
    try:
        t0 = time.time()
        r = requests.get(
            target_url,
            proxies={"http": proxy_url, "https": proxy_url},
            impersonate="chrome124",
            timeout=10
        )
        elapsed = time.time() - t0
        print(f"Status Code: {r.status_code} ({elapsed:.2f}s)")
        print(f"URL trả về: {r.url}")
        print(f"Dung lượng HTML: {len(r.text)} bytes")

        if "verify.html" in r.url or "滑动拼图验证" in r.text:
            print("⚠️ CẢNH BÁO: Bị Tencent WAF Captcha chặn!")
            sys.exit(2)
        elif r.status_code == 200 and "医生" in r.text:
            print("🎉 HOÀN TOÀN THÀNH CÔNG! Đã vượt qua Tencent WAF, trích xuất được phác đồ bác sĩ.")
            print("👉 SẴN SÀNG KÍCH HOẠT CRAWLER 220 WORKERS!")
        else:
            print(f"⚠️ Nhận mã HTTP {r.status_code}, kiểm tra lại nội dung.")
    except Exception as e:
        print(f"❌ Lỗi gửi request tới ask.39.net: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
