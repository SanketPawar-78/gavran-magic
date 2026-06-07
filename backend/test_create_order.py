from pymongo import MongoClient
from bson.objectid import ObjectId
import os
from dotenv import load_dotenv

load_dotenv('d:\\Projects\\Gavran Magic Website\\gavran-magic\\backend\\.env')
client = MongoClient(os.getenv('MONGO_URI'))
db = client.get_database()

db.orders.update_one(
    {'_id': ObjectId('69cfbcf8bb41c4010cc19692')},
    {'$set': {
        'order_status': 'Shipped',
        'tracking_id': '1269057348',
        'shipment_id': '1265353946'
    }}
)
print("Order updated to Shipped status!")
