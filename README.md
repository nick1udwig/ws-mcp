# ws-mcp

Wrap MCP stdio servers with a WebSocket.
For use with [kibitz](https://github.com/nick1udwig/kibitz).

## Quickstart

### Prerequisites

1. Install [uv](https://github.com/astral-sh/uv):
   ```bash
   curl -LsSf https://astral.sh/uv/install.sh | sh
   ```

### Configuration

1. Create your configuration file:
   ```bash
   cp sample.config.json config.json
   ```

2. The config file specifies which MCP servers to run. The sample config includes:
   - `wcgw`: For general system operations and file management
   - `fetch`: For making HTTP requests

3. You can modify `config.json` to add or remove servers based on your needs.

### Running ws-mcp

Basic usage with config file:
```bash
uvx --refresh --from . ws-mcp --config config.json --port 3001
```

This will start all configured servers on the specified port.

## Detailed Usage

```bash
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

# `--command` can be supplied multiple times!
#  Example serving multiple servers at once:
uvx ws-mcp --env-file path/to/.env --command "npx -y @modelcontextprotocol/server-brave-search" --command "uvx mcp-server-fetch" --port 3004

# Servers can also be specified in a `.json` file following [the standard MCP format](https://modelcontextprotocol.io/quickstart/user#2-add-the-filesystem-mcp-server)
uvx ws-mcp --env-file path/to/.env --config path/to/config.json --port 3005
```
