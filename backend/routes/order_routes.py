from flask import Blueprint, request, jsonify
from extensions import get_db
from shiprocket import ShiprocketAPI
from bson import ObjectId
import datetime
import razorpay
import os
from middleware.auth_middleware import admin_required, token_required

order_bp = Blueprint('order_bp', __name__)

def get_shiprocket():
    """Always return a fresh ShiprocketAPI instance so new .env credentials are picked up."""
    return ShiprocketAPI()

# Initialize Razorpay
client = None
if os.getenv('RAZORPAY_KEY_ID') and os.getenv('RAZORPAY_KEY_SECRET'):
    client = razorpay.Client(auth=(os.getenv('RAZORPAY_KEY_ID'), os.getenv('RAZORPAY_KEY_SECRET')))

def send_sms(phone, message):
    """Order confirmation SMS — uses MSG91 if configured, else prints to console."""
    import os
    if not os.getenv('MSG91_AUTH_KEY') or 'your_' in os.getenv('MSG91_AUTH_KEY', ''):
        print(f"\n[DEV MODE] Order SMS → +91{phone}: {message}")
        return True
    
    # In production, integrate MSG91 or fast2sms logic here
    return True

@order_bp.route('/shipping-cost', methods=['POST'])
def get_shipping_cost():
    data = request.json
    pincode = data.get('pincode')
    weight = data.get('weight', 0.5)
    cod = data.get('cod', 0)
    user_id = data.get('user_id')
    device_id = data.get('device_id')
    
    if not pincode:
        return jsonify({'message': 'Pincode is required'}), 400
        
    if not is_maharashtra_pincode(pincode):
         return jsonify({'message': 'Delivery available only in Maharashtra'}), 400

    # Check if this is the user's first order
    is_first_order = False
    db = get_db()
    
    # Check by user_id
    if user_id and user_id != 'guest':
        order_count = db.orders.count_documents({
            'user_id': str(user_id),
            'order_status': {'$ne': 'Cancelled'}
        })
        if order_count < 1:
            is_first_order = True
    
    # Check by device_id (Anti-fraud)
    if not is_first_order and device_id:
        device_order_count = db.orders.count_documents({
            'device_id': str(device_id),
            'order_status': {'$ne': 'Cancelled'}
        })
        if device_order_count < 1:
            is_first_order = True
    elif is_first_order and device_id:
        # even if user is new, if device has an order, block free delivery
        device_order_count = db.orders.count_documents({
            'device_id': str(device_id),
            'order_status': {'$ne': 'Cancelled'}
        })
        if device_order_count >= 1:
            is_first_order = False

    order_total = data.get('order_total', 0)
    
    # NEW RULE: Choice 3. Free Shipping ONLY if First Order AND Cart > 1000
    if is_first_order and float(order_total) >= 1000:
        return jsonify({
            'total_shipping': 0,
            'message': 'Congratulations! Free Shipping applied for your first order over ₹1000.'
        }), 200

    # Pickup location: Shrigonda (413701)
    pickup_pincode = "413701"

    shipping_details = get_shiprocket().get_shipping_rate(pickup_pincode, pincode, weight, cod=cod)
    return jsonify(shipping_details), 200

# Maharashtra Pincode Validation
def is_maharashtra_pincode(pincode):
    try:
        pin = int(pincode)
        # Maharashtra pincodes: 400000-445999
        return 400000 <= pin <= 445999
    except:
        return False

@order_bp.route('/eligibility', methods=['POST'])
def check_eligibility():
    data = request.json
    user_id = data.get('user_id')
    device_id = data.get('device_id')
    
    db = get_db()
    
    # Strict check: Must be eligible on BOTH user and device
    user_eligible = True
    if user_id and user_id != 'guest':
        count = db.orders.count_documents({'user_id': str(user_id), 'order_status': {'$ne': 'Cancelled'}})
        if count >= 1:
            user_eligible = False
            
    device_eligible = True
    if device_id:
        count = db.orders.count_documents({'device_id': str(device_id), 'order_status': {'$ne': 'Cancelled'}})
        if count >= 1:
            device_eligible = False
            
    return jsonify({
        'eligible_for_free_delivery': user_eligible and device_eligible
    }), 200

