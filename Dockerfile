# Thin runtime wrapper for deploying the official prebuilt OmniRoute image.
# This avoids rebuilding the large Next.js application on constrained Render builders.
FROM diegosouzapw/omniroute:latest

ENV PORT=20128 \
    HOSTNAME=0.0.0.0 \
    DATA_DIR=/app/data \
    REQUIRE_API_KEY=false

EXPOSE 20128
