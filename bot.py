import asyncio
import logging
from maxapi import Bot, Dispatcher
from maxapi.types import MessageCreated, BotStarted
from maxapi.types.message import NewMessageLink
from maxapi.enums.message_link_type import MessageLinkType
from database import db
from config import BOT_TOKEN
import queue
import threading
import os
import aiohttp
from pathlib import Path

logging.basicConfig(level=logging.INFO)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
bot_loop = None
message_queues = {}
queues_lock = threading.Lock()


@dp.bot_started()
async def handle_bot_started(event: BotStarted):
    await event.bot.send_message(
        chat_id=event.chat_id,
        text='Здравствуйте! Напишите ваш вопрос, оператор ответит в ближайшее время.'
    )


@dp.message_created()
async def handle_message(event: MessageCreated):
    try:
        chat_id = str(event.chat.chat_id)
        user_name = 'Пользователь'
        if event.from_user:
            user_name = event.from_user.first_name or event.from_user.username or f'User_{event.from_user.user_id}'
        
        text = event.message.body.text or ''
        message_id = event.message.body.mid
        file_path = None
        file_name = None
        file_type = None
        
        if hasattr(event.message.body, 'attachments') and event.message.body.attachments:
            for i, attachment in enumerate(event.message.body.attachments):
                file_id = None
                file_url = None
                
                try:
                    if hasattr(attachment, 'file_id'):
                        file_id = attachment.file_id
                    elif hasattr(attachment, 'payload') and hasattr(attachment.payload, 'file_id'):
                        file_id = attachment.payload.file_id
                    
                    if hasattr(attachment, 'url'):
                        file_url = attachment.url
                    elif hasattr(attachment, 'payload') and hasattr(attachment.payload, 'url'):
                        file_url = attachment.payload.url
                    
                    if hasattr(attachment, 'file_name'):
                        file_name = attachment.file_name
                    elif hasattr(attachment, 'name'):
                        file_name = attachment.name
                    elif hasattr(attachment, 'payload'):
                        if hasattr(attachment.payload, 'file_name'):
                            file_name = attachment.payload.file_name
                        elif hasattr(attachment.payload, 'name'):
                            file_name = attachment.payload.name
                    
                    if not file_name:
                        if file_id:
                            file_name = f'file_{file_id}.jpg'
                        elif file_url and 'id=' in file_url:
                            file_id_from_url = file_url.split('id=')[1].split('&')[0]
                            file_name = f'file_{file_id_from_url}.jpg'
                        else:
                            file_name = f'file_{message_id}_{i}.jpg'
                    
                    if file_id or file_url:
                        uploads_dir = Path('uploads')
                        uploads_dir.mkdir(exist_ok=True)
                        
                        try:
                            file_content = None
                            content_type = None
                            
                            if file_id and hasattr(bot, 'download_file'):
                                try:
                                    file_content = await bot.download_file(file_id)
                                except:
                                    pass
                            
                            if file_url and not file_content:
                                async with aiohttp.ClientSession() as session:
                                    async with session.get(file_url) as resp:
                                        if resp.status == 200:
                                            file_content = await resp.read()
                                            content_type = resp.headers.get('Content-Type', '')
                            
                            if not file_content:
                                continue
                            
                            file_extension = ''
                            if '.' in file_name:
                                file_extension = file_name.split('.')[-1].lower()
                            
                            if content_type:
                                if 'image' in content_type:
                                    file_type = 'image'
                                    if not file_extension:
                                        file_name += '.jpg' if 'jpeg' in content_type or 'jpg' in content_type else '.png' if 'png' in content_type else '.gif' if 'gif' in content_type else '.jpg'
                                elif 'audio' in content_type:
                                    file_type = 'audio'
                                    if not file_extension:
                                        file_name += '.mp3' if 'mpeg' in content_type or 'mp3' in content_type else '.ogg' if 'ogg' in content_type else '.mp3'
                                elif 'video' in content_type:
                                    file_type = 'video'
                                    if not file_extension:
                                        file_name += '.mp4'
                                elif 'pdf' in content_type:
                                    file_type = 'document'
                                    if not file_extension:
                                        file_name += '.pdf'
                                else:
                                    file_type = 'file'
                            
                            if not content_type or file_type == 'file':
                                if file_extension:
                                    if file_extension in ['jpg', 'jpeg', 'png', 'gif', 'webp', 'bmp', 'svg']:
                                        file_type = 'image'
                                    elif file_extension in ['mp3', 'wav', 'ogg', 'flac', 'm4a', 'aac']:
                                        file_type = 'audio'
                                    elif file_extension in ['mp4', 'avi', 'mov', 'mkv', 'webm']:
                                        file_type = 'video'
                                    elif file_extension in ['pdf', 'doc', 'docx', 'txt', 'xls', 'xlsx', 'ppt', 'pptx']:
                                        file_type = 'document'
                                    else:
                                        file_type = 'file'
                                else:
                                    file_type = 'file'
                            
                            file_path = f'uploads/{chat_id}_{message_id}_{file_name}'
                            with open(file_path, 'wb') as f:
                                f.write(file_content)
                            
                            if not text:
                                text = f'[{file_type}]'
                            break
                        except Exception as e:
                            logging.error(f'Ошибка при скачивании файла: {e}')
                except Exception as e:
                    logging.error(f'Ошибка при обработке attachment: {e}')
        
        if not text and not file_path:
            return
        
        logging.info(f'Получено сообщение от {user_name} (chat_id={chat_id})')
        
        msg = await db.add_message(chat_id, user_name, text, from_bot=False, message_id=message_id, 
                                   file_path=file_path, file_name=file_name, file_type=file_type)
        
        with queues_lock:
            if chat_id in message_queues:
                message_queues[chat_id].put(msg)
    except Exception as e:
        logging.error(f'Ошибка обработки сообщения: {e}')


