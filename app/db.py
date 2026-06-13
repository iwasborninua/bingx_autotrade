import aiomysql

from app import config


async def connect():
    return await aiomysql.connect(
        host=config.DB_HOST,
        port=config.DB_PORT,
        user=config.DB_USERNAME,
        password=config.DB_PASSWORD,
        db=config.DB_DATABASE,
        charset="utf8mb4",
        autocommit=True,
    )
