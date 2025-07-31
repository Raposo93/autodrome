#!/bin/bash

# Parar backend
if [ -f /tmp/autodrome_backend.pid ]; then
  kill "$(cat /tmp/autodrome_backend.pid)" && echo "Backend detenido"
  rm /tmp/autodrome_backend.pid
else
  echo "PID del backend no encontrado"
fi

# Parar frontend
if [ -f /tmp/autodrome_frontend.pid ]; then
  kill "$(cat /tmp/autodrome_frontend.pid)" && echo "Frontend detenido"
  rm /tmp/autodrome_frontend.pid
else
  echo "PID del frontend no encontrado"
fi