async def send_message_to_user(chat_id: str, text: str, reply_to: str = None):
    link = None
    reply_to_data = None
    
    if reply_to:
        msg_data = await db.get_message_by_mid(reply_to)
        if msg_data:
            reply_to_data = {'user_name': msg_data.user_name, 'text': msg_data.text}
            
            if reply_to.startswith('temp_'):
                quoted_text = msg_data.text[:100] if len(msg_data.text) > 100 else msg_data.text
                text = f"↩️ {msg_data.user_name}: {quoted_text}\n\n{text}"
            else:
                link = NewMessageLink(type=MessageLinkType.REPLY, mid=reply_to)
    
    response = await bot.send_message(chat_id=int(chat_id), text=text, link=link)
    message_id = response.body.mid if hasattr(response, 'body') else None
    
    msg = await db.add_message(chat_id, 'Оператор', text, from_bot=True, message_id=message_id)
    msg.reply_to = reply_to_data
    
    with queues_lock:
        if chat_id in message_queues:
            message_queues[chat_id].put(msg)


def send_message_sync(chat_id: str, text: str, reply_to: str = None):
    if bot_loop and bot_loop.is_running():
        future = asyncio.run_coroutine_threadsafe(send_message_to_user(chat_id, text, reply_to), bot_loop)
        future.result(timeout=10)
    else:
        raise RuntimeError('Bot loop is not running')


def subscribe_sync(chat_id: str) -> queue.Queue:
    with queues_lock:
        if chat_id not in message_queues:
            message_queues[chat_id] = queue.Queue()
        return message_queues[chat_id]


def unsubscribe_sync(chat_id: str):
    with queues_lock:
        if chat_id in message_queues:
            del message_queues[chat_id]


async def start_bot():
    global bot_loop
    await db.init()
    bot_loop = asyncio.get_event_loop()
    await dp.start_polling(bot)