@order_bp.route('/razorpay/create', methods=['POST'])
@token_required
def create_razorpay_order(current_user):
    """Step 1: Create a formal Razorpay Order for the payment modal."""
    if not client:
        return jsonify({'message': 'Razorpay not configured on server'}), 500
        
    try:
        data = request.json
        amount = float(data.get('amount', 0))
        if amount <= 0:
            return jsonify({'message': 'Invalid amount'}), 400
            
        # Razorpay expects amount in paise (1 INR = 100 Paise)
        razorpay_order = client.order.create({
            "amount": int(amount * 100),
            "currency": "INR",
            "payment_capture": "1" # Auto-capture
        })
        
        return jsonify(razorpay_order), 200
    except Exception as e:
        print(f"Razorpay Order Error: {e}")
        return jsonify({'message': str(e)}), 400

@order_bp.route('/', methods=['POST'])
@token_required
def create_order(current_user):
    data = request.json
    required_fields = ['user_id', 'products', 'total_price', 'address', 'city', 'pincode', 'phone', 'name']
    for field in required_fields:
        if field not in data:
            return jsonify({'message': f'Missing field: {field}'}), 400

    pincode = data['pincode']
    if not is_maharashtra_pincode(pincode):
         return jsonify({'message': 'Delivery available only in Maharashtra (Pincode 400xxx-44xxxx)'}), 400

    # Check Shiprocket Serviceability (Pickup: Shrigonda 413701)
    pickup_pincode = "413701"
    serviceability = get_shiprocket().check_serviceability(pickup_pincode, pincode)

    is_serviceable = (
        serviceability
        and 'data' in serviceability
        and len(serviceability['data'].get('available_courier_companies', [])) > 0
    )

    if not is_serviceable:
        print(f"[Order] Serviceability fallback for pincode {pincode}: {serviceability.get('status', 'unknown')}, allowing through (MH pincode validated)")

    # Promo Code Validation
    db = get_db()
    promo_code = data.get('promo_code')
    if promo_code:
        offer = db.offers.find_one({'code': promo_code.strip().upper()})
        if not offer:
            return jsonify({'message': 'Invalid promotional code.'}), 400
        
        # Check Status
        if offer.get('status') != 'active':
             return jsonify({'message': 'This promotional campaign is no longer active.'}), 400
        
        # Check Dates
        current_time = datetime.datetime.utcnow()
        try:
            s_val = offer.get('start_date')
            if s_val:
                start_date = datetime.datetime.fromisoformat(s_val.replace('Z', '+00:00')).replace(tzinfo=None) if 'T' in s_val else datetime.datetime.strptime(s_val, '%Y-%m-%d')
                if current_time < start_date:
                    return jsonify({'message': f'This code will be valid from {start_date.strftime("%d %b %Y")}.'}), 400
            
            e_val = offer.get('end_date')
            if e_val:
                end_date = datetime.datetime.fromisoformat(e_val.replace('Z', '+00:00')).replace(tzinfo=None) if 'T' in e_val else datetime.datetime.strptime(e_val, '%Y-%m-%d').replace(hour=23, minute=59, second=59)
                if current_time > end_date:
                    return jsonify({'message': 'This promotional code has expired.'}), 400
        except:
            pass # Fallback to status check if date parsing fails

        # Check Usage Limit
        usage_limit = offer.get('usage_limit')
        if usage_limit is not None and str(usage_limit).strip() != '':
            try:
                usage_limit = int(usage_limit)
                used_count = db.orders.count_documents({
                    'promo_code': offer.get('code'),
                    'order_status': {'$nin': ['Cancelled', 'Declined']}
                })
                if used_count >= usage_limit:
                    return jsonify({'message': 'This promotional code is sold out (usage limit reached).'}), 400
            except:
                pass

    # Stock Check & Update
    db = get_db()
    products_to_update = []
    
    for item in data['products']:
        p_id = item.get('product_id')
        qty = item.get('quantity', 1)
        
        product = db.products.find_one({'_id': ObjectId(p_id)})
        if not product:
            return jsonify({'message': f'Product {p_id} not found'}), 404
            
        current_stock = int(product.get('stock', 0))
        if current_stock < qty:
            return jsonify({'message': f'Insufficient stock for {product.get("name")}. Only {current_stock} available.'}), 400
            
        products_to_update.append((p_id, qty))

    # All products have enough stock, now decrement
    for p_id, qty in products_to_update:
        dec_qty = int(qty) * -1
        db.products.update_one(
            {'_id': ObjectId(p_id)},
            {'$inc': {'stock': dec_qty}}
        )

    # Create Order in MongoDB
    order = {
        "user_id": data['user_id'], # Store as string
        "products": data['products'],
        "total_price": data['total_price'],
        "address": data['address'],
        "city": data['city'],
        "pincode": pincode,
        "phone": data['phone'],
        "name": data['name'],
        "device_id": data.get('device_id', ''),
        "order_status": "Placed",
        "payment_status": data.get('payment_status', 'Pending'),
        "payment_method": data.get('payment_method', 'COD'),
        "razorpay_payment_id": data.get('razorpay_payment_id', ''),
        "razorpay_order_id": data.get('razorpay_order_id', ''),
        "razorpay_signature": data.get('razorpay_signature', ''),
        "created_at": datetime.datetime.utcnow(),
        "promo_code": data.get('promo_code', ''),
        "tracking_id": "PENDING"
    }   
    
    order_id = db.orders.insert_one(order).inserted_id
    tracking_id = "PENDING"

    # Send Order Confirmation SMS
    try:
        order_short_id = str(order_id)[-6:].upper()
        total_amount = data['total_price']
        sms_message = (
            f"Gavran Magic Order Confirmed! 🎉\n"
            f"Order ID: #{order_short_id}\n"
            f"Amount: ₹{total_amount}\n"
            f"Status: Placed\n"
            f"Thank you for ordering! Track your order at our website."
        )
        send_sms(data['phone'], sms_message)
    except Exception as sms_err:
        print(f"SMS Error: {sms_err}")

    return jsonify({'message': 'Order placed successfully', 'order_id': str(order_id), 'tracking_id': tracking_id}), 201

