#!/bin/bash
cd ~/agentes
git pull origin main
sudo docker compose up -d --build
echo "✓ Actualizado"
