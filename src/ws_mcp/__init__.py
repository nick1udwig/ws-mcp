import argparse
import asyncio
import json
import logging
import os
import shlex
import sys
import time

from asyncio import create_subprocess_exec, subprocess, Queue
from pathlib import Path
from typing import Optional, Dict, List, Any, Union, Tuple

import jsonschema
import websockets

from colorama import Fore, Style, init as init_colorama
from websockets.legacy.server import WebSocketServerProtocol

# Initialize colorama for cross-platform color support
init_colorama()

# CLI formatting constants
SUCCESS_PREFIX = "✅"
START_PREFIX = "🚀"
SUMMARY_PREFIX = "✨"
WEBSOCKET_PREFIX = "🔗"
BULLET_POINT = "•"
SERVER_NAME_COLOR = Fore.CYAN
COMMAND_COLOR = Fore.WHITE
RESET = Style.RESET_ALL

DEFAULT_CONFIG = """{
  "mcpServers": {
    "wcgw": {
      "command": "uvx",
      "args": [
        "--refresh",
        "--from",
        "wcgw@latest",
        "--python",
        "3.12",
        "wcgw_mcp"
      ]
    },
    "fetch": {
      "command": "uvx",
      "args": [
        "--refresh",
        "mcp-server-fetch"
      ]
    }
  }
}"""

logging.basicConfig(level=logging.INFO)
# Silence all websockets loggers at the root
logging.getLogger('websockets').setLevel(logging.WARNING)
logger = logging.getLogger(__name__)
websockets_logger = logging.getLogger('websockets.server')
websockets_logger.setLevel(logging.WARNING)  # Reduce websockets library logging

class MessagePublisher:
    """Handles publishing messages to WebSocket clients."""
    def __init__(self):
        self.message_queue: "Queue[Dict[str, Any]]" = Queue()
        self.websocket: Optional[WebSocketServerProtocol] = None
        self.running = False
        self._task: Optional[asyncio.Task] = None

    def set_websocket(self, websocket: WebSocketServerProtocol):
        """Set the WebSocket connection to publish messages to."""
        self.websocket = websocket

    async def start(self):
        """Start the message publishing task."""
        if self._task is None:
            self.running = True
            self._task = asyncio.create_task(self._publish_messages())

    async def stop(self):
        """Stop the message publishing task."""
        self.running = False
        if self._task:
            await self.message_queue.put(None)  # Sentinel to stop the loop
            await self._task
            self._task = None

    async def publish(self, message: Dict[str, Any]):
        """Queue a message for publishing."""
        await self.message_queue.put(message)

    async def _publish_messages(self):
        """Main loop for publishing messages to WebSocket."""
        while self.running:
            try:
                message = await self.message_queue.get()
                if message is None:  # Stop sentinel
                    break

                if self.websocket and self.websocket.state == websockets.protocol.State.OPEN:
                    await self.websocket.send(json.dumps(message))

            except Exception as e:
                logger.error(f"Error publishing message: {e}")
                continue

INITIALIZE_REQUEST_SCHEMA = {
    "type": "object",
    "required": ["jsonrpc", "method", "params", "id"],
    "properties": {
        "jsonrpc": {"type": "string", "enum": ["2.0"]},
        "method": {"type": "string", "enum": ["initialize"]},
        "params": {
            "type": "object",
            "required": ["protocolVersion", "clientInfo", "capabilities"],
            "properties": {
                "protocolVersion": {"type": "string"},
                "clientInfo": {
                    "type": "object",
                    "required": ["name", "version"],
                    "properties": {
                        "name": {"type": "string"},
                        "version": {"type": "string"}
                    }
                },
                "capabilities": {"type": "object"}
            }
        },
        "id": {"type": ["string", "number"]}
    }
}