@order_bp.route('/<order_id>', methods=['GET'])
@token_required
def get_order(current_user, order_id):
    try:
        order = get_db().orders.find_one({'_id': ObjectId(order_id)})
        if order:
            order['_id'] = str(order['_id'])
            order['user_id'] = str(order['user_id'])
            return jsonify(order), 200
        return jsonify({'message': 'Order not found'}), 404
    except Exception:
        return jsonify({'message': 'Invalid Order ID format'}), 400
    
@order_bp.route('/<order_id>/cancel', methods=['POST'])
@token_required
def cancel_order(current_user, order_id):
    try:
        data = request.json
        cancellation_reason = data.get('reason', 'Not specified')
        
        order = get_db().orders.find_one({'_id': ObjectId(order_id)})
        if not order:
             return jsonify({'message': 'Order not found'}), 404
             
        if order['order_status'] in ['Delivered', 'Cancelled']:
             return jsonify({'message': f'Order cannot be cancelled. Current status: {order["order_status"]}'}), 400
             
        # Check grace period from settings
        db = get_db()
        settings = db.settings.find_one({"type": "global"})
        grace_hours = settings.get('refund_hour_grace_period', 24) if settings else 24
        
        created_at = order.get('created_at')
        if created_at:
            if isinstance(created_at, str):
                created_at = datetime.datetime.fromisoformat(created_at.replace('Z', '+00:00'))
            
            # Ensure created_at is naive if comparing with utcnow() or both are aware
            if created_at.tzinfo is not None:
                now = datetime.datetime.now(datetime.timezone.utc)
            else:
                now = datetime.datetime.utcnow()
                
            time_diff = now - created_at
            hours_passed = time_diff.total_seconds() / 3600
            
            if hours_passed > grace_hours:
                return jsonify({'message': f'Order cancellation window ({grace_hours} hours) has expired.'}), 400
             
        get_db().orders.update_one(
            {'_id': ObjectId(order_id)},
            {'$set': {
                'order_status': 'Cancellation Requested',
                'cancellation_reason': cancellation_reason,
                'cancellation_requested_at': datetime.datetime.utcnow()
            }}
        )
        
        return jsonify({'message': 'Cancellation request submitted for approval'}), 200
    except Exception as e:
        print(f"Error cancelling order: {e}")
        return jsonify({'message': 'Failed to cancel order'}), 500

@order_bp.route('/user/<user_id>', methods=['GET'])
@token_required
def get_user_orders(current_user, user_id):
    if current_user['role'] != 'admin' and current_user['user_id'] != user_id:
        return jsonify({'message': 'Unauthorized'}), 403
    orders_cursor = get_db().orders.find({'user_id': user_id}).sort('created_at', -1)
    orders = []
    for order in orders_cursor:
        order['_id'] = str(order['_id'])
        orders.append(order)
    return jsonify(orders), 200

