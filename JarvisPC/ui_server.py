"""
FastAPI server to power the modern Jarvis web UI.

This tiny server exposes two endpoints:

  - GET `/` serves the main UI HTML page.
  - POST `/event` accepts JSON events from the assistant and queues them
    for broadcast to connected web socket clients.
  - WebSocket `/ws` streams events down to the browser in real time.

To run this server locally:

  $ uvicorn ui_server:app --host 127.0.0.1 --port 8787 --reload

Then visit http://127.0.0.1:8787 in your browser to see the overlay.

See `ui/index.html` for the corresponding frontend implementation.
"""

import asyncio
import json
import os
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

app = FastAPI()

# Serve static files out of the ./ui directory
app.mount("/ui", StaticFiles(directory="ui"), name="ui")

# In-memory queue of events and set of connected clients
clients: set[WebSocket] = set()
queue: asyncio.Queue = asyncio.Queue()


@app.get("/")
async def root() -> FileResponse:
    """Serve the main UI page."""
    return FileResponse("ui/index.html")


@app.post("/event")
async def event(req: Request):
    """Receive an event from the assistant and queue it for broadcast."""
    try:
        data = await req.json()
    except Exception:
        return {"ok": False, "error": "invalid JSON"}
    await queue.put(data)
    return {"ok": True}


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """Accept a websocket connection and forward events."""
    await websocket.accept()
    clients.add(websocket)
    try:
        while True:
            data = await queue.get()
            # broadcast to all clients
            dead: list[WebSocket] = []
            for ws in list(clients):
                try:
                    await ws.send_text(json.dumps(data))
                except WebSocketDisconnect:
                    dead.append(ws)
                except Exception:
                    dead.append(ws)
            for d in dead:
                clients.discard(d)
    except Exception:
        clients.discard(websocket)
