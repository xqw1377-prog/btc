import asyncio
import os
from dotenv import load_dotenv
from aurora.main_loop import MainLoop

def main():
    load_dotenv()
    
    api_key = os.getenv('BINANCE_API_KEY')
    api_secret = os.getenv('BINANCE_API_SECRET')
    testnet = os.getenv('TESTNET', 'true').lower() == 'true'
    
    if not api_key or not api_secret:
        print("Please set BINANCE_API_KEY and BINANCE_API_SECRET in .env file")
        return
    
    engine = MainLoop(api_key, api_secret, testnet)
    
    try:
        asyncio.run(engine.start())
    except KeyboardInterrupt:
        print("Stopping engine...")
        asyncio.run(engine.stop())

if __name__ == "__main__":
    main()
