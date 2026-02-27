from flask import Flask, request, jsonify
import json
import os
import csv
app = Flask(__name__)

@app.route("/")
def index():
    return "Backup Server Coordinator"

FILE_OPERATION_LOG = "/logs/recovery_archive.csv"


# after every write operation, archive log for later backup
@app.route("/archive", methods=["POST"])
def archive():
    data = request.get_json()
    try:
        file_exists = os.path.exists(FILE_OPERATION_LOG)
        # Ensure fieldnames match the data sent by client
        fieldnames = ["uuid", "timestamp", "client_id", "filename", "operation", "appended"]

        with open(FILE_OPERATION_LOG, "a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            if not file_exists:
                writer.writeheader()
            writer.writerow(data)

        return jsonify({"status": "archived"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
bad = set(unhealthy_nodes)
healthy = [x for x in healthy if x not in bad]