#!/usr/bin/env python3
"""Enhanced Pipecat Bot with MCP Server Integration for Car Service."""

import os
import json
import httpx
from datetime import datetime
from typing import Any, Dict, Optional

from dotenv import load_dotenv
from loguru import logger

print("🚀 Starting Enhanced Pipecat bot with MCP Car Service...")
print("⏳ Loading AI models and MCP client...\n")

logger.info("Loading Silero VAD model...")
from pipecat.audio.vad.silero import SileroVADAnalyzer

logger.info("✅ Silero VAD model loaded")
logger.info("Loading pipeline components...")
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineParams, PipelineTask
from pipecat.processors.aggregators.openai_llm_context import OpenAILLMContext
from pipecat.services.cartesia.tts import CartesiaTTSService
from pipecat.services.deepgram.stt import DeepgramSTTService
from pipecat.services.openai.llm import OpenAILLMService
from pipecat.adapters.schemas.function_schema import FunctionSchema
from pipecat.adapters.schemas.tools_schema import ToolsSchema
from pipecat.services.llm_service import FunctionCallParams

logger.info("✅ Pipeline components loaded")

logger.info("Loading LiveKit transport...")
from pipecat.transports.services.livekit import LiveKitTransport, LiveKitParams

logger.info("✅ All components loaded successfully!")

load_dotenv(override=True)

# MCP Configuration
MCP_PORT = int(os.getenv("MCP_PORT", "8000"))
MCP_HOST = os.getenv("MCP_HOST", "http://localhost")
MCP_SERVER_URL = f"{MCP_HOST}:{MCP_PORT}/mcp"

# LiveKit Configuration
LIVEKIT_URL = os.getenv("LIVEKIT_URL")
LIVEKIT_API_KEY = os.getenv("LIVEKIT_API_KEY")
LIVEKIT_API_SECRET = os.getenv("LIVEKIT_API_SECRET")

class MCPHTTPClient:
    """HTTP client for communicating with MCP server."""
    
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
            "clientInfo": {"name": "pipecat-car-service-bot", "version": "1.0.0"},
        })

    async def list_tools(self):
        return await self._rpc("list_tools", {})

    async def call_tool(self, name: str, arguments: Dict[str, Any]):
        return await self._rpc("call_tool", {"name": name, "arguments": arguments or {}})

class MCPManager:
    """Manages MCP server communication."""
    
    def __init__(self):
        self.mcp_url = MCP_SERVER_URL
        logger.info(f"🔗 MCP Manager initialized with URL: {self.mcp_url}")
    
    async def call_mcp_tool(self, tool_name: str, arguments: Dict[str, Any]):
        """Call an MCP tool and return the result."""
        try:
            logger.info(f"🛠️ Calling MCP tool: {tool_name} with args: {arguments}")
            
            async with MCPHTTPClient(self.mcp_url) as mcp:
                await mcp.initialize()
                result = await mcp.call_tool(tool_name, arguments)
                logger.info(f"✅ MCP tool result: {result}")
                return result
                
        except Exception as e:
            logger.error(f"❌ MCP tool error: {str(e)}")
            raise e

# Initialize MCP manager
mcp_manager = MCPManager()

async def get_available_services_function(params: FunctionCallParams):
    """Get available car services from MCP server."""
    try:
        logger.info("Getting available car services...")
        
        result = await mcp_manager.call_mcp_tool("get_available_services", {})
        
        # Handle different result formats
        if isinstance(result, list):
            services = result
        elif isinstance(result, dict):
            services = result.get("services") or result.get("result") or []
        else:
            services = []
        
        response = {
            "status": "success",
            "message": f"Available services: {', '.join(services) if services else 'No services available'}",
            "services": services
        }
        
        await params.result_callback(response)
        
    except Exception as e:
        logger.error(f"Error getting available services: {str(e)}")
        await params.result_callback({
            "status": "error",
            "message": f"Failed to get available services: {str(e)}"
        })

async def schedule_car_service_function(params: FunctionCallParams):
    """Schedule a car service appointment using MCP server."""
    try:
        service_type = params.arguments.get("service_type")
        date = params.arguments.get("date")
        time = params.arguments.get("time")
        customer_name = params.arguments.get("customer_name")
        customer_email = params.arguments.get("customer_email")
        phone_number = params.arguments.get("phone_number")
        vehicle_model = params.arguments.get("vehicle_model")
        notes = params.arguments.get("notes", "")
        
        logger.info(f"Scheduling car service: {service_type} for {customer_name}")
        
        # Prepare arguments for MCP call
        mcp_arguments = {
            "service_type": service_type,
            "date": date,
            "time": time,
            "customer_name": customer_name,
            "customer_email": customer_email,
            "phone_number": phone_number,
            "vehicle_model": vehicle_model,
            "notes": notes
        }
        
        # Call MCP server
        result = await mcp_manager.call_mcp_tool("schedule_car_service", mcp_arguments)
        
        # Process the result
        if isinstance(result, dict) and result.get("success"):
            booking = result.get("booking", {})
            booking_id = booking.get("booking_id", "N/A")
            email_sent = result.get("email_sent", False)
            
            response = {
                "status": "success",
                "message": f"Car service appointment scheduled successfully! Booking ID: {booking_id}. " +
                          f"{'Confirmation email sent.' if email_sent else 'Email notification failed.'}",
                "booking_id": booking_id,
                "booking_details": booking
            }
        else:
            response = {
                "status": "error",
                "message": "Failed to schedule car service appointment"
            }
        
        await params.result_callback(response)
        
    except Exception as e:
        logger.error(f"Error scheduling car service: {str(e)}")
        await params.result_callback({
            "status": "error",
            "message": f"Failed to schedule car service: {str(e)}"
        })

