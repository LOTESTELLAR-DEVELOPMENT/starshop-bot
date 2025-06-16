import asyncpg
import redis.asyncio as redis

async def create_pg_pool(dsn):
    return await asyncpg.create_pool(dsn)
 
async def create_redis_pool(url):
    return await redis.from_url(url) 