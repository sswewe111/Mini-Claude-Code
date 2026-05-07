from mcp.mcp_client import MCPClient


class MCPToolRouter:
    
    def __init__(self):
        self.clients = {}  # server_name -> MCPClient
    def register_client(self, client: MCPClient):
        self.clients[client.server_name] = client
    def is_mcp_tool(self, tool_name: str) -> bool:
        return tool_name.startswith("mcp__")
    def call(self, tool_name: str, arguments: dict) -> str:
        """Route an MCP tool call to the correct server."""
        parts = tool_name.split("__", 2)
        if len(parts) != 3:
            return f"Error: Invalid MCP tool name: {tool_name}"
        _, server_name, actual_tool = parts
        client = self.clients.get(server_name)
        if not client:
            return f"Error: MCP server not found: {server_name}"
        return client.call_tool(actual_tool, arguments)
    def get_all_tools(self) -> list:
        """Collect tools from all connected MCP servers."""
        tools = []
        for client in self.clients.values():
            tools.extend(client.get_agent_tools())
        return tools

mcp_router = MCPToolRouter()