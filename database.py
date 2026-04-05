import aiosqlite
from datetime import datetime
from typing import List, Optional
from dataclasses import dataclass


@dataclass
class Message:
    id: int
    chat_id: str
    user_name: str
    text: str
    timestamp: datetime
    from_bot: bool
    message_id: Optional[str] = None
    file_path: Optional[str] = None
    file_name: Optional[str] = None
    file_type: Optional[str] = None


@dataclass
class Chat:
    chat_id: str
    user_name: str
    messages: List[Message]
    unread_count: int
    last_activity: datetime


class Database:
    def __init__(self, db_path: str = 'support_bot.db'):
        self.db_path = db_path
    
    async def init(self):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute('''
                CREATE TABLE IF NOT EXISTS chats (
                    chat_id TEXT PRIMARY KEY,
                    user_name TEXT NOT NULL,
                    unread_count INTEGER DEFAULT 0,
                    last_activity TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            await db.execute('''
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    chat_id TEXT NOT NULL,
                    user_name TEXT NOT NULL,
                    text TEXT NOT NULL,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    from_bot INTEGER DEFAULT 0,
                    message_id TEXT,
                    file_path TEXT,
                    file_name TEXT,
                    file_type TEXT,
                    FOREIGN KEY (chat_id) REFERENCES chats(chat_id)
                )
            ''')
            
            await db.commit()
    
    async def add_message(self, chat_id: str, user_name: str, text: str, from_bot: bool = False, message_id: Optional[str] = None, file_path: Optional[str] = None, file_name: Optional[str] = None, file_type: Optional[str] = None) -> Message:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute('''
                INSERT OR IGNORE INTO chats (chat_id, user_name, unread_count, last_activity)
                VALUES (?, ?, 0, ?)
            ''', (chat_id, user_name, datetime.now()))
            
            await db.execute('''
                UPDATE chats 
                SET last_activity = ?, 
                    unread_count = unread_count + ?
                WHERE chat_id = ?
            ''', (datetime.now(), 0 if from_bot else 1, chat_id))
            
            cursor = await db.execute('''
                INSERT INTO messages (chat_id, user_name, text, timestamp, from_bot, message_id, file_path, file_name, file_type)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (chat_id, user_name, text, datetime.now(), 1 if from_bot else 0, message_id, file_path, file_name, file_type))
            
            await db.commit()
            
            return Message(
                id=cursor.lastrowid,
                chat_id=chat_id,
                user_name=user_name,
                text=text,
                timestamp=datetime.now(),
                from_bot=from_bot,
                message_id=message_id,
                file_path=file_path,
                file_name=file_name,
                file_type=file_type
            )
    
    async def mark_as_read(self, chat_id: str):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute('UPDATE chats SET unread_count = 0 WHERE chat_id = ?', (chat_id,))
            await db.commit()
    
    async def get_chat(self, chat_id: str) -> Optional[Chat]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            
            cursor = await db.execute('SELECT * FROM chats WHERE chat_id = ?', (chat_id,))
            chat_row = await cursor.fetchone()
            
            if not chat_row:
                return None
            
            cursor = await db.execute('''
                SELECT * FROM messages 
                WHERE chat_id = ? 
                ORDER BY timestamp ASC
            ''', (chat_id,))
            
            message_rows = await cursor.fetchall()
            
            messages = [
                Message(
                    id=row['id'],
                    chat_id=row['chat_id'],
                    user_name=row['user_name'],
                    text=row['text'],
                    timestamp=datetime.fromisoformat(row['timestamp']),
                    from_bot=bool(row['from_bot']),
                    message_id=row['message_id'],
                    file_path=row['file_path'] if 'file_path' in row.keys() else None,
                    file_name=row['file_name'] if 'file_name' in row.keys() else None,
                    file_type=row['file_type'] if 'file_type' in row.keys() else None
                )
                for row in message_rows
            ]
            
            return Chat(
                chat_id=chat_row['chat_id'],
                user_name=chat_row['user_name'],
                messages=messages,
                unread_count=chat_row['unread_count'],
                last_activity=datetime.fromisoformat(chat_row['last_activity'])
            )
    
    async def get_all_chats(self) -> List[Chat]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            
            cursor = await db.execute('SELECT * FROM chats ORDER BY last_activity DESC')
            chat_rows = await cursor.fetchall()
            
            chats = []
            for chat_row in chat_rows:
                cursor = await db.execute('''
                    SELECT * FROM messages 
                    WHERE chat_id = ? 
                    ORDER BY timestamp ASC
                ''', (chat_row['chat_id'],))
                
                message_rows = await cursor.fetchall()
                
                messages = [
                    Message(
                        id=row['id'],
                        chat_id=row['chat_id'],
                        user_name=row['user_name'],
                        text=row['text'],
                        timestamp=datetime.fromisoformat(row['timestamp']),
                        from_bot=bool(row['from_bot']),
                        message_id=row['message_id'],
                        file_path=row['file_path'] if 'file_path' in row.keys() else None,
                        file_name=row['file_name'] if 'file_name' in row.keys() else None,
                        file_type=row['file_type'] if 'file_type' in row.keys() else None
                    )
                    for row in message_rows
                ]
                
                chats.append(Chat(
                    chat_id=chat_row['chat_id'],
                    user_name=chat_row['user_name'],
                    messages=messages,
                    unread_count=chat_row['unread_count'],
                    last_activity=datetime.fromisoformat(chat_row['last_activity'])
                ))
            
            return chats
    
    async def get_message_by_mid(self, message_id: str) -> Optional[Message]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute('SELECT * FROM messages WHERE message_id = ?', (message_id,))
            row = await cursor.fetchone()
            
            if not row:
                return None
            
            return Message(
                id=row['id'],
                chat_id=row['chat_id'],
                user_name=row['user_name'],
                text=row['text'],
                timestamp=datetime.fromisoformat(row['timestamp']),
                from_bot=bool(row['from_bot']),
                message_id=row['message_id'],
                file_path=row['file_path'] if 'file_path' in row.keys() else None,
                file_name=row['file_name'] if 'file_name' in row.keys() else None,
                file_type=row['file_type'] if 'file_type' in row.keys() else None
            )


db = Database()
