#!/bin/bash
cd /var/www/backend/alienedge-frontend
echo "Starting frontend at $(date)..."
npm start > /var/www/backend/output/frontend.log 2>&1 &
echo $! > /var/www/backend/output/frontend.pid
echo "Frontend started with PID $(cat /var/www/backend/output/frontend.pid)"
