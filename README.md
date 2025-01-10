# ws-mcp

Wrap MCP stdio servers with a WebSocket.
For use with [llm-chat](https://github.com/nick1udwig/llm-chat).

## Prerequisites

* uv

## Usage

```
# Example using fetch
uvx ws-mcp --command "uvx mcp-server-fetch" --port 3002

# Example using wcgw
## On macOS
uvx ws-mcp --command "uvx --from wcgw@latest --python 3.12 wcgw_mcp" --port 3001

## On Linux (or if you have issues on macOS with wcgw)
cd /tmp
git clone https://github.com/nick1udwig/wcgw.git
cd wcgw
git submodule update --init --recursive
git checkout hf/fix-wcgw-on-ubuntu
cd ..
uvx ws-mcp --command "uvx --from /tmp/wcgw --with /tmp/wcgw/src/mcp_wcgw --python 3.12 wcgw_mcp" --port 3001

# Example using Brave search
export BRAVE_API_KEY=YOUR_API_KEY_HERE
uvx ws-mcp --env BRAVE_API_KEY=$BRAVE_API_KEY --command "npx -y @modelcontextprotocol/server-brave-search" --port 3003

# Or, with a .env file:
uvx ws-mcp --env-file path/to/.env --command "npx -y @modelcontextprotocol/server-brave-search" --port 3003
```
