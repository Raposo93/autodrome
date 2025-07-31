#!/bin/bash

# Lanzar backend en segundo plano y guardar su PID
(
  cd ~/git/autodrome || exit 1
  source ~/.python_venv/autodrome_env/bin/activate
  nohup uvicorn app:app --reload --host 0.0.0.0 --port 5000 > /tmp/autodrome_backend.log 2>&1 &
  echo $! > /tmp/autodrome_backend.pid
)

# Lanzar frontend en segundo plano y guardar su PID
(
  cd ~/git/autodrome/frontend || exit 1
  nohup npm run dev > /tmp/autodrome_frontend.log 2>&1 &
  echo $! > /tmp/autodrome_frontend.pid
)

echo "Autodrome backend and frontend started in the background."
