#!/usr/bin/env python3
"""
MCP HTTP server (FastAPI) exposing:
- initialize
- list_tools
- call_tool (get_available_services, schedule_car_service)
"""

import os
import logging
from datetime import datetime
from typing import List, Dict, Any, Optional

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

# Optional email integration
try:
    from composio import Composio
except Exception:
    Composio = None

# ----------------------------
# Env & logging
# ----------------------------
load_dotenv()

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] MCP_SERVER: %(message)s",
)

COMPOSIO_API_KEY = os.getenv("COMPOSIO_API_KEY", "")
CONNECTED_ACCOUNT_ID = os.getenv("CONNECTED_ACCOUNT_ID", "")
MCP_PORT = int(os.getenv("MCP_PORT", "8000"))
ALLOW_ORIGINS = os.getenv("MCP_CORS_ORIGINS", "*")

logging.debug(f"🌐 MCP_PORT: {MCP_PORT}")

# ----------------------------
# Composio init
# ----------------------------
composio = None
if Composio and COMPOSIO_API_KEY:
    try:
        composio = Composio(api_key=COMPOSIO_API_KEY)
        logging.info("✅ Composio initialized.")
    except Exception as e:
        logging.error(f"❌ Composio init error: {e}")
        composio = None
else:
    logging.warning("⚠️ Composio not configured — email sending will be mocked.")

# ----------------------------
# MCP logic
# ----------------------------
def _available_services() -> List[str]:
    return [
        "Oil Change", "Brake Service", "Tire Rotation", "Engine Tune-up",
        "Transmission Service", "Air Filter Replacement", "Battery Check",
        "General Inspection", "Wheel Alignment", "AC Service",
    ]

def _send_confirmation_email(to_email: str, subject: str, content: str) -> dict:
    try:
        if not composio:
            logging.warning("Mocking email send — Composio not initialized.")
            return {"success": False, "result": f"Mock email to {to_email}"}
        result = composio.tools.execute(
            "GMAIL_SEND_EMAIL",
            connected_account_id=CONNECTED_ACCOUNT_ID,
            arguments={"recipient_email": to_email, "subject": subject, "body": content},
        )
        return {"success": True, "result": result}
    except Exception as e:
        logging.error(f"Email send error: {e}")
        return {"success": False, "error": str(e)}

