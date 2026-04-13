#!/bin/bash
source venv/bin/activate
nohup python3 server.py > server.log 2>&1 &
echo "Servidor iniciado em background (veja server.log)"
