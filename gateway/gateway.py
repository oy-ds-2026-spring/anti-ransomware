from flask import Flask, request, jsonify
import requests
import random
from flasgger import Swagger
from dataclasses import dataclass, asdict
from typing import Optional

app = Flask(__name__)
Swagger(app)

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
class CreateReq:
    filename: str
    content: str = ""


@dataclass
class DeleteReq:
    filename: str


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
    """
    Read a file from one of the finance nodes.
    ---
    tags:
      - File Operations
    parameters:
      - in: body
        name: body
        required: true
        schema:
          type: object
          required:
            - filename
          properties:
            filename:
              type: string
              example: "contract_Flores_Inc.txt"
    responses:
      200:
        description: File content retrieved successfully
      400:
        description: Invalid request parameters
      500:
        description: Internal server error
    """
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
    """
    Write content to a file on the primary finance node (finance1).
    ---
    tags:
      - File Operations
    parameters:
      - in: body
        name: body
        required: true
        schema:
          type: object
          required:
            - filename
            - content
          properties:
            filename:
              type: string
              example: "contract_Flores_Inc.txt"
            content:
              type: string
              example: "Hello World"
    responses:
      200:
        description: File written successfully
      400:
        description: Invalid request parameters
      500:
        description: Internal server error
    """
    try:
        req = WriteReq(**request.get_json())
    except (TypeError, AttributeError):
        return jsonify(Response(error="Invalid request parameters").to_dict()), 400

    try:
        resp = requests.post("http://client-finance1:5000/write", json=asdict(req), timeout=10)
        return jsonify(resp.json()), resp.status_code
    except Exception as e:
        return jsonify(Response(error=str(e)).to_dict()), 500


# route to finance1 node(primary)
@app.route("/finance/create", methods=["POST"])
def create_op():
    """
    Create a new file on the primary finance node (finance1).
    ---
    tags:
      - File Operations
    parameters:
      - in: body
        name: body
        required: true
        schema:
          type: object
          required:
            - filename
          properties:
            filename:
              type: string
              example: "new_file.txt"
            content:
              type: string
              example: "Initial content"
    responses:
      200:
        description: File created successfully
      400:
        description: Invalid request parameters
      500:
        description: Internal server error
    """
    try:
        req = CreateReq(**request.get_json())
    except (TypeError, AttributeError):
        return jsonify(Response(error="Invalid request parameters").to_dict()), 400

    try:
        resp = requests.post("http://client-finance1:5000/create", json=asdict(req), timeout=10)
        return jsonify(resp.json()), resp.status_code
    except Exception as e:
        return jsonify(Response(error=str(e)).to_dict()), 500


# route to finance1 node(primary)
@app.route("/finance/delete", methods=["POST"])
def delete_op():
    """
    Delete a file on the primary finance node (finance1).
    ---
    tags:
      - File Operations
    parameters:
      - in: body
        name: body
        required: true
        schema:
          type: object
          required:
            - filename
          properties:
            filename:
              type: string
              example: "contract_Stephenson-Mcdonald.txt"
    responses:
      200:
        description: File deleted successfully
      400:
        description: Invalid request parameters
      500:
        description: Internal server error
    """
    try:
        req = DeleteReq(**request.get_json())
    except (TypeError, AttributeError):
        return jsonify(Response(error="Invalid request parameters").to_dict()), 400

    try:
        resp = requests.post("http://client-finance1:5000/delete", json=asdict(req), timeout=10)
        return jsonify(resp.json()), resp.status_code
    except Exception as e:
        return jsonify(Response(error=str(e)).to_dict()), 500


# route to finance1 node(primary)
@app.route("/finance/attack", methods=["GET"])
def attack_op():
    """
    Trigger an attack on the primary finance node (finance1).
    ---
    tags:
      - File Operations
    responses:
      200:
        description: Attack triggered successfully
      500:
        description: Internal server error
    """
    try:
        resp = requests.get("http://client-finance1:5000/attack", timeout=5)
        return jsonify(resp.json()), resp.status_code
    except Exception as e:
        return jsonify(Response(error=str(e)).to_dict()), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=9000)
