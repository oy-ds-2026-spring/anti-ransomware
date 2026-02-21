from flask import Flask, jsonify, render_template, request
import json
import os
import requests
import logging

app = Flask(__name__)

# so index.html is automatically reloaded
app.config["TEMPLATES_AUTO_RELOAD"] = True
app.jinja_env.auto_reload = True

STATE_FILE = "/logs/system_state.json"
POSITIONS_FILE = "./node_positions.json"


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/dashboard/state")
def get_state():
    # read log
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r") as f:
                return jsonify(json.load(f))
        except json.JSONDecodeError:
            pass

    # if no state_file
    return jsonify(
        {
            "finance1": "Safe",
            "finance2": "Safe",
            "finance3": "Safe",
            "finance4": "Safe",
            "last_entropy": 0.0,
            "logs": ["System initialized. Waiting for events..."],
            "processing_logs": [],
            "entropy_history": [],
        }
    )


@app.route("/dashboard/positions", methods=["GET"])
def get_positions():
    if os.path.exists(POSITIONS_FILE):
        try:
            with open(POSITIONS_FILE, "r") as f:
                return jsonify(json.load(f))
        except Exception:
            pass
    return jsonify({})


@app.route("/dashboard/positions", methods=["POST"])
def save_positions():
    try:
        data = request.get_json()
        with open(POSITIONS_FILE, "w") as f:
            json.dump(data, f)
        return jsonify({"status": "success"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


# attack/normal
@app.route("/dashboard/attack", methods=["GET"])
def trigger_action():
    """
    Trigger an attack simulation via the gateway.

    This endpoint sends a request to the finance-gateway to initiate an attack
    on the primary finance node. It is used by the frontend dashboard to
    simulate a ransomware attack.

    Returns:
        JSON response indicating the status of the command transmission.
    """
    # target: gateway
    # action: attack/normal
    url = f"http://finance-gateway:9000/finance/attack"
    try:
        # operation
        requests.get(url, timeout=2)
        return jsonify({"status": "success", "message": f"Sent attack to gateway"})
    except Exception as e:
        print(f"Action failed: {e}")
        # return 200 anyway
        return jsonify({"status": "warning", "message": "Command sent (ignore timeout)"})


if __name__ == "__main__":
    # disable default Flask/Werkzeug logging
    log = logging.getLogger("werkzeug")
    log.setLevel(logging.ERROR)

    print("🌐 Dashboard starting on port 8501...")
    app.run(host="0.0.0.0", port=8501)
