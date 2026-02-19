from flask import Flask, jsonify, render_template
import json
import os
import requests

app = Flask(__name__)

# so index.html is automatically reloaded
app.config["TEMPLATES_AUTO_RELOAD"] = True
app.jinja_env.auto_reload = True

STATE_FILE = "/logs/system_state.json"


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/state")
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


# attack/normal
@app.route("/api/action/<target>/<action>", methods=["POST"])
def trigger_action(target, action):
    # target: finance1/finance2/finance3/finance4
    # action: attack/normal
    url = f"http://client-{target}:5000/{action}"
    try:
        # operation
        requests.post(url, timeout=2)
        return jsonify({"status": "success", "message": f"Sent {action} to {target}"})
    except Exception as e:
        print(f"Action failed: {e}")
        # return 200 anyway
        return jsonify({"status": "warning", "message": "Command sent (ignore timeout)"})


if __name__ == "__main__":
    print("🌐 Dashboard starting on port 8501...")
    app.run(host="0.0.0.0", port=8501)
