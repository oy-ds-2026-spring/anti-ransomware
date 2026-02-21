1. Python 3.9 is needed
2. `pip install -r requirements.txt`
3. `docker-compose up --build`


compile protobuf files:
```cmd
python -m grpc_tools.protoc \
  -I./proto \
  --python_out=./common \
  --grpc_python_out=./common \
  ./proto/lockdown.proto
```
