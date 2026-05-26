#!/usr/bin/env python3
"""
deepseek_proxy.py — Local HTTP proxy for DeepSeek API

Captures /chat/completions usage data from API responses and
writes token counts to the SQLite database consumed by deepseekMonitor.py.

Usage:
    python deepseek_proxy.py --api-key sk-xxx
    # Then configure your DeepSeek client to use:
    #   base_url: http://localhost:7654

No third-party dependencies (stdlib only).
"""

import argparse
import json
import os
import sqlite3
import sys
import urllib.request
import urllib.error
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from socketserver import ThreadingMixIn

DEEPSEEK_HOST = "api.deepseek.com"
DEFAULT_DB_PATH = Path.home() / ".deepseek_usage.db"
DEFAULT_PORT = 7654


def log_usage(usage: dict, db_path: str):
    """Extract token usage from a /chat/completions response and write to SQLite."""
    if not usage:
        return
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS usage_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT,
                input_tokens INTEGER,
                output_tokens INTEGER,
                cache_hit_tokens INTEGER,
                cache_miss_tokens INTEGER,
                total_tokens INTEGER
            )
        """)
        conn.execute(
            """
            INSERT INTO usage_log (timestamp, input_tokens, output_tokens,
                                    cache_hit_tokens, cache_miss_tokens, total_tokens)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                datetime.now().isoformat(),
                usage.get("prompt_tokens", 0),
                usage.get("completion_tokens", 0),
                usage.get("prompt_cache_hit_tokens", 0),
                usage.get("prompt_cache_miss_tokens", 0),
                usage.get("total_tokens", 0),
            ),
        )
        conn.commit()
    finally:
        conn.close()


def extract_usage_from_sse(body: bytes) -> dict:
    """Parse SSE response body for the final usage object (before [DONE])."""
    text = body.decode("utf-8", errors="replace")
    usage = None
    for part in text.split("\n\n"):
        for line in part.split("\n"):
            if line.startswith("data: "):
                payload = line[6:].strip()
                if payload == "[DONE]":
                    continue
                try:
                    obj = json.loads(payload)
                    if "usage" in obj:
                        usage = obj["usage"]
                except json.JSONDecodeError:
                    pass
    return usage


class ProxyHandler(BaseHTTPRequestHandler):
    """Handles incoming HTTP requests and proxies them to api.deepseek.com."""

    def do_GET(self):
        self._forward()

    def do_POST(self):
        self._forward()

    def do_DELETE(self):
        self._forward()

    def do_PATCH(self):
        self._forward()

    def _forward(self):
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length) if content_length > 0 else b""

        url = f"https://{DEEPSEEK_HOST}{self.path}"

        req = urllib.request.Request(url, data=body or None, method=self.command)
        for key, value in self.headers.items():
            if key.lower() not in ("host", "connection", "content-length",
                                   "transfer-encoding", "accept-encoding"):
                req.add_header(key, value)

        try:
            resp = urllib.request.urlopen(req)
            resp_body = resp.read()
            status = resp.status
            resp_headers = resp.headers
        except urllib.error.HTTPError as e:
            resp_body = e.read()
            status = e.code
            resp_headers = e.headers

        # Capture usage from /chat/completions responses
        if self.command == "POST" and "/chat/completions" in self.path and status == 200:
            req_body_str = body.decode("utf-8", errors="replace")
            try:
                req_json = json.loads(req_body_str)
                stream = req_json.get("stream", False)
            except json.JSONDecodeError:
                stream = False

            if stream:
                usage = extract_usage_from_sse(resp_body)
                if usage:
                    log_usage(usage, self.server.db_path)
            else:
                try:
                    data = json.loads(resp_body)
                    if "usage" in data:
                        log_usage(data["usage"], self.server.db_path)
                except json.JSONDecodeError:
                    pass

        # Send response back to client
        self.send_response(status)
        excluded_keys = {"transfer-encoding", "content-encoding", "alt-svc"}
        for key, value in resp_headers.items():
            if key.lower() not in excluded_keys:
                self.send_header(key, value)
        self.send_header("Content-Length", str(len(resp_body)))
        self.end_headers()
        self.wfile.write(resp_body)

    def log_message(self, fmt, *args):
        sys.stderr.write(f"[{datetime.now().strftime('%H:%M:%S')}] {args[0]} {args[1]} {args[2]}\n")


class ThreadedProxyServer(ThreadingMixIn, HTTPServer):
    allow_reuse_address = True
    daemon_threads = True


def main():
    parser = argparse.ArgumentParser(
        description="DeepSeek API Local Proxy — captures token usage to SQLite")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT,
                        help=f"Listen port (default: {DEFAULT_PORT})")
    parser.add_argument("--api-key",
                        help="DeepSeek API key (default: DEEPSEEK_API_KEY env var)")
    parser.add_argument("--db-path", default=str(DEFAULT_DB_PATH),
                        help=f"SQLite database path (default: {DEFAULT_DB_PATH})")
    args = parser.parse_args()

    api_key = args.api_key or os.environ.get("DEEPSEEK_API_KEY")
    if not api_key:
        print("❌ DEEPSEEK_API_KEY not set. Provide via --api-key or environment variable.")
        sys.exit(1)

    db_path = Path(args.db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    server = ThreadedProxyServer(("127.0.0.1", args.port), ProxyHandler)
    server.db_path = str(db_path)

    print(f"🚀 DeepSeek Proxy running on http://127.0.0.1:{args.port}")
    print(f"📁 Usage DB: {db_path}")
    masked_key = f"***{api_key[-4:]}" if len(api_key) > 4 else "***"
    print(f"🔑 API Key: {masked_key}")
    print()
    print("Configure your DeepSeek client with:")
    print(f"  base_url = http://127.0.0.1:{args.port}")
    print()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down...")
        server.shutdown()


if __name__ == "__main__":
    main()