async def run_bot(url: str, token: str, room_name: str):
    """Run the bot with LiveKit transport."""
    
    logger.info(f"Starting enhanced bot with MCP Car Service and LiveKit transport")
    logger.info(f"LiveKit URL: {url}, Room: {room_name}")

    # Initialize services
    stt = DeepgramSTTService(api_key=os.getenv("DEEPGRAM_API_KEY"))

    tts = CartesiaTTSService(
        api_key=os.getenv("CARTESIA_API_KEY"),
        voice_id="71a7ad14-091c-4e8e-a314-022ece01c121",  # British Reading Lady
    )

    llm = OpenAILLMService(api_key=os.getenv("OPENAI_API_KEY"))

    # Define function schemas for car service operations
    get_services_function = FunctionSchema(
        name="get_available_services",
        description="Get a list of available car services",
        properties={},
        required=[]
    )
    
    schedule_service_function = FunctionSchema(
        name="schedule_car_service",
        description="Schedule a car service appointment",
        properties={
            "service_type": {
                "type": "string",
                "description": "Type of car service needed (e.g., Oil Change, Brake Service, Tire Rotation)"
            },
            "date": {
                "type": "string", 
                "description": "Date for the appointment (YYYY-MM-DD format)"
            },
            "time": {
                "type": "string",
                "description": "Time for the appointment (HH:MM format)"
            },
            "customer_name": {
                "type": "string",
                "description": "Customer's full name"
            },
            "customer_email": {
                "type": "string",
                "description": "Customer's email address"
            },
            "phone_number": {
                "type": "string",
                "description": "Customer's phone number"
            },
            "vehicle_model": {
                "type": "string",
                "description": "Vehicle make and model"
            },
            "notes": {
                "type": "string",
                "description": "Additional notes or special requests"
            }
        },
        required=["service_type", "date", "time", "customer_name", "customer_email", "phone_number", "vehicle_model"]
    )
    
    # Create tools schema
    tools = ToolsSchema(standard_tools=[get_services_function, schedule_service_function])

    # Register function handlers - THIS IS THE CRITICAL PART THAT WORKS IN YOUR GOOGLE BOT
    llm.register_function("get_available_services", get_available_services_function)
    llm.register_function("schedule_car_service", schedule_car_service_function)

    messages = [
        {
            "role": "system",
            "content": """You are a helpful car service scheduling assistant with access to our car service system.
            You can help customers:
            1. Check available car services - use get_available_services function
            2. Schedule car service appointments - use schedule_car_service function
            
            When customers ask about services, first get the available services list.
            When scheduling appointments, gather all required information:
            - Service type (from available services)
            - Date and time for appointment
            - Customer name, email, and phone number  
            - Vehicle make and model
            - Any special notes or requests
            
            Always confirm the appointment details before scheduling. Be friendly, professional, 
            and conversational. Keep responses brief for voice interaction.""",
        },
    ]

    context = OpenAILLMContext(messages, tools)
    context_aggregator = llm.create_context_aggregator(context)

    # Initialize LiveKit transport
    transport = LiveKitTransport(
        url=url,
        token=token,
        room_name=room_name,
        params=LiveKitParams(
            audio_in_enabled=True,
            audio_out_enabled=True,
            vad_analyzer=SileroVADAnalyzer(),
        )
    )

    rtvi = None  # Remove RTVI processor to avoid compatibility issues

    # Build pipeline
    pipeline = Pipeline(
        [
            transport.input(),  # Transport user input
            stt,  # Speech to text
            context_aggregator.user(),  # User responses
            llm,  # LLM with function calling
            tts,  # Text to speech
            transport.output(),  # Transport bot output
            context_aggregator.assistant(),  # Assistant spoken responses
        ]
    )

    task = PipelineTask(
        pipeline,
        params=PipelineParams(
            enable_metrics=True,
            enable_usage_metrics=True,
        ),
        # Remove RTVI observer
    )

    @transport.event_handler("on_first_participant_joined")
    async def on_first_participant_joined(transport, participant):
        logger.info(f"First participant joined: {participant}")
        # Greet the user when they connect
        messages.append({
            "role": "system", 
            "content": "Greet the user warmly and let them know you can help them check available car services and schedule appointments."
        })
        await task.queue_frames([context_aggregator.user().get_context_frame()])

    @transport.event_handler("on_participant_disconnected")
    async def on_participant_disconnected(transport, participant):
        logger.info(f"Participant disconnected: {participant}")
        await task.cancel()

    # Run the pipeline
    runner = PipelineRunner(handle_sigint=False)  # Disable signal handling for Windows
    await runner.run(task)

if __name__ == "__main__":
    import argparse
    import asyncio
    from livekit import api

    # Validate LiveKit configuration
    if not all([LIVEKIT_URL, LIVEKIT_API_KEY, LIVEKIT_API_SECRET]):
        raise ValueError("LiveKit configuration incomplete. Please set LIVEKIT_URL, LIVEKIT_API_KEY, and LIVEKIT_API_SECRET")

    # Parse command line arguments
    parser = argparse.ArgumentParser(description="Car Service Bot with LiveKit")
    parser.add_argument("--room", type=str, default="car-service-room", help="Room name to join")
    args = parser.parse_args()

    room_name = args.room
    
    # Generate a token for the bot
    token = (
        api.AccessToken(LIVEKIT_API_KEY, LIVEKIT_API_SECRET)
        .with_identity("car-service-agent")
        .with_name("Car Service Assistant")
        .with_grants(api.VideoGrants(room_join=True, room=room_name))
        .to_jwt()
    )

    logger.info(f"Bot will join room: {room_name}")
    logger.info(f"Bot identity: car-service-agent")

    # Run the bot
    asyncio.run(run_bot(LIVEKIT_URL, token, room_name))