# lightweight python base image
FROM python:3.9-slim 

# cd /app, avoid mixing with other system files
# root directory is `/` of the new system
WORKDIR /app

# env var
# python print log real-time, for debugging
# RabbitMQ Address
# CLIENT_ID can be override by docker-compose.yml
ENV PYTHONUNBUFFERED=1 \
  BROKER_HOST=rabbitmq \
  MONITOR_DIR=/data \
  CLIENT_ID=unknown-client \
  TZ=Europe/Helsinki
# install system dependency
RUN apt-get update && apt-get install -y restic procps tzdata && rm -rf /var/lib/apt/lists/*

# explicitly copy to the container: /app/requirements.txt
COPY requirements.txt .
# delete whl after completion
RUN pip install --no-cache-dir -r requirements.txt

# copy all the code
# the same dockerfile
COPY . .

# data dir to be monitored
RUN mkdir -p /data

# for attacker node to invoke attacking
# I'm listening 5000!
EXPOSE 5000 8080 8000

# docker run -> automatically run `python client.py`
# if the script fails, the container stops
CMD ["python", "client.py"]
