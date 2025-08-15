#!/usr/bin/env python3
import os
import sys
import logging
from typing import Dict, Any, Optional

from dotenv import load_dotenv
import httpx

from livekit import agents
from livekit.agents import AgentSession, Agent, RunContext, function_tool
from livekit.plugins import openai, silero  # ✅ LLM + STT + TTS

load_dotenv()

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stderr)]
)
logger = logging.getLogger("car-service-agent")

MCP_PORT = int(os.getenv("MCP_PORT", "8000"))
MCP_HOST = os.getenv("MCP_HOST", "http://localhost")
MCP_SERVER_URL = f"{MCP_HOST}:{MCP_PORT}/mcp"

# ----------------------------
# MCP HTTP Client
# ----------------------------
class MCPHTTPClient:
    def __init__(self, url: str):
        self.url = url
        self.http: Optional[httpx.AsyncClient] = None
        self.req_id = 0

    async def __aenter__(self):
        self.http = httpx.AsyncClient(timeout=20.0)
        return self

    async def __aexit__(self, exc_type, exc, tb):
        if self.http:
            await self.http.aclose()
            self.http = None

    def _next_id(self) -> int:
        self.req_id += 1
        return self.req_id

    async def _rpc(self, method: str, params: Any = None) -> Any:
        payload = {"jsonrpc": "2.0", "id": self._next_id(), "method": method, "params": params}
        resp = await self.http.post(self.url, json=payload)
        resp.raise_for_status()
        data = resp.json()
        if "error" in data and data["error"]:
            raise RuntimeError(f"MCP error {data['error'].get('code')}: {data['error'].get('message')}")
        return data.get("result")

    async def initialize(self):
        return await self._rpc("initialize", {
            "protocolVersion": "0.1.0",
            "capabilities": {},
            "clientInfo": {"name": "car-service-agent", "version": "1.0.0"},
        })

    async def list_tools(self):
        return await self._rpc("list_tools", {})

    async def call_tool(self, name: str, arguments: Dict[str, Any]):
        return await self._rpc("call_tool", {"name": name, "arguments": arguments or {}})

# ----------------------------
# LiveKit Agent
# ----------------------------
class CarServiceAgent(Agent):
    def __init__(self):
        super().__init__(instructions="You are a friendly car service scheduling assistant.")
        self._mcp_url = MCP_SERVER_URL

    async def on_start(self, context: RunContext):
        logger.debug("📣 Connecting to MCP HTTP server…")
        async with MCPHTTPClient(self._mcp_url) as mcp:
            await mcp.initialize()
            tools = await mcp.list_tools()
            logger.info(f"🛠️ Tools: {[t.get('name') for t in tools]}")
        logger.debug("📣 MCP handshake done.")

    async def _call_mcp(self, tool_name: str, arguments: Dict[str, Any]):
        async with MCPHTTPClient(self._mcp_url) as mcp:
            await mcp.initialize()
            return await mcp.call_tool(tool_name, arguments)

    @function_tool()
    async def get_available_services(self, context: RunContext) -> str:
        result = await self._call_mcp("get_available_services", {})
        services = result if isinstance(result, list) else result.get("services") or result.get("result")
        return f"Available services: {', '.join(services)}" if isinstance(services, list) else str(services)

    @function_tool()
    async def schedule_car_service(
        self, context: RunContext,
        service_type: str, date: str, time: str,
        customer_name: str, customer_email: str,
        phone_number: str, vehicle_model: str,
        notes: str = "",
    ) -> str:
        result = await self._call_mcp("schedule_car_service", {
            "service_type": service_type,
            "date": date,
            "time": time,
            "customer_name": customer_name,
            "customer_email": customer_email,
            "phone_number": phone_number,
            "vehicle_model": vehicle_model,
            "notes": notes,
        })
        return f"Result: {result}"

# ----------------------------
# Entry point with LLM
# ----------------------------
async def entrypoint(ctx: agents.JobContext):
    session = AgentSession(
        stt=openai.STT(),
        llm=openai.LLM(model="gpt-4o-mini"),  # ✅ Now has LLM
        tts=openai.TTS(),
        vad=silero.VAD.load(),
    )
    agent = CarServiceAgent()
    await session.start(room=ctx.room, agent=agent)
    await session.generate_reply(instructions="Greet the user warmly.")

if __name__ == "__main__":
    agents.cli.run_app(agents.WorkerOptions(entrypoint_fnc=entrypoint))
