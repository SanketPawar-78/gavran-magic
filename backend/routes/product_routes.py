from flask import Blueprint, jsonify, request
from extensions import get_db
from bson import ObjectId
from middleware.auth_middleware import admin_required, token_required

product_bp = Blueprint('product_bp', __name__)

# Base URL for images — served from Netlify frontend /public/images/
IMAGE_BASE = "https://gavran-magic.netlify.app/images"

# Removed DEFAULTS array as requested by user - all products will only be added through admin dashboard.

@product_bp.route('/', methods=['GET'])
def get_products():
    """Fetch all products."""
    db = get_db()
    products_coll = db.products
    
    # Fetch all products (admin vs public filtering shifted to frontend display logic)
    products = list(products_coll.find())

    for p in products:
        p['_id'] = str(p['_id'])
        # Fallbacks for existing products
        if 'images' not in p:
            p['images'] = [p.get('image')] if p.get('image') else []
        if 'stock' not in p:
            p['stock'] = 100
        if 'discount' not in p:
            p['discount'] = 0
        if 'status' not in p:
            p['status'] = 'active'
            
    return jsonify(products), 200


@product_bp.route('/<id>', methods=['GET'])
def get_product(id):
    db = get_db()
    product = db.products.find_one({'_id': ObjectId(id)})
    if product:
        product['_id'] = str(product['_id'])
        if 'images' not in product:
            product['images'] = [product.get('image')] if product.get('image') else []
        if 'stock' not in product:
            product['stock'] = 100
        if 'discount' not in product:
            product['discount'] = 0
        return jsonify(product), 200
    return jsonify({'message': 'Product not found'}), 404

# --- Review Routes ---

@product_bp.route('/<id>/reviews', methods=['GET'])
def get_reviews(id):
    db = get_db()
    reviews = list(db.reviews.find({'product_id': id}).sort('timestamp', -1))
    for r in reviews:
        r['_id'] = str(r['_id'])
    return jsonify(reviews), 200

@product_bp.route('/<id>/reviews', methods=['POST'])
@token_required
def add_review(current_user, id):
    db = get_db()
    data = request.json
    review = {
        "product_id": id,
        "user_name": data.get("user_name", "Anonymous"),
        "user_id": data.get("user_id", "guest"),
        "rating": int(data.get("rating", 5)),
        "title": data.get("title", ""),
        "comment": data.get("comment", ""),
        "photo": data.get("photo"), # base64 string
        "timestamp": data.get("timestamp") or ""
    }
    db.reviews.insert_one(review)
    return jsonify({"message": "Review added successfully"}), 201


# Admin Routes
@product_bp.route('/', methods=['POST'])
@admin_required
def add_product(current_admin):
    db = get_db()
    data = request.json
    db.products.insert_one(data)
    return jsonify({'message': 'Product added'}), 201


@product_bp.route('/<id>', methods=['PUT'])
@admin_required
def update_product(current_admin, id):
    db = get_db()
    data = request.json
    # MongoDB update requires $set if we only want to update specific fields
    db.products.update_one({'_id': ObjectId(id)}, {'$set': data})
    return jsonify({'message': 'Product updated'}), 200


@product_bp.route('/<id>', methods=['DELETE'])
@admin_required
def delete_product(current_admin, id):
    db = get_db()
    db.products.delete_one({'_id': ObjectId(id)})
    return jsonify({'message': 'Product deleted'}), 200