class McpServer:
    """Represents a single MCP server process and its state."""
    def __init__(self, name: str, command: str, env: Optional[Dict[str, str]] = None):
        self.name = name
        self.command = command
        self.env = env or {}
        self.process: Optional[subprocess.Process] = None
        self.pending_requests: Dict[str, Tuple[asyncio.Future, bool]] = {}
        self.tools: Dict[str, Any] = {}  # Map of tool names to their schemas
        self.initialized = False
        self.message_publisher: Optional[MessagePublisher] = None

    async def start_process(self):
        """Start the MCP server process"""
        args = shlex.split(self.command)
        process_env = {**os.environ, **self.env}

        self.process = await create_subprocess_exec(
            *args,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=process_env
        )

        if not self.process.stdin or not self.process.stdout:
            raise RuntimeError(f"Failed to create process pipes for command: {self.command}")

        print(f"{SUCCESS_PREFIX} Started MCP server '{SERVER_NAME_COLOR}{self.name}{RESET}' [command: {COMMAND_COLOR}{self.command}{RESET}]")
        return self.process

    def register_tools(self, tools: Dict[str, Any]):
        """Register tools provided by this server"""
        self.tools = tools
        self.initialized = True

    async def send_request(self, request: Dict[str, Any], should_send_over_ws: bool) -> Dict[str, Any]:
        """Send a request to this server and wait for response"""
        if not self.process or not self.process.stdin:
            raise RuntimeError("Process not started or stdin not available")

        request_id = request.get("id")
        if request_id:
            self.pending_requests[request_id] = asyncio.Future(), should_send_over_ws

        message_bytes = f"{json.dumps(request)}\n".encode()
        self.process.stdin.write(message_bytes)
        await self.process.stdin.drain()
        logger.debug(f"Sent to {self.command}: {request}")

        if request_id:
            try:
                response = await asyncio.wait_for(
                    self.pending_requests[request_id][0],
                    timeout=10.0
                )
                return response
            except asyncio.TimeoutError:
                return {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "error": {
                        "code": -32000,
                        "message": "Request timed out"
                    }
                }
            finally:
                self.pending_requests.pop(request_id, None)

        return {}

    def set_message_publisher(self, publisher: MessagePublisher):
        """Set the message publisher for this server."""
        self.message_publisher = publisher

    async def handle_stdout(self):
        """Handle server process output"""
        while True:
            if not self.process or not self.process.stdout:
                break

            try:
                line = await self.process.stdout.readline()
                if not line:
                    logger.error(f"Process stdout closed for command: {self.command}")
                    break

                line_str = line.decode().strip()
                if not line_str:
                    logger.info(f"handle_stdout {self.command} got no-decode-able line")
                    continue

                logger.debug(f"handle_stdout {self.command} got line {line_str}")

                try:
                    message = json.loads(line_str)
                    if "id" in message and message["id"] in self.pending_requests:
                        future, should_send_over_ws = self.pending_requests.pop(message["id"])
                        future.set_result(message)

                    if self.message_publisher and should_send_over_ws:
                        await self.message_publisher.publish(message)
                except json.JSONDecodeError as e:
                    logger.error(f"Failed to parse JSON from {self.command}: {line_str}")
                    logger.error(f"JSON error: {e}")

            except Exception as e:
                logger.error(f"Error handling process output for {self.command}: {e}")
                continue

    async def handle_stderr(self):
        """Handle stderr output from the process"""
        while True:
            if not self.process or not self.process.stderr:
                break

            try:
                line = await self.process.stderr.readline()
                if not line:
                    break
                logger.debug(f"Process stderr ({self.command}): {line.decode().strip()}")
            except Exception as e:
                logger.error(f"Error handling stderr ({self.command}): {e}")
                break

    async def cleanup(self):
        """Clean up server resources"""
        if self.process:
            try:
                self.process.terminate()
                await asyncio.wait_for(self.process.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                self.process.kill()
            self.process = None

        for future in self.pending_requests.values():
            if not future.done():
                future.cancel()
        self.pending_requests.clear()


class McpWebSocketBridge:
    def __init__(self, servers: List[Tuple[str, str]], port: int = 3000, env: Optional[Dict[str, str]] = None):
        self.servers: List[McpServer] = [McpServer(name, cmd, env) for name, cmd in servers]
        self.port = port
        self.websocket: Optional[WebSocketServerProtocol] = None
        self.tool_to_server: Dict[str, McpServer] = {}  # Maps tool names to servers
        self.message_publisher = MessagePublisher()
        self.authenticated = False  # Track Spider authentication
        self.expected_api_key: Optional[str] = None  # Expected API key for Spider auth

    async def start_all_servers(self):
        """Start all MCP server processes"""
        for server in self.servers:
            await server.start_process()

    def get_server_for_tool(self, name: str) -> Optional[McpServer]:
        """Get the server responsible for a given tool/method"""
        return self.tool_to_server.get(name)

    def get_combined_tools(self):
        combined_tools = []
        for server in self.servers:
            logger.debug(f"{server.tools}")
            combined_tools.extend(server.tools)
        logger.debug(f"get_combined_tools: combined: {combined_tools}")
        return combined_tools

    async def handle_initialize(self, request: Dict[str, Any]) -> Dict[str, Any]:
        """Handle initialize request by forwarding to all servers and combining responses"""
        # Send initialize to all servers and collect their tools
        for server in self.servers:
            response = await server.send_request(request, False)
            logger.debug(f"handle_initialize: initialize {server.command} - {response}")

            await server.send_request({"jsonrpc":"2.0","method":"notifications/initialized"}, False)

            response = await server.send_request({"jsonrpc":"2.0","method":"tools/list","id":2}, False)
            logger.debug(f"handle_initialize: tools/list {server.command} - {response}")

            if "result" in response and "tools" in response["result"]:
                server_tools = response["result"]["tools"]
                # Register tools with this server
                server.register_tools(server_tools)
                # Update tool to server mapping
                for tool in server_tools:
                    self.tool_to_server[tool["name"]] = server

        # Return combined response
        logger.debug(f"handle_initialize: done with {self.tool_to_server}")
        # TODO
        return {
            "jsonrpc": "2.0",
            "id": request["id"],
            "result": {"protocolVersion": "2024-11-05", "capabilities": {"experimental": {}, "prompts": {"listChanged": False}, "tools": {"listChanged": False}}, "serverInfo": {"name": "ws-mcp-multi", "version": "1.0.0"}},
        }

    async def list_tools(self, id):
        return {
            "jsonrpc": "2.0",
            "id": id,
            "result": {
                "tools": self.get_combined_tools()
            }
        }

    async def handle_client(self, websocket: WebSocketServerProtocol):
        """Handle WebSocket client connection"""
        # Check if this is actually a new connection
        was_connected = self.websocket is not None
        self.websocket = websocket
        self.message_publisher.set_websocket(websocket)

        # Check if Spider authentication is required
        self.expected_api_key = os.environ.get('SPIDER_API_KEY')
        if self.expected_api_key:
            self.authenticated = False
        else:
            self.authenticated = True  # No auth required if no API key set

        # Set message publisher for all servers
        for server in self.servers:
            server.set_message_publisher(self.message_publisher)

        if not was_connected:  # Only log if we weren't connected before
            logger.info("WebSocket status: connected")

        try:
            async for message in websocket:
                try:
                    data = json.loads(message)
                    logger.debug(f"Received message: {data}")

                    method = data.get("method")

                    # Handle Spider authentication first if required
                    if not self.authenticated and self.expected_api_key:
                        if method != "spider/authorization":
                            error_response = {
                                "jsonrpc": "2.0",
                                "id": data.get("id"),
                                "error": {
                                    "code": -32001,
                                    "message": "Authentication required. Send spider/authorization first."
                                }
                            }
                            await websocket.send(json.dumps(error_response))
                            await websocket.close(1008, "Authentication required")
                            return
                        else:
                            # Handle spider/authorization
                            params = data.get("params", {})
                            api_key = params.get("api_key")
                            if api_key == self.expected_api_key:
                                self.authenticated = True
                                auth_response = {
                                    "jsonrpc": "2.0",
                                    "id": data.get("id"),
                                    "result": {"status": "authenticated"}
                                }
                                await websocket.send(json.dumps(auth_response))
                                continue
                            else:
                                error_response = {
                                    "jsonrpc": "2.0",
                                    "id": data.get("id"),
                                    "error": {
                                        "code": -32002,
                                        "message": "Invalid API key"
                                    }
                                }
                                await websocket.send(json.dumps(error_response))
                                await websocket.close(1008, "Invalid API key")
                                return

                    # Special handling for initialize
                    if method == "initialize":
                        try:
                            jsonschema.validate(instance=data, schema=INITIALIZE_REQUEST_SCHEMA)
                            response = await self.handle_initialize(data)
                            await websocket.send(json.dumps(response))
                            logger.debug("done")
                            continue
                        except jsonschema.exceptions.ValidationError as e:
                            error_response = {
                                "jsonrpc": "2.0",
                                "id": data.get("id"),
                                "error": {
                                    "code": -32600,
                                    "message": f"Invalid initialize request: {str(e)}"
                                }
                            }
                            await websocket.send(json.dumps(error_response))
                            continue
                    elif method == "tools/list":
                        tools = await self.list_tools(data.get("id"))
                        logger.debug(f"tools/list: {tools}")
                        await websocket.send(json.dumps(tools))
                        continue
                    elif method == "notifications/initialized":
                        continue
                    elif method == "spider/start-package":
                        await self.handle_spider_start_package(data, websocket)
                        continue
                    elif method == "spider/persist":
                        await self.handle_spider_persist(data, websocket)
                        continue
                    elif method == "spider/load-project":
                        await self.handle_spider_load_project(data, websocket)
                        continue
                    elif method == "tools/call":
                        # Route other requests to appropriate server
                        name = data["params"]["name"]
                        s = self.get_server_for_tool(name)
                        if not s:
                            error_response = {
                                "jsonrpc": "2.0",
                                "id": data.get("id"),
                                "error": {
                                    "code": -32601,
                                    "message": f"Tool not found: {name}"
                                }
                            }
                            await websocket.send(json.dumps(error_response))
                            continue

                        response = await s.send_request(data, True)
                        if response:
                            await websocket.send(json.dumps(response))
                    else:
                        error_response = {
                            "jsonrpc": "2.0",
                            "id": data.get("id"),
                            "error": {
                                "code": -32601,
                                "message": f"Method not found: {method}"
                            }
                        }
                        await websocket.send(json.dumps(error_response))
                        continue


                except Exception as e:
                    logger.error(f"Error handling message: {e}")
                    if "id" in data:
                        error_response = {
                            "jsonrpc": "2.0",
                            "id": data["id"],
                            "error": {
                                "code": -32000,
                                "message": str(e)
                            }
                        }
                        await websocket.send(json.dumps(error_response))

        except websockets.exceptions.ConnectionClosed:
            # Only log if this was our last connection
            if self.websocket == websocket:
                logger.info("WebSocket status: disconnected")
                self.websocket = None
        finally:
            if self.websocket == websocket:  # Only clear if it's still our current connection
                self.websocket = None

    async def handle_spider_start_package(self, data: Dict[str, Any], websocket: WebSocketServerProtocol):
        """Handle Spider start-package request"""
        import zipfile
        import base64
        import tempfile
        import shutil
        import hashlib
        from pathlib import Path

        try:
            params = data.get("params", {})
            package_dir = params.get("package_dir")

            if not package_dir:
                error_response = {
                    "jsonrpc": "2.0",
                    "id": data.get("id"),
                    "error": {
                        "code": -32602,
                        "message": "Missing package_dir parameter"
                    }
                }
                await websocket.send(json.dumps(error_response))
                return

            package_path = Path(package_dir)
            pkg_path = package_path / "pkg"
            metadata_path = package_path / "metadata.json"

            if not pkg_path.exists():
                error_response = {
                    "jsonrpc": "2.0",
                    "id": data.get("id"),
                    "error": {
                        "code": -32603,
                        "message": f"Package not built: {pkg_path} does not exist. Run 'kit build' first."
                    }
                }
                await websocket.send(json.dumps(error_response))
                return

            # Read metadata.json if it exists
            metadata = {}
            package_name = package_path.name
            publisher = "unknown"
            current_version = "1.0.0"

            if metadata_path.exists():
                try:
                    with open(metadata_path, 'r') as f:
                        metadata = json.load(f)
                        # Extract key fields from metadata
                        if 'properties' in metadata:
                            props = metadata['properties']
                            package_name = props.get('package_name', package_name)
                            publisher = props.get('publisher', publisher)
                            current_version = props.get('current_version', current_version)
                except Exception as e:
                    logger.warning(f"Failed to read metadata.json: {e}")

            # Create a temporary zip file
            with tempfile.NamedTemporaryFile(suffix='.zip', delete=False) as tmp_zip:
                with zipfile.ZipFile(tmp_zip.name, 'w', zipfile.ZIP_DEFLATED) as zipf:
                    for root, dirs, files in os.walk(pkg_path):
                        # Add directory entries
                        for dir_name in dirs:
                            dir_path = os.path.join(root, dir_name)
                            arcname = os.path.relpath(dir_path, pkg_path) + '/'
                            # Create a ZipInfo for the directory
                            zinfo = zipfile.ZipInfo(arcname)
                            zinfo.external_attr = 0o755 << 16 | 0x10  # Set directory flag and permissions
                            zipf.writestr(zinfo, '')
                        
                        # Add file entries
                        for file in files:
                            file_path = os.path.join(root, file)
                            arcname = os.path.relpath(file_path, pkg_path)
                            zipf.write(file_path, arcname)

                # Read the zip file and encode as base64
                with open(tmp_zip.name, 'rb') as f:
                    zip_data = f.read()
                    zip_base64 = base64.b64encode(zip_data).decode('utf-8')

                    # Calculate hash of the zip file
                    f.seek(0)
                    hash_obj = hashlib.sha256()
                    hash_obj.update(f.read())
                    version_hash = hash_obj.hexdigest()

                # Clean up temp file
                os.unlink(tmp_zip.name)

            # Ensure metadata has all required fields
            if metadata:
                # Ensure properties exists
                if 'properties' not in metadata:
                    metadata['properties'] = {}

                # Ensure all required properties fields are present
                props = metadata['properties']
                props['package_name'] = props.get('package_name', package_name)
                props['publisher'] = props.get('publisher', publisher)
                props['current_version'] = props.get('current_version', current_version)

                # Ensure code_hashes includes the current version
                if 'code_hashes' not in props:
                    props['code_hashes'] = {}
                props['code_hashes'][current_version] = version_hash

                # Ensure other fields have defaults if not present
                props.setdefault('mirrors', [])
                props.setdefault('license', None)
                props.setdefault('screenshots', None)
                props.setdefault('wit_version', None)
                props.setdefault('dependencies', None)

                # Ensure top-level metadata fields
                metadata.setdefault('name', package_name)
                metadata.setdefault('description', props.get('description', f"Package built from {package_dir}"))
                metadata.setdefault('image', '')
                metadata.setdefault('external_url', '')
                metadata.setdefault('animation_url', None)
            else:
                # Create complete metadata structure from scratch
                metadata = {
                    "name": package_name,
                    "description": f"Package built from {package_dir}",
                    "image": "",
                    "external_url": "",
                    "animation_url": None,
                    "properties": {
                        "package_name": package_name,
                        "publisher": publisher,
                        "current_version": current_version,
                        "mirrors": [],
                        "code_hashes": {current_version: version_hash},
                        "license": None,
                        "screenshots": None,
                        "wit_version": None,
                        "dependencies": None
                    }
                }

            # Send response with the zipped package and metadata
            response = {
                "jsonrpc": "2.0",
                "id": data.get("id"),
                "result": {
                    "package_zip": zip_base64,
                    "package_name": package_name,
                    "publisher": publisher,
                    "version_hash": version_hash,
                    "metadata": metadata,
                    "success": True
                }
            }
            await websocket.send(json.dumps(response))

        except Exception as e:
            error_response = {
                "jsonrpc": "2.0",
                "id": data.get("id"),
                "error": {
                    "code": -32603,
                    "message": f"Failed to package: {str(e)}"
                }
            }
            await websocket.send(json.dumps(error_response))

    async def handle_spider_persist(self, data: Dict[str, Any], websocket: WebSocketServerProtocol):
        """Handle Spider persist request"""
        import zipfile
        import base64
        import tempfile
        from pathlib import Path

        try:
            params = data.get("params", {})
            directories = params.get("directories", [])

            if not directories:
                error_response = {
                    "jsonrpc": "2.0",
                    "id": data.get("id"),
                    "error": {
                        "code": -32602,
                        "message": "Missing directories parameter"
                    }
                }
                await websocket.send(json.dumps(error_response))
                return

            # Create a temporary zip file
            with tempfile.NamedTemporaryFile(suffix='.zip', delete=False) as tmp_zip:
                with zipfile.ZipFile(tmp_zip.name, 'w', zipfile.ZIP_DEFLATED) as zipf:
                    for directory in directories:
                        dir_path = Path(directory).expanduser()
                        if dir_path.exists() and dir_path.is_dir():
                            for root, dirs, files in os.walk(dir_path):
                                for file in files:
                                    file_path = os.path.join(root, file)
                                    # Preserve directory structure in zip
                                    arcname = os.path.relpath(file_path, dir_path.parent)
                                    zipf.write(file_path, arcname)

                # Read the zip file and encode as base64
                with open(tmp_zip.name, 'rb') as f:
                    zip_data = f.read()
                    zip_base64 = base64.b64encode(zip_data).decode('utf-8')

                # Clean up temp file
                os.unlink(tmp_zip.name)

            # Send response with the zipped directories
            response = {
                "jsonrpc": "2.0",
                "id": data.get("id"),
                "result": {
                    "persisted_zip": zip_base64,
                    "directories": directories,
                    "success": True
                }
            }
            await websocket.send(json.dumps(response))

        except Exception as e:
            error_response = {
                "jsonrpc": "2.0",
                "id": data.get("id"),
                "error": {
                    "code": -32603,
                    "message": f"Failed to persist: {str(e)}"
                }
            }
            await websocket.send(json.dumps(error_response))

    async def handle_spider_load_project(self, data: Dict[str, Any], websocket: WebSocketServerProtocol):
        """Handle Spider load-project request"""
        import zipfile
        import base64
        import tempfile
        from pathlib import Path
        import uuid

        try:
            params = data.get("params", {})
            project_uuid = params.get("project_uuid")
            name = params.get("name")
            initial_zip = params.get("initial_zip")

            # Generate UUID if not provided
            if not project_uuid:
                project_uuid = str(uuid.uuid4())

            # Create project directory
            project_dir = Path.home() / project_uuid
            project_dir.mkdir(parents=True, exist_ok=True)

            # Extract initial zip if provided
            if initial_zip:
                try:
                    # Decode base64 zip content
                    zip_data = base64.b64decode(initial_zip)

                    # Create temporary file for zip
                    with tempfile.NamedTemporaryFile(suffix='.zip', delete=False) as tmp_zip:
                        tmp_zip.write(zip_data)
                        tmp_zip_path = tmp_zip.name

                    # Extract zip to project directory
                    with zipfile.ZipFile(tmp_zip_path, 'r') as zipf:
                        zipf.extractall(project_dir)

                    # Clean up temp file
                    os.unlink(tmp_zip_path)

                    logger.info(f"Extracted initial zip to {project_dir}")
                except Exception as e:
                    logger.error(f"Failed to extract initial zip: {e}")
                    # Continue even if extraction fails

            # Send successful response
            response = {
                "jsonrpc": "2.0",
                "id": data.get("id"),
                "result": {
                    "project_uuid": project_uuid,
                    "directory": str(project_dir)
                }
            }
            await websocket.send(json.dumps(response))
            logger.info(f"Project loaded: {project_uuid} at {project_dir}")

        except Exception as e:
            logger.error(f"Error in handle_spider_load_project: {e}")
            error_response = {
                "jsonrpc": "2.0",
                "id": data.get("id"),
                "error": {
                    "code": -32603,
                    "message": f"Failed to load project: {str(e)}"
                }
            }
            await websocket.send(json.dumps(error_response))

    async def cleanup(self):
        """Clean up all server resources"""
        await self.message_publisher.stop()
        for server in self.servers:
            await server.cleanup()

    async def serve(self):
        """Start the WebSocket server and all MCP processes"""
        try:
            print(f"\n{START_PREFIX} Starting {len(self.servers)} MCP servers...")
            # Start all MCP servers
            await self.start_all_servers()

            # Start the message publisher
            await self.message_publisher.start()

            # Start output handlers for all servers
            stdout_tasks = [
                asyncio.create_task(server.handle_stdout())
                for server in self.servers
            ]
            stderr_tasks = [
                asyncio.create_task(server.handle_stderr())
                for server in self.servers
            ]

            # Start WebSocket server
            async with websockets.serve(self.handle_client, "localhost", self.port):
                # Print summary of started servers
                server_count = len(self.servers)
                print(f"\n{SUMMARY_PREFIX} {server_count}/{server_count} MCP servers started successfully:")
                for server in self.servers:
                    print(f"  {BULLET_POINT} {SERVER_NAME_COLOR}{server.name}{RESET}")

                print(f"\n{WEBSOCKET_PREFIX} Multi-MCP bridge running on ws://localhost:{self.port}\n")

                try:
                    #await asyncio.gather(*output_tasks, stderr_task)
                    await asyncio.gather(*stdout_tasks, *stderr_tasks)
                except Exception as e:
                    logger.error(f"Error in message handling: {e}")

                await asyncio.Future()  # run forever

        except Exception as e:
            logger.error(f"Server error: {e}")
        finally:
            await self.cleanup()

def parse_dotenv(env_file: Path) -> Dict[str, str]:
    """Parse a .env file and return a dictionary of environment variables."""
    if not env_file.exists():
        raise FileNotFoundError(f"Environment file not found: {env_file}")

    env_vars = {}
    with env_file.open() as f:
        for line in f:
            line = line.strip()
            # Skip empty lines and comments
            if not line or line.startswith('#'):
                continue
            try:
                key, value = line.split('=', 1)
                # Remove quotes if present
                key = key.strip()
                value = value.strip().strip("'").strip('"')
                env_vars[key] = value
            except ValueError:
                logger.warning(f"Skipping invalid line in .env file: {line}")
    return env_vars

# Schema for MCP server configuration file
MCP_CONFIG_SCHEMA = {
    "type": "object",
    "required": ["mcpServers"],
    "properties": {
        "mcpServers": {
            "type": "object",
            "minProperties": 1,
            "patternProperties": {
                "^[a-zA-Z0-9_-]+$": {  # Server name pattern
                    "type": "object",
                    "required": ["command"],
                    "properties": {
                        "command": {
                            "type": "string",
                            "minLength": 1
                        },
                        "args": {
                            "type": "array",
                            "items": {
                                "type": "string"
                            }
                        }
                    },
                    "additionalProperties": False
                }
            },
            "additionalProperties": False
        }
    },
    "additionalProperties": False
}

def parse_config(config_str: str) -> List[Tuple[str, str]]:
    config = json.loads(config_str)

    # Validate configuration against schema
    jsonschema.validate(instance=config, schema=MCP_CONFIG_SCHEMA)

    server_configs = []
    for server_name, server_config in config["mcpServers"].items():
        cmd = [server_config["command"]]
        if "args" in server_config:
            cmd.extend(server_config["args"])
        server_configs.append((server_name, shlex.join(cmd)))

    return server_configs

def parse_config_file(config_path: Path) -> List[Tuple[str, str]]:
    """Parse the MCP server configuration file.

    Args:
        config_path: Path to the JSON configuration file.

    Returns:
        List of command strings extracted from the configuration.

    Raises:
        ValueError: If the configuration file is invalid.
        FileNotFoundError: If the configuration file doesn't exist.
        json.JSONDecodeError: If the configuration file contains invalid JSON.
        jsonschema.exceptions.ValidationError: If the configuration doesn't match the schema.
    """
    if not config_path.exists():
        raise FileNotFoundError(f"Configuration file not found: {config_path}")

    with config_path.open() as f:
        config_str = f.read()

    return parse_config(config_str)

def parse_args():
    parser = argparse.ArgumentParser(
        description='Bridge multiple stdio-based MCP servers to WebSocket',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s --command "uv tool run --from wcgw@latest --python 3.12 wcgw_mcp" --command "node path/to/mcp-server.js" --port 10125
  %(prog)s --command "./server1" --command "./server2" --port 10125 --env API_KEY=xyz123
  %(prog)s --command "./server1" --command "./server2" --env-file .env
  %(prog)s --config config.json --port 10125"""
    )

    command_group = parser.add_mutually_exclusive_group(required=False)
    command_group.add_argument(
        '--command',
        type=str,
        action='append',
        help='Command to start an MCP server (in quotes). Can be specified multiple times.'
    )

    command_group.add_argument(
        '--config',
        type=Path,
        help='Path to a JSON configuration file containing MCP server configurations'
    )

    parser.add_argument(
        '--port',
        type=int,
        default=10125,
        help='Port for the WebSocket server (default: 3000)'
    )

    parser.add_argument(
        '--log-level',
        choices=['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'],
        default='INFO',
        help='Set the logging level (default: INFO)'
    )

    parser.add_argument(
        '--env',
        type=str,
        action='append',
        help='Environment variables to pass to the MCP server in KEY=VALUE format. Can be specified multiple times. Overrides .env.'
    )

    parser.add_argument(
        '--env-file',
        type=Path,
        help='Path to a .env file containing environment variables'
    )

    return parser.parse_args()

async def execute():
    args = parse_args()

    # Set log level from arguments
    logging.getLogger().setLevel(args.log_level)

    # Initialize environment variables dictionary
    env = {}

    # Read environment variables from .env file if provided
    if args.env_file:
        try:
            env.update(parse_dotenv(args.env_file))
        except Exception as e:
            logger.error(f"Error reading .env file: {e}")
            sys.exit(1)

    # Add/override with command line environment variables if provided
    if args.env:
        for env_var in args.env:
            try:
                key, value = env_var.split('=', 1)
                env[key] = value
            except ValueError:
                logger.error(f"Invalid environment variable format: {env_var}. Must be KEY=VALUE")
                sys.exit(1)

    # Get commands from either direct arguments or config file
    try:
        if args.command:
            commands = args.command
        elif args.config:
            commands = parse_config_file(args.config)
        else:
            commands = parse_config(DEFAULT_CONFIG)
    except (FileNotFoundError, json.JSONDecodeError, jsonschema.exceptions.ValidationError) as e:
        logger.error(f"Error reading configuration file: {e}")
        sys.exit(1)

    # Initialize bridge with multiple commands
    bridge = McpWebSocketBridge(commands, args.port, env)
    await bridge.serve()

def main():
    asyncio.run(execute())

if __name__ == "__main__":
    main()
