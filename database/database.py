import pymongo, os
from config import DB_URI, DB_NAME

dbclient = pymongo.MongoClient(DB_URI)
database = dbclient[DB_NAME]

user_data = database['users']

async def present_user(user_id : int):
    found = user_data.find_one({'_id': user_id})
    return bool(found)

async def add_user(user_id: int):
    user_data.insert_one({'_id': user_id})
    return

async def full_userbase():
    user_docs = user_data.find()
    user_ids = []
    for doc in user_docs:
        user_ids.append(doc['_id'])
        
    return user_ids

async def del_user(user_id: int):
    user_data.delete_one({'_id': user_id})
    return

async def update_shortener(user_id: int, site: str, api: str):
    user_data.update_one(
        {'_id': user_id},
        {'$set': {'shortener': site, 'shortener_api': api}},
        upsert=True
    )
    return

async def get_shortener(user_id: int):
    user = user_data.find_one({'_id': user_id})
    if user and 'shortener' in user and 'shortener_api' in user:
        return user['shortener'], user['shortener_api']
    return None, None
