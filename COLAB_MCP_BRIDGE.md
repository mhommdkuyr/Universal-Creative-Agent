# Google Colab MCP Bridge

This service exposes a protected Streamable HTTP MCP endpoint and maintains an authenticated outbound WebSocket from a live Colab runtime.

## Render setup

Create a Python Web Service from this repository using branch `colab-mcp-bridge`.

- Build command: `pip install -r requirements-colab-bridge.txt`
- Start command: `uvicorn colab_bridge_server:app --host 0.0.0.0 --port $PORT`
- Health check path: `/healthz`
- Environment variables (use fresh random values; do not commit them):
  - `MCP_BEARER_TOKEN`: long random secret for MCP HTTP requests
  - `AGENT_BEARER_TOKEN`: different long random secret for the Colab WebSocket client

The MCP URL is `https://YOUR-RENDER-SERVICE.onrender.com/mcp`. Send `Authorization: Bearer <MCP_BEARER_TOKEN>` with MCP requests.

## Colab client

Use the code template in `colab_mcp_client.py`. In Colab, replace the WebSocket URL with `wss://YOUR-RENDER-SERVICE.onrender.com/agent/ws`, and put the value of `AGENT_BEARER_TOKEN` into the cell. Run the cell and keep it running.

## Available tools

- `colab_status` — inspect whether the notebook client is connected
- `colab_run_python` — execute Python in the connected notebook's global namespace
- `colab_list_files` — list items under `/content`
- `colab_read_file` — read UTF-8 text files under `/content` up to 1 MiB

**Security:** This allows remote Python execution in your active Colab runtime. Keep both tokens secret, only connect trusted MCP clients, and stop the Colab client cell when you are finished. Do not mount sensitive Drive folders unless needed.
