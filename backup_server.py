import http.server
import socketserver
import os

PORT = 8000
os.makedirs("/data", exist_ok=True)
os.chdir("/data")

Handler = http.server.SimpleHTTPRequestHandler
with socketserver.TCPServer(("", PORT), Handler) as httpd:
    print(f"💾 Immutable Backup Storage serving at port {PORT}")
    httpd.serve_forever()
