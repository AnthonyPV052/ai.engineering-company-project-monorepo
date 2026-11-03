#!/bin/sh
set -e

echo "Starting Next.js application..."
if [ ! -f "/app/uis/website/.next/BUILD_ID" ]; then
  echo "No production build found — running build..."
  npm run build
fi
npm run start