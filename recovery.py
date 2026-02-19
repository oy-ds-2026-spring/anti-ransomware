from flask import Flask

app = Flask(__name__)


@app.route("/")
def home():
    return "hello"


if __name__ == "__main__":
    print("recovery listening")
    app.run(host="0.0.0.0", port=8080)
