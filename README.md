# ws-mcp

Wrap MCP servers with a WebSocket.

## Usage

```
# Example using fetch
uvx ws-mcp --command "uvx mcp-server-fetch" --port 3002

# Example using wcgw
## On macOS?
uvx ws-mcp --command "uvx --from wcgw@latest --python 3.12 wcgw_mcp" --port 3001

## On Ubuntu?
cd /tmp
git clone https://github.com/nick1udwig/wcgw.git
cd wcgw
git submodule update --init --recursive
git checkout hf/fix-wcgw-on-ubuntu
cd ..
uvx ws-mcp --command "uvx --from /tmp/wcgw --with /tmp/wcgw/src/mcp_wcgw --python 3.12 wcgw_mcp" --port 3001
```
