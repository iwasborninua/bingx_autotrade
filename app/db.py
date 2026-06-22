import warnings

import aiomysql

from app import config


warnings.filterwarnings("ignore", message=r"Table '.*' already exists", category=Warning)
warnings.filterwarnings("ignore", message=r".*'VALUES function' is deprecated.*", category=Warning)


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
