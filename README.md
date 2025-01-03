# ws-mcp

Wrap MCP servers with a WebSocket.

## Usage

```
# Example using wcgw

git clone https://github.com/nick1udwig/wcgw.git
cd wcgw
git submodule update --init --recursive
git checkout hf/fix-wcgw-on-ubuntu
cd ..

git clone https://github.com/nick1udwig/ws-mcp.git
cd ws-mcp

python3 ws-mcp.py --command "uv tool run --from /home/nick/git/wcgw --with /home/nick/git/wcgw/src/mcp_wcgw --python 3.12 wcgw_mcp" --port 3001
```
