import asyncio
import threading
from bot import start_bot
from web import start_web_server
from config import WEB_HOST, WEB_PORT


def run_web():
    start_web_server(WEB_HOST, WEB_PORT)


async def main():
    web_thread = threading.Thread(target=run_web, daemon=True)
    web_thread.start()
    
    print(f'Веб-интерфейс доступен по ссылке: http://{WEB_HOST}:{WEB_PORT}')
    
    await start_bot()


if __name__ == '__main__':
    asyncio.run(main())
