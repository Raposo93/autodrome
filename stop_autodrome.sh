#!/bin/bash

# Stop backend
pkill -f 'uvicorn app:app' && echo "Backend stopped"

# Stop frontend (node process on port 5173)
frontend_pids=$(lsof -ti :5173)

if [ -n "$frontend_pids" ]; then
  for pid in $frontend_pids; do
    kill "$pid" && echo "Frontend process $pid killed"
  done
else
  echo "Frontend not running on port 5173"
fi
