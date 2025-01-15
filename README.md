# ws-mcp

Wrap MCP stdio servers with a WebSocket.
For use with [kibitz](https://github.com/nick1udwig/kibitz).

## Prerequisites

* [uv](https://github.com/astral-sh/uv)

## Usage

```bash
# Example using fetch
uvx --from . ws-mcp --command "uvx mcp-server-fetch" --port 3002

# Example using wcgw
## On macOS
uvx --from . ws-mcp --command "uvx --from wcgw@latest --python 3.12 wcgw_mcp" --port 3001

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

### Example MCP configuration file

```json
{
  "mcpServers": {
    "wcgw": {
      "command": "uvx",
      "args": [
        "wcgw@latest",
        "--python",
        "3.12",
        "wcgw_mcp"
      ]
    },
    "fetch": {
      "command": "uvx",
      "args": [
        "mcp-server-fetch"
      ]
    },
    "brave-search": {
      "command": "npx",
      "args": [
        "-y",
        "@modelcontextprotocol/server-brave-search"
      ]
    }
  }
}
```
