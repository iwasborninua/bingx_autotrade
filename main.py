if __name__ == "__main__":
    import asyncio

    from app.telegram.listener import run_listener

    asyncio.run(run_listener())
