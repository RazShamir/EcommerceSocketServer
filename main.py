from fastapi import FastAPI, WebSocket, WebSocketException
from chat_server.base.manager import ChatManager
import uuid 


app = FastAPI()
manager = ChatManager()

@app.websocket("/ws")
async def connect_ws(ws: WebSocket):
    await ws.accept()
    id = uuid.uuid4()
    try:
        await manager.handle_connection(connection=ws, id=id)
    except WebSocketException  as e:
        manager.close_connection(id)

