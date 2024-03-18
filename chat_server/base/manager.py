import uuid
import json
from fastapi import WebSocket


JOIN_ROOM = "join_room"
LEAVE_ROOM = "leave_room"
MESSAGE_CLIENT = "message_client"
MESSAGE_ROOM = "message_room"
CREATE_ROOM = "create_room"
LIST_ROOMS = "list_rooms"


class ClientCommandMessage:
    command: str # send_to_room, send_to_client, ban, leave_room, join_room
    info: str | None # room_id, client_id
    message: str | None

    def __init__(self, command, info = None, message = None) -> None:
        self.command = command
        self.info = info
        self.message = message

    @staticmethod
    def from_json(jsonStr: str):
        try:
            message = json.loads(jsonStr)
            return ClientCommandMessage(command=message["command"], info =message["info"], message=message["message"])
        except Exception  as e:
            return None
        

class Message:
    sender: uuid.UUID | None
    message: str
    is_exception: bool

    def __init__(self, message: str, sender: uuid.UUID | None, is_exception = False) -> None:
        self.message = message
        self.sender = sender
        self.is_exception = is_exception

    def to_json(self):
        return {
            "sender": self.sender,
            "message": self.message,
            "is_exception": self.is_exception,
            "server_message": self.sender == None
        }


class Client:
    id: uuid.UUID
    ws: WebSocket
    room: uuid.UUID | None
    def __init__(self, ws: WebSocket, id: uuid.UUID) -> None:
        self.id = id
        self.ws = ws

    def join_room(self, room_id: uuid.UUID):
        self.room = room_id    
    
    def leave_room(self):
        self.room = None

    async def receive_message(self, message: Message):
        await self.ws.send_json(message.to_json())   

    async def close(self):
        await self.ws.close()    

class Room:
    id: uuid.UUID
    name: str
    clients: set[uuid.UUID]
    def __init__(self, name: str) -> None:
        self.id = uuid.uuid4()
        self.name = name
        self.clients = set()      

    def client_join(self, client_id: uuid.UUID):
        self.clients.add(client_id)      

    def client_leave(self, client_id: uuid.UUID):
        self.clients.remove(client_id)  

    def is_empty(self):
        return  len(self.clients) == 0
    
    def to_json(self):
        return {
            "clients": list(map(lambda client: client.id, self.clients)),
            "name": self.name,
            "id": self.id
        }

class ChatManager:

    clients: dict[uuid.UUID, Client]
    rooms: dict[uuid.UUID, Room] # maps room id to set of client ids
    def __init__(self) -> None:
        self.clients = dict()
        self.rooms = dict()


    async def send_message_to_room(self, room_id: uuid.UUID, message: Message, ignore_id = None):
        if room_id in self.rooms:
            room = self.rooms[room_id]
            for user_id in room.clients:
                if user_id == ignore_id:
                    continue
                await self.send_message_to_client(user_id, message)

    async def send_message_to_client(self, client_id: uuid.UUID, message: Message):
        if client_id in self.clients:
            client = self.clients[client_id]
            await client.receive_message(message)


    async def handle_connection(self, connection: WebSocket, id: uuid.UUID):
        client = Client(connection, id=id)
        self.clients[client.id] = client
        while True:
            message = await connection.receive_text() # send_to_room:roomId:Message
            client_message = ClientCommandMessage.from_json(message)
            if client_message.command == JOIN_ROOM:
                room_id = client_message.info
                if room_id in self.rooms:
                    room = self.rooms[room_id]
                    room.client_join(client.id)
                    client.join_room(room_id)
            elif client_message.command == LEAVE_ROOM:
                room_id = client_message.info
                if room_id in self.rooms:
                    room = self.rooms[room_id]
                    room.client_leave(client.id)
                    client.leave_room()
                    if room.is_empty(): # remove the room completely if its empty
                        del self.rooms[room_id]
            elif client_message.command == MESSAGE_CLIENT:
                other_client_id = client_message.info
                await self.send_message_to_client(other_client_id, 
                                                Message(message=client_message.message, 
                                                        sender=client.id))
            elif client_message.command == MESSAGE_ROOM:
                if client.room is None: # client is not in a room but tries to send a room message
                    await client.receive_message(Message(message="Cannot send a room message, you are not a room member",
                                                        sender=None, is_exception=True))
                else:
                    await self.send_message_to_room(client.room, 
                                                    Message(message=client_message.message, 
                                                        sender=client.id), ignore_id=client.id)
            elif client_message.command == CREATE_ROOM:
                new_room = Room(name=client_message.info)
                new_room.client_join(client.id)
                client.join_room(new_room.id)
                self.rooms[room.id] = new_room
            elif client_message.command == LIST_ROOMS:
                rooms = { 
                    "rooms": list(map(lambda room: room.to_json(), self.rooms.values()))
                }
                await self.send_message_to_client(client.id, 
                                                Message(message=json.dumps(rooms)))




    async def close_connection(self, id: uuid.UUID):
        try:
            if id in self.clients:
                client = self.clients[id]
                if client.room and client.room in self.rooms:
                    room = self.rooms[client.room]
                    room.client_leave(client.id)
                    client.leave_room()
                    # notify the room that client has left
                    await self.send_message_to_room(room.id, 
                                                Message(message=f"{client.id} Has left the room",sender=None))
                del self.clients[id] # remove the connection
                client.close()
        except:
            pass # ignore this, might happen naturally   
