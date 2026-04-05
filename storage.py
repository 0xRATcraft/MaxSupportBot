from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List
import asyncio
import queue
import threading


@dataclass
class Message:
    chat_id: str
    user_name: str
    text: str
    timestamp: datetime
    from_bot: bool = False
    message_id: str = None


@dataclass
class Chat:
    chat_id: str
    user_name: str
    messages: List[Message] = field(default_factory=list)
    unread_count: int = 0
    last_activity: datetime = field(default_factory=datetime.now)


class ChatStorage:
    def __init__(self):
        self.chats: Dict[str, Chat] = {}
        self.active_sessions: Dict[str, queue.Queue] = {}
        self._lock = threading.Lock()

    async def add_message(self, chat_id: str, user_name: str, text: str, from_bot: bool = False, message_id: str = None):
        with self._lock:
            if chat_id not in self.chats:
                self.chats[chat_id] = Chat(chat_id=chat_id, user_name=user_name)
            
            message = Message(
                chat_id=chat_id,
                user_name=user_name,
                text=text,
                timestamp=datetime.now(),
                from_bot=from_bot,
                message_id=message_id
            )
            
            self.chats[chat_id].messages.append(message)
            self.chats[chat_id].last_activity = datetime.now()
            
            if not from_bot:
                self.chats[chat_id].unread_count += 1
            
            if chat_id in self.active_sessions:
                self.active_sessions[chat_id].put(message)
            
            return message

    async def mark_as_read(self, chat_id: str):
        with self._lock:
            if chat_id in self.chats:
                self.chats[chat_id].unread_count = 0

    async def get_chat(self, chat_id: str) -> Chat:
        return self.chats.get(chat_id)

    async def get_all_chats(self) -> List[Chat]:
        return sorted(self.chats.values(), key=lambda c: c.last_activity, reverse=True)

    def subscribe_sync(self, chat_id: str) -> queue.Queue:
        with self._lock:
            if chat_id not in self.active_sessions:
                self.active_sessions[chat_id] = queue.Queue()
            return self.active_sessions[chat_id]

    def unsubscribe_sync(self, chat_id: str):
        with self._lock:
            if chat_id in self.active_sessions:
                del self.active_sessions[chat_id]


storage = ChatStorage()