# ADMIN: Push order to Shiprocket
@order_bp.route('/<order_id>/ship', methods=['POST'])
@admin_required
def ship_order(current_admin, order_id):
    try:
        db = get_db()
        order = db.orders.find_one({'_id': ObjectId(order_id)})
        if not order:
            return jsonify({'message': 'Order not found'}), 404
            
        data = request.json if request.is_json else {}
        pickup_location = data.get('pickup_location', 'warehouse')
        weight = float(data.get('weight', 0.5))
        length = float(data.get('length', 10))
        breadth = float(data.get('breadth', 10))
        height = float(data.get('height', 10))

        # Prepare Shiprocket Order Payload
        sr_order_items = []
        for item in order['products']:
            sr_order_items.append({
                "name": item.get('name', 'GAVRAN Product'),
                "sku": str(item.get('product_id', 'sku')),
                "units": item.get('quantity', 1),
                "selling_price": item.get('price', 0),
                "discount": "",
                "tax": "",
                "hsn": ""
            })
            
        full_name = str(order.get('name', 'Customer'))
        name_parts = full_name.strip().split(' ', 1)
        first_name = name_parts[0] if name_parts else 'Customer'
        last_name = name_parts[1] if len(name_parts) > 1 else 'Customer'

        # Map payment method to Shiprocket accepted values
        payment_method_map = {'COD': 'COD', 'Prepaid': 'Prepaid', 'Online': 'Prepaid'}
        payment_method = payment_method_map.get(order.get('payment_method', 'COD'), 'COD')

        sr_order_payload = {
            "order_id": str(order['_id']),
            "order_date": order['created_at'].strftime("%Y-%m-%d %H:%M"),
            "pickup_location": pickup_location,
            "billing_customer_name": first_name,
            "billing_last_name": last_name,
            "billing_address": order['address'],
            "billing_city": order['city'],
            "billing_pincode": str(order['pincode']),
            "billing_state": "Maharashtra",
            "billing_country": "India",
            "billing_email": order.get('email', 'customer@gavranmagic.com'),
            "billing_phone": str(order['phone']),
            "shipping_is_billing": True,
            "order_items": sr_order_items,
            "payment_method": payment_method,
            "sub_total": float(order['total_price']),
            "length": length,
            "breadth": breadth,
            "height": height,
            "weight": weight
        }

        sr_response = get_shiprocket().create_order(sr_order_payload)

        # Shiprocket returns status_code=1 on success
        if sr_response and sr_response.get('status_code') == 1:
            sr_order_id = sr_response.get('order_id', '')
            shipment_id = sr_response.get('shipment_id', '')

            db.orders.update_one(
                {'_id': ObjectId(order_id)},
                {'$set': {
                    'order_status': 'Shipped',
                    'tracking_id': str(sr_order_id),
                    'shipment_id': str(shipment_id)
                }}
            )
            return jsonify({
                'message': 'Successfully pushed to Shiprocket! 🚀',
                'shiprocket_order_id': sr_order_id,
                'shiprocket_shipment_id': shipment_id
            }), 200
        else:
            # Log full response for debugging
            error_msg = sr_response.get('message', 'Unknown error from Shiprocket')
            print(f"[Shiprocket] Order push FAILED: {sr_response}")
            return jsonify({'message': error_msg, 'details': sr_response}), 400
            
    except Exception as e:
        print(f"Shiprocket Error: {e}")
        return jsonify({'message': str(e)}), 500

# ADMIN: Get all orders
@order_bp.route('/', methods=['GET'])
@admin_required
def get_all_orders(current_admin):
    # In production, check for admin token
    orders_cursor = get_db().orders.find().sort('created_at', -1)
    orders = []
    for order in orders_cursor:
        order['_id'] = str(order['_id'])
        orders.append(order)
    return jsonify(orders), 200

