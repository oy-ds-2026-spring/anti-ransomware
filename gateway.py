from flask import Flask, request, jsonify
import requests
import random
from dataclasses import dataclass, asdict
from typing import Optional

app = Flask(__name__)

FINANCE_NODES = [
    "client-finance1",
    "client-finance2",
    "client-finance3",
    "client-finance4",
]


@dataclass
class ReadReq:
    filename: str


@dataclass
class WriteReq:
    filename: str
    content: str


@dataclass
class Response:
    status: Optional[str] = None
    content: Optional[str] = None
    message: Optional[str] = None
    error: Optional[str] = None

    def to_dict(self):
        return {k: v for k, v in asdict(self).items() if v is not None}


# route to finance1234 node
@app.route("/finance/read", methods=["POST"])
def read_op():
    try:
        req = ReadReq(**request.get_json())
    except (TypeError, AttributeError):
        return jsonify(Response(error="Invalid request parameters").to_dict()), 400

    # randomly select one node
    target = random.choice(FINANCE_NODES)
    try:
        payload = asdict(req)
        resp = requests.post(f"http://{target}:5000/read", json=payload, timeout=3)
        return jsonify(resp.json()), resp.status_code
    except Exception as e:
        return jsonify(Response(error=str(e)).to_dict()), 500


# route to finance1 node(primary)
@app.route("/finance/write", methods=["POST"])
def write_op():
    try:
        req = WriteReq(**request.get_json())
    except (TypeError, AttributeError):
        return jsonify(Response(error="Invalid request parameters").to_dict()), 400

    try:
        resp = requests.post("http://client-finance1:5000/write", json=asdict(req), timeout=10)
        return jsonify(resp.json()), resp.status_code
    except Exception as e:
        return jsonify(Response(error=str(e)).to_dict()), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=9000)
