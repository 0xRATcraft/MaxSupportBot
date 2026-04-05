from flask import Flask, render_template, request, jsonify, session, redirect, url_for, send_from_directory
from flask_socketio import SocketIO, emit, join_room
import asyncio
from threading import Thread
from database import db
from bot import send_message_sync, subscribe_sync, unsubscribe_sync
from config import WEB_PASSWORD
import secrets
import os
from werkzeug.utils import secure_filename
from pathlib import Path


app = Flask(__name__)
app.config['SECRET_KEY'] = secrets.token_hex(32)
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')

Path(app.config['UPLOAD_FOLDER']).mkdir(exist_ok=True)


@app.route('/uploads/<path:filename>')
def uploaded_file(filename):
    if not session.get('authenticated'):
        return jsonify({'error': 'Unauthorized'}), 401
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        password = request.json.get('password')
        if password == WEB_PASSWORD:
            session['authenticated'] = True
            return jsonify({'success': True})
        return jsonify({'success': False, 'error': 'Неверный пароль'}), 401
    
    return render_template('login.html')


@app.route('/logout')
def logout():
    session.pop('authenticated', None)
    return redirect(url_for('login'))


@app.route('/')
def index():
    if not session.get('authenticated'):
        return redirect(url_for('login'))
    return render_template('index.html')


@app.route('/api/chats')
def get_chats():
    if not session.get('authenticated'):
        return jsonify({'error': 'Unauthorized'}), 401
    
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    chats = loop.run_until_complete(db.get_all_chats())
    loop.close()
    
    return jsonify([{
        'chat_id': chat.chat_id,
        'user_name': chat.user_name,
        'last_message': chat.messages[-1].text if chat.messages else '',
        'last_activity': chat.last_activity.strftime('%H:%M:%S'),
        'unread_count': chat.unread_count
    } for chat in chats])


@app.route('/api/chat/<chat_id>')
def get_chat(chat_id):
    if not session.get('authenticated'):
        return jsonify({'error': 'Unauthorized'}), 401
    
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    chat = loop.run_until_complete(db.get_chat(chat_id))
    loop.run_until_complete(db.mark_as_read(chat_id))
    loop.close()
    
    if not chat:
        return jsonify({'error': 'Chat not found'}), 404
    
    return jsonify({
        'chat_id': chat.chat_id,
        'user_name': chat.user_name,
        'messages': [{
            'text': msg.text,
            'from_bot': msg.from_bot,
            'timestamp': msg.timestamp.strftime('%H:%M:%S'),
            'user_name': msg.user_name,
            'message_id': msg.message_id,
            'file_path': msg.file_path,
            'file_name': msg.file_name,
            'file_type': msg.file_type
        } for msg in chat.messages]
    })


@socketio.on('join_chat')
def handle_join_chat(data):
    chat_id = data['chat_id']
    join_room(chat_id)
    
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(db.mark_as_read(chat_id))
    loop.close()
    
    def listen():
        q = subscribe_sync(chat_id)
        
        try:
            while True:
                msg = q.get(timeout=30)
                msg_data = {
                    'text': msg.text,
                    'from_bot': msg.from_bot,
                    'timestamp': msg.timestamp.strftime('%H:%M:%S'),
                    'user_name': msg.user_name,
                    'message_id': msg.message_id,
                    'file_path': msg.file_path,
                    'file_name': msg.file_name,
                    'file_type': msg.file_type
                }
                if hasattr(msg, 'reply_to') and msg.reply_to:
                    msg_data['reply_to'] = msg.reply_to
                
                socketio.emit('new_message', msg_data, room=chat_id)
                
                if not msg.from_bot:
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    loop.run_until_complete(db.mark_as_read(chat_id))
                    loop.close()
        except:
            pass
        finally:
            unsubscribe_sync(chat_id)
    
    Thread(target=listen, daemon=True).start()


@socketio.on('upload_file')
def handle_upload_file(data):
    if not session.get('authenticated'):
        socketio.emit('upload_error', {'error': 'Unauthorized'})
        return
    
    try:
        chat_id = data['chat_id']
        file_data = data['file']
        file_name = secure_filename(data['file_name'])
        
        file_type = 'file'
        if any(file_name.lower().endswith(ext) for ext in ['.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp']):
            file_type = 'image'
        
        import base64
        file_bytes = base64.b64decode(file_data.split(',')[1])
        
        file_path = f'uploads/web_{chat_id}_{file_name}'
        with open(file_path, 'wb') as f:
            f.write(file_bytes)
        
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        msg = loop.run_until_complete(
            db.add_message(chat_id, 'Оператор', f'[{file_type}]', from_bot=True, 
                          message_id=f'web_{chat_id}_{file_name}',
                          file_path=file_path, file_name=file_name, file_type=file_type)
        )
        loop.close()
        
        msg_data = {
            'text': msg.text,
            'from_bot': msg.from_bot,
            'timestamp': msg.timestamp.strftime('%H:%M:%S'),
            'user_name': msg.user_name,
            'message_id': msg.message_id,
            'file_path': msg.file_path,
            'file_name': msg.file_name,
            'file_type': msg.file_type
        }
        
        socketio.emit('new_message', msg_data, room=chat_id)
        socketio.emit('upload_success', {'success': True})
    except Exception as e:
        socketio.emit('upload_error', {'error': str(e)})
        traceback.print_exc()
        socketio.emit('upload_error', {'error': str(e)})


@socketio.on('send_message')
def handle_send_message(data):
    print(f'Received send_message: {data}')
    chat_id = data['chat_id']
    text = data['text']
    reply_to = data.get('reply_to')
    
    try:
        send_message_sync(chat_id, text, reply_to)
        print(f'Message sent successfully to {chat_id}, reply_to={reply_to}')
        socketio.emit('message_sent', {'success': True})
    except Exception as e:
        print(f'Error sending message: {e}')
        import traceback
        traceback.print_exc()
        socketio.emit('message_sent', {'success': False, 'error': str(e)})


def start_web_server(host: str, port: int):
    socketio.run(app, host=host, port=port, debug=False, allow_unsafe_werkzeug=True)
@socketio.on('send_message')
def handle_send_message(data):
    chat_id = data['chat_id']
    text = data['text']
    reply_to = data.get('reply_to')
    
    try:
        send_message_sync(chat_id, text, reply_to)
        socketio.emit('message_sent', {'success': True})
    except Exception as e:
        socketio.emit('message_sent', {'success': False, 'error': str(e)})