# ADMIN: Update order status & metadata
@order_bp.route('/<order_id>/status', methods=['PUT'])
@admin_required
def update_order_status(current_admin, order_id):
    try:
        data = request.json
        new_status = data.get('status')
        reason = data.get('reason')
        admin_note = data.get('admin_note')

        if not new_status:
            return jsonify({'message': 'Status is required'}), 400
            
        update_data = {'order_status': new_status}
        if reason:
            update_data['cancellation_reason'] = reason
        if admin_note:
            update_data['admin_note'] = admin_note
        # If status is changing to Cancelled or Declined, return stock!
        if new_status in ['Cancelled', 'Declined']:
            update_data['cancelled_at'] = datetime.datetime.utcnow()
            
            # Fetch order to get products
            order = get_db().orders.find_one({'_id': ObjectId(order_id)})
            if order and order.get('order_status') not in ['Cancelled', 'Declined']:
                # Return items to stock
                for item in order.get('products', []):
                    p_id = item.get('product_id')
                    qty = item.get('quantity', 0)
                    if p_id and qty > 0:
                        get_db().products.update_one(
                            {'_id': ObjectId(p_id)},
                            {'$inc': {'stock': int(qty)}}
                        )

        result = get_db().orders.update_one(
            {'_id': ObjectId(order_id)},
            {'$set': update_data}
        )
        
        if result.matched_count == 0:
            return jsonify({'message': 'Order not found'}), 404
            
        return jsonify({'message': 'Order status updated successfully'}), 200
    except Exception as e:
        return jsonify({'message': str(e)}), 400

# ADMIN: Delete an order
@order_bp.route('/<order_id>', methods=['DELETE'])
@admin_required
def delete_order(current_admin, order_id):
    try:
        db = get_db()
        result = db.orders.delete_one({'_id': ObjectId(order_id)})
        
        if result.deleted_count == 0:
            return jsonify({'message': 'Order not found'}), 404
            
        return jsonify({'message': 'Order deleted successfully'}), 200
    except Exception as e:
        return jsonify({'message': str(e)}), 400

# ADMIN: Get business analytics
@order_bp.route('/analytics/report', methods=['GET'])
@admin_required
def get_analytics(current_admin):
    try:
        db = get_db()
        # 1. Daily Sales for last 7 days
        today = datetime.datetime.utcnow().replace(hour=23, minute=59, second=59)
        last_7_days = []
        for i in range(6, -1, -1):
            day = today - datetime.timedelta(days=i)
            day_start = day.replace(hour=0, minute=0, second=0, microsecond=0)
            day_end = day.replace(hour=23, minute=59, second=59, microsecond=999)
            
            orders = list(db.orders.find({
                'created_at': {'$gte': day_start, '$lte': day_end},
                'order_status': {'$nin': ['Cancelled', 'Declined']}
            }))
            
            revenue = sum(float(o.get('total_price', 0)) for o in orders)
            last_7_days.append({
                'name': day.strftime('%a'),
                'revenue': round(float(revenue), 2),
                'orders': len(orders)
            })

        # 2. Sales by Category (All time)
        category_stats = {}
        all_orders = list(db.orders.find({'order_status': {'$nin': ['Cancelled', 'Declined']}}))
        
        for order in all_orders:
            for item in order.get('products', []):
                # Try to get category from orders product ref or fetch from products coll
                # For efficiency we use a small cache or just use the category field if it was stored in the order
                cat = item.get('category', 'Others')
                val = float(item.get('price', 0)) * float(item.get('quantity', 1))
                if cat in category_stats:
                    category_stats[cat] += val
                else:
                    category_stats[cat] = val
        
        category_data = [
            {'name': k, 'value': int(round(v))} for k, v in category_stats.items()
        ]
        
        # 3. Overall Metrics
        total_revenue = sum(float(o.get('total_price', 0)) for o in all_orders)
        avg_order_value = total_revenue / len(all_orders) if all_orders else 0
        
        # Calculate Repeat Customer Rate
        user_order_counts = {}
        for o in all_orders:
            uid = str(o.get('user_id'))
            user_order_counts[uid] = user_order_counts.get(uid, 0) + 1
            
        repeat_customers = [uid for uid, count in user_order_counts.items() if count > 1]
        repeat_rate = (len(repeat_customers) / len(user_order_counts) * 100) if user_order_counts else 0

        return jsonify({
            'dailyData': last_7_days,
            'categoryData': category_data,
            'metrics': {
                'totalRevenue': round(total_revenue, 2),
                'avgOrderValue': round(avg_order_value, 2),
                'orderCount': len(all_orders),
                'repeatRate': round(repeat_rate, 1)
            }
        }), 200
        
    except Exception as e:
        print(f"Analytics Error: {e}")
        return jsonify({'message': str(e)}), 400
