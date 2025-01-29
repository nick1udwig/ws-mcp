# ws-mcp

Wrap MCP stdio servers with a WebSocket.
For use with [kibitz](https://github.com/nick1udwig/kibitz).

## Quickstart

### Prerequisites

Install [uv](https://github.com/astral-sh/uv):
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

### Configuration

The config file specifies which MCP servers to run.
The default config (no `--config` or `--command` args provided) includes:
- [`wcgw`](https://github.com/rusiaaman/wcgw): For general system operations and file management
- [`fetch`](https://github.com/modelcontextprotocol/servers/tree/main/src/fetch): For making HTTP requests

To make a configuration file:

1. Create your configuration file:
   ```bash
   cp sample.config.json config.json
   ```
2. Modify `config.json` to add or remove servers based on your needs.
3. Run with `--config path/to/config.json` to use the new config file.

### Running ws-mcp

Basic usage with default config file (no `--config` or `--command` provided) and port:
```bash
uvx --refresh ws-mcp@latest
```

This will start all configured servers on the default port (`10125`).

To use a config file and port:
```bash
uvx --refresh ws-mcp@latest --config path/to/config --port 10125
```

## Detailed Usage

```bash
# Example using fetch
uvx --refresh ws-mcp --command "uvx mcp-server-fetch" --port 3002

# Example using wcgw
## On macOS
uvx --refresh ws-mcp --command "uvx --from wcgw@latest --python 3.12 wcgw_mcp" --port 3001

## On Linux (or if you have issues on macOS with wcgw)
cd /tmp
git clone https://github.com/nick1udwig/wcgw.git
cd wcgw
git submodule update --init --recursive
git checkout hf/fix-wcgw-on-ubuntu
cd ..
uvx --refresh ws-mcp --command "uvx --from /tmp/wcgw --with /tmp/wcgw/src/mcp_wcgw --python 3.12 wcgw_mcp" --port 3001

# Example using Brave search
export BRAVE_API_KEY=YOUR_API_KEY_HERE
uvx --refresh ws-mcp --env BRAVE_API_KEY=$BRAVE_API_KEY --command "npx -y @modelcontextprotocol/server-brave-search" --port 3003

# Or, with a .env file:
uvx --refresh ws-mcp --env-file path/to/.env --command "npx -y @modelcontextprotocol/server-brave-search" --port 3003

# `--command` can be supplied multiple times!
#  Example serving multiple servers at once:
uvx --refresh ws-mcp --env-file path/to/.env --command "npx -y @modelcontextprotocol/server-brave-search" --command "uvx mcp-server-fetch" --port 3004

# Servers can also be specified in a `.json` file following [the standard MCP format](https://modelcontextprotocol.io/quickstart/user#2-add-the-filesystem-mcp-server)
uvx --refresh ws-mcp --env-file path/to/.env --config path/to/config.json --port 3005
```

## Dev setup

```bash
uv run ws-mcp --env-file path/to/.env --config path/to/config.json --port 3005
```
