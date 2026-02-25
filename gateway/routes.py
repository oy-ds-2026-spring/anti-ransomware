from flask import Flask, request, jsonify
import requests
import os
import random
import uuid
from flasgger import Swagger
from dataclasses import dataclass, asdict
from typing import Optional
import sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from logger import Logger


# whether gateway uses kerberos key depends on
# `whether lib requests_gssapi is installed`
# for debugging
try:
    from requests_gssapi import HTTPSPNEGOAuth
except ImportError:
    HTTPSPNEGOAuth = None

app = Flask(__name__)
Swagger(app)

FINANCE_NODES = [
    "client-finance1",
    "client-finance2",
    "client-finance3",
    "client-finance4",
]

# Kerberos Auth Object
krb_auth = HTTPSPNEGOAuth() if HTTPSPNEGOAuth else None


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

# remember who's the primary, default finance1
CURRENT_PRIMARY = FINANCE_NODES[0]

def _send_to_primary(endpoint, method="POST", json_data=None):
    global CURRENT_PRIMARY
    
    try:
        url = f"http://{CURRENT_PRIMARY}:5000{endpoint}"
        
        if method == "POST":
            resp = requests.post(url, json=json_data, timeout=3, auth=krb_auth)
        else:
            resp = requests.get(url, timeout=3, auth=krb_auth)
        
        # if primary is alive
        if resp.status_code < 500:
            return resp
        
        # 500: primary internal error, maybe ransomware
        raise Exception(f"Primary {CURRENT_PRIMARY} returned {resp.status_code}")
    except Exception as e:
        Logger.error(f"Current primary node {CURRENT_PRIMARY} is down: {e}")        
    
    # current primary dead, find next primary node
    for node in FINANCE_NODES:
        if node == CURRENT_PRIMARY:
            continue # it's already dead
            
        try:
            url = f"http://{node}:5000{endpoint}"
            
            if method == "POST":
                resp = requests.post(url, json=json_data, timeout=3, auth=krb_auth)
            else:
                resp = requests.get(url, timeout=3, auth=krb_auth)
            
            # designate this one as new primary
            if resp.status_code < 500:
                CURRENT_PRIMARY = node
                Logger.done(f"Election success, new primary is {CURRENT_PRIMARY}")
                return resp
                
        except Exception:
            continue
    
    # no one alive
    raise Exception("All finance nodes are down!")

# read: retry, until every client is confirmed dead
def _send_to_any(endpoint, method="POST", json_data=None, timeout=3):
    nodes = list(FINANCE_NODES)
    random.shuffle(nodes)
    
    last_error = None
    
    for node in nodes:
        try:
            url = f"http://{node}:5000{endpoint}"
            
            if method == "POST":
                resp = requests.post(url, json=json_data, timeout=timeout, auth=krb_auth)
            else:
                resp = requests.get(url, timeout=timeout, auth=krb_auth)
            
            if resp.status_code < 500:
                return resp
        except Exception as e:
            last_error = e
            continue
    
    raise last_error if last_error else Exception("All finance nodes are down")

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

    try:
        resp = _send_to_any("/read", method="POST", json_data=asdict(req))
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
        # give global unique ID to a write request
        payload = asdict(req)
        payload["request_id"] = str(uuid.uuid4())
        Logger.info(payload["request_id"])
        resp = _send_to_primary("/write", method="POST", json_data=payload)
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
        # give global unique ID to a write request
        payload = asdict(req)
        payload["request_id"] = str(uuid.uuid4())
        resp = _send_to_primary("/create", method="POST", json_data=payload)
        return jsonify(resp.json()), resp.status_code
    except Exception as e:
        return jsonify(Response(error=str(e)).to_dict()), 500


# route to finance1234 node for HTML browsing
@app.route("/browse", defaults={"req_path": ""})
@app.route("/browse/<path:req_path>")
def browse_fs(req_path):
    """
    Browse file system (HTML) via Gateway.
    ---
    tags:
      - File Browser
    parameters:
      - in: path
        name: req_path
        type: string
        required: false
        description: The path to browse (relative to monitor dir)
    responses:
      200:
        description: HTML content of the directory listing or file content
      403:
        description: Forbidden
      404:
        description: Not Found
      500:
        description: Internal server error
    """
    endpoint = f"/browse/{req_path}" if req_path else "/browse"

    try:
        resp = _send_to_any(endpoint, method="GET", timeout=5)
        return resp.content, resp.status_code
    except Exception as e:
        return f"Gateway Error: {e}", 500


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
        # give global unique ID to a write request
        payload = asdict(req)
        payload["request_id"] = str(uuid.uuid4())
        resp = _send_to_primary("/delete", method="POST", json_data=payload)
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
        resp = _send_to_primary("/attack", method="GET")
        return jsonify(resp.json()), resp.status_code
    except Exception as e:
        return jsonify(Response(error=str(e)).to_dict()), 500