class CarServiceMCPServer:
    async def initialize(self, params: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        logging.debug(f"🔄 initialize(params={params})")
        protocol_version = None
        capabilities: Dict[str, Any] = {}
        client_info: Dict[str, Any] = {}
        if isinstance(params, dict):
            protocol_version = params.get("protocolVersion") or params.get("protocol_version")
            capabilities = params.get("capabilities", {}) or {}
            client_info = params.get("clientInfo") or params.get("client_info") or {}
        logging.info(f"🤝 MCP handshake with client: {client_info}")
        return {
            "protocolVersion": protocol_version or "0.1.0",
            "capabilities": capabilities,
            "serverInfo": {"name": "car-service-mcp", "version": "1.0.0"},
        }

    async def list_tools(self, _params: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
        logging.debug("🧰 list_tools()")
        return [
            {
                "name": "get_available_services",
                "description": "List all available car services.",
                "inputSchema": {"type": "object", "properties": {}},
            },
            {
                "name": "schedule_car_service",
                "description": "Schedule a car service booking.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "service_type": {"type": "string"},
                        "date": {"type": "string"},
                        "time": {"type": "string"},
                        "customer_name": {"type": "string"},
                        "customer_email": {"type": "string"},
                        "phone_number": {"type": "string"},
                        "vehicle_model": {"type": "string"},
                        "notes": {"type": "string"},
                    },
                    "required": [
                        "service_type", "date", "time",
                        "customer_name", "customer_email",
                        "phone_number", "vehicle_model",
                    ],
                },
            },
        ]

    async def call_tool(self, params: Dict[str, Any]) -> Any:
        logging.debug(f"🛠️ call_tool(params={params})")
        if not isinstance(params, dict):
            raise ValueError("call_tool: params must be an object")

        name = params.get("name")
        arguments = params.get("arguments") or {}
        if not name:
            raise ValueError("call_tool: 'name' is required")

        if name == "get_available_services":
            return _available_services()

        if name == "schedule_car_service":
            required = [
                "service_type", "date", "time",
                "customer_name", "customer_email",
                "phone_number", "vehicle_model",
            ]
            missing = [k for k in required if k not in arguments]
            if missing:
                raise ValueError(f"Missing required arguments: {missing}")

            booking_id = f"CAR-{datetime.now().strftime('%Y%m%d%H%M%S')}"
            booking = {
                "booking_id": booking_id,
                "service_type": arguments["service_type"],
                "date": arguments["date"],
                "time": arguments["time"],
                "customer": {
                    "name": arguments["customer_name"],
                    "email": arguments["customer_email"],
                    "phone": arguments["phone_number"],
                },
                "vehicle": {"model": arguments["vehicle_model"]},
                "notes": arguments.get("notes", ""),
                "status": "confirmed",
                "created_at": datetime.now().isoformat(),
            }
            
            # UPDATE THIS PART - Enhanced email content
            subject = f"🚗 Car Service Confirmation - {booking_id}"
            content = f"""Dear {arguments['customer_name']},

Thank you for choosing our car service! We are pleased to confirm your appointment.

BOOKING DETAILS:
• Booking ID: {booking_id}
• Customer Name: {arguments['customer_name']}
• Phone Number: {arguments['phone_number']}
• Service Type: {arguments['service_type']}
• Date: {arguments['date']}
• Time: {arguments['time']}
• Vehicle Model: {arguments['vehicle_model']}

We look forward to servicing your vehicle. Please arrive 10 minutes early and bring your vehicle registration documents.

If you need to reschedule or have any questions, please contact us at your earliest convenience.

Best regards,
Car Service Team"""
            
            email_result = _send_confirmation_email(arguments["customer_email"], subject, content)
            return {
                "success": True,
                "booking": booking,
                "email_sent": bool(email_result.get("success")),
                "email_details": email_result.get("result"),
            }

        raise ValueError(f"Unknown tool: {name}")

server_impl = CarServiceMCPServer()

# ----------------------------
# FastAPI app
# ----------------------------
app = FastAPI(title="MCP HTTP Server (Car Service)")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in ALLOW_ORIGINS.split(",")] if ALLOW_ORIGINS else ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/health")
async def health():
    return {"ok": True, "server": "car-service-mcp", "version": "1.0.0"}

@app.post("/mcp")
async def mcp_endpoint(request: Request):
    try:
        payload = await request.json()
        logging.debug(f"📥 /mcp payload: {payload}")

        if not isinstance(payload, dict) or payload.get("jsonrpc") != "2.0":
            return JSONResponse(
                status_code=200,
                content={"jsonrpc": "2.0", "id": payload.get("id") if isinstance(payload, dict) else None,
                         "error": {"code": -32600, "message": "Invalid Request"}},
            )

        req_id = payload.get("id")
        method = payload.get("method")
        params = payload.get("params")

        if method == "initialize":
            result = await server_impl.initialize(params)
        elif method == "list_tools":
            result = await server_impl.list_tools(params)
        elif method == "call_tool":
            result = await server_impl.call_tool(params or {})
        else:
            return JSONResponse(
                status_code=200,
                content={"jsonrpc": "2.0", "id": req_id,
                         "error": {"code": -32601, "message": f"Method not found: {method}"}},
            )

        return JSONResponse(status_code=200, content={"jsonrpc": "2.0", "id": req_id, "result": result})

    except ValueError as ve:
        return JSONResponse(
            status_code=200,
            content={"jsonrpc": "2.0", "id": None, "error": {"code": -32602, "message": str(ve)}},
        )
    except Exception:
        return JSONResponse(
            status_code=200,
            content={"jsonrpc": "2.0", "id": None, "error": {"code": -32603, "message": "Internal error"}},
        )

if __name__ == "__main__":
    uvicorn.run("mcp_server:app", host="0.0.0.0", port=MCP_PORT, reload=False)