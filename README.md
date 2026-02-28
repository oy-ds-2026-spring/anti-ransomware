# Distributed Systems Course Project: anti-ransomware

## 📚 Introduction

<p align="center">Anti-ramsomware Distributed Model<br>
🚀Constructed with🚀<br>
    <img alt="Static Badge" src="https://img.shields.io/badge/Python-3.9-blue">
    <img alt="Static Badge" src="https://img.shields.io/badge/Docker-29.2-0077b6">
    <img alt="Static Badge" src="https://img.shields.io/badge/RabbitMQ-3-ca6702">
    <img alt="Static Badge" src="https://img.shields.io/badge/Restic_Server-latest-a3b18a">
    <img alt="Static Badge" src="https://img.shields.io/badge/Flask-2.3-669bbc">
</p>

<br>

### 🔖 High Lights

**1. Introduction**: Simple single-node file monitor to detect suspicious file modifications.

**2. Communication**: Event streaming from multiple endpoints monitoring file changes.

**3. Time & Consensus**: Sequence file changes, consensus on system “clean” state snapshots.

**4. Non-Functional Reqs**: Low-latency detection, minimal overhead on file writes.

**5. Replication & Consistency**: Replicated file system to store and restore.

**6. System Architecture**: Microservices: monitoring agents, detection engine, recovery manager.

**7. Distributed ML**: Real-time anomaly detection for malicious encryption signatures.

**8. Edge–Cloud Continuum**: Local edge monitoring for immediate threat detection, cloud-based global rollback orchestration.

<br>

### 🗺️ Project Structure

![pasted-image-1772227482389.webp](https://files.seeusercontent.com/2026/02/27/Z2tk/pasted-image-1772227482389.webp)

<br>

## 🛠️ Deployment

> [!IMPORTANT]
>
> We use <img alt="Static Badge" src="https://img.shields.io/badge/Python-3.9-blue">, other versions might not be supported

### 1. 🐍 Locally

If you want to run each component locally, you can install all the needed packages via

```shell
pip install -r requirements.txt
```

And to compile protobuf files:

```cmd
python -m grpc_tools.protoc \
  -I./proto \
  --python_out=./common \
  --grpc_python_out=./common \
  ./proto/lockdown.proto
```



#### 2. 🐋 Via Docker

We also have an configured docker compose, in project root, please run

```shell
docker-compose up --build
```



## ⚙️ How to use

After deploying, visit the project's dashboard at:

```
http://localhost:8501/
```

You can click on the `Attack` button to simulate attack behaviors on the system.



## 📒 ProDetails

See [<b>detail.md</b>](docs/detail.md) for more information