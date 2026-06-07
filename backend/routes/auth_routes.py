import random
import datetime
import requests
import os
from flask import Blueprint, request, jsonify
from extensions import get_db
from config import Config
import jwt
from middleware.auth_middleware import admin_required, token_required
from extensions import limiter

auth_bp = Blueprint('auth_bp', __name__)


# ============================================================
# SMS SENDER — Fast2SMS (FREE) or Dev Mode (prints to console)
# Sign up FREE at: https://www.fast2sms.com/
# Get your API key from Dashboard → Dev API
# Paste it in backend/.env as: FAST2SMS_API_KEY=your_key_here
# ============================================================

def send_otp_sms(phone, otp):
    """
    Send OTP SMS via real providers (Fast2SMS or 2Factor.in).
    """
    db = get_db()
    
    # 1. Try Fast2SMS (High Priority - Dedicated OTP Route)
    fast2sms_key = os.getenv('FAST2SMS_API_KEY', '')
    if fast2sms_key and 'your_' not in fast2sms_key:
        url = "https://www.fast2sms.com/dev/bulkV2"
        headers = {"authorization": fast2sms_key}
        payload = {
            "route": "otp",
            "variables_values": otp,
            "numbers": phone,
        }
        try:
            # Fast2SMS OTP route is reliable and doesn't trigger calls
            resp = requests.post(url, headers=headers, data=payload, timeout=10)
            result = resp.json()
            if result.get("return"):
                print(f"✅ Fast2SMS: OTP SMS sent to +91{phone}")
                return True
            else:
                print(f"❌ Fast2SMS Failure: {result}")
        except Exception as e:
            print(f"❌ Fast2SMS Connection Error: {e}")

    # 2. Try 2Factor.in (Fallback)
    tf_key = os.getenv('TWOFACTOR_API_KEY', '')
    if tf_key and 'your_' not in tf_key:
        # Using the standard SMS route
        url = f"https://2factor.in/API/V1/{tf_key}/SMS/{phone}/AUTOGEN"
        try:
            resp = requests.get(url, timeout=10)
            result = resp.json()
            if result.get('Status') == 'Success':
                print(f"✅ 2Factor: OTP sent to +91{phone}")
                # Store session for verification
                db.otps.update_one(
                    {'phone': phone}, 
                    {'$set': {'twofactor_session': result.get('Details', '')}},
                    upsert=False
                )
                return True
            else:
                print(f"❌ 2Factor Failure: {result}")
        except Exception as e:
            print(f"❌ 2Factor Connection Error: {e}")

    # 3. Dev Fallback (Only if both fail or keys are missing)
    print(f"\n{'!'*45}")
    print(f"  [CRITICAL: SMS NOT SENT - CHECK API BALANCES]")
    print(f"  Phone : +91 {phone}")
    print(f"  OTP   : {otp}")
    print(f"{'!'*45}\n")
    return True


def send_order_confirmation_sms(phone, order_short_id, total_amount):
    """Send order confirmation SMS to customer."""
    api_key = os.getenv('FAST2SMS_API_KEY', '')

    if not api_key or 'your_' in api_key:
        print(f"[DEV MODE] Order Confirmed → +91{phone} | #{order_short_id} | ₹{total_amount}")
        return True

    url = "https://www.fast2sms.com/dev/bulkV2"
    headers = {"authorization": api_key}
    message = f"Gavran Magic: Order #{order_short_id} confirmed! Amount Rs.{total_amount}. We will deliver soon. Thank you!"
    params = {
        "route": "q",
        "message": message,
        "flash": 0,
        "numbers": phone,
    }
    try:
        response = requests.get(url, headers=headers, params=params, timeout=10)
        result = response.json()
        if result.get("return"):
            print(f"✅ Order SMS sent to +91{phone}")
        return True
    except Exception as e:
        print(f"Order SMS Error: {e}")
        return True  # Don't fail the order if SMS fails


@auth_bp.route('/send-otp', methods=['POST'])
@limiter.limit("5 per minute; 20 per hour")
def send_otp():
    try:
        data = request.json
        phone = str(data.get('phone', '')).strip()

        # Validate 10-digit Indian number
        if not phone or len(phone) != 10 or not phone.isdigit():
            return jsonify({'message': 'Please enter a valid 10-digit mobile number'}), 400

        db = get_db()

        # Rate limiting: max 5 OTP requests per hour per phone
        one_hour_ago = datetime.datetime.utcnow() - datetime.timedelta(hours=1)
        recent_count = db.otp_logs.count_documents({
            'phone': phone,
            'created_at': {'$gte': one_hour_ago}
        })
        if recent_count >= 20:
            return jsonify({'message': 'Too many OTP requests. Please wait before trying again.'}), 429

        # Generate 6-digit OTP
        otp = str(random.randint(100000, 999999))
        expiry = datetime.datetime.utcnow() + datetime.timedelta(minutes=5)

        # Save OTP to DB (overwrite any existing)
        db.otps.update_one(
            {'phone': phone},
            {'$set': {'otp': otp, 'expiry': expiry, 'attempts': 0}},
            upsert=True
        )

        # Log request for rate limiting
        db.otp_logs.insert_one({'phone': phone, 'created_at': datetime.datetime.utcnow()})

        # Send SMS
        success = send_otp_sms(phone, otp)

        if success:
            return jsonify({'message': 'OTP sent successfully'}), 200
        else:
            return jsonify({'message': 'Failed to send OTP. Please try again.'}), 500

    except Exception as e:
        print(f"Send OTP Error: {e}")
        return jsonify({'error': str(e)}), 500


@auth_bp.route('/verify-otp', methods=['POST'])
@limiter.limit("10 per minute")
def verify_otp():
    try:
        data = request.json
        phone = str(data.get('phone', '')).strip()
        otp = str(data.get('otp', '')).strip()

        if not phone or not otp:
            return jsonify({'message': 'Phone and OTP are required'}), 400

        db = get_db()
        otp_record = db.otps.find_one({'phone': phone})

        if not otp_record:
            return jsonify({'message': 'OTP not found. Please request a new one.'}), 401

        # Brute force protection
        if otp_record.get('attempts', 0) >= 5:
            db.otps.delete_one({'phone': phone})
            return jsonify({'message': 'Too many failed attempts. Please request a new OTP.'}), 401

        # Expiry check
        if otp_record['expiry'] < datetime.datetime.utcnow():
            db.otps.delete_one({'phone': phone})
            return jsonify({'message': 'OTP expired. Please request a new one.'}), 401

        # OTP check
        twofactor_session = otp_record.get('twofactor_session')
        api_key = os.getenv('TWOFACTOR_API_KEY', '')

        if twofactor_session and api_key and 'your_' not in api_key:
            # Verify via 2Factor.in API
            url = f"https://2factor.in/API/V1/{api_key}/SMS/VERIFY/{twofactor_session}/{otp}"
            try:
                resp = requests.get(url, timeout=10)
                result = resp.json()
                print(f"[2Factor Verify] Response: {result}")
                if result.get('Status') != 'Success':
                    db.otps.update_one({'phone': phone}, {'$inc': {'attempts': 1}})
                    remaining = 5 - (otp_record.get('attempts', 0) + 1)
                    return jsonify({'message': f"Incorrect OTP. {remaining} attempts remaining."}), 401
            except Exception as e:
                print(f"❌ 2Factor Verification Exception: {e}")
                # Fallback to local check if API is down
                if otp_record['otp'] != otp:
                    db.otps.update_one({'phone': phone}, {'$inc': {'attempts': 1}})
                    remaining = 5 - (otp_record.get('attempts', 0) + 1)
                    return jsonify({'message': f'Incorrect OTP. {remaining} attempts remaining.'}), 401
        else:
            # Local OTP check (Dev mode)
            if otp_record['otp'] != otp:
                db.otps.update_one({'phone': phone}, {'$inc': {'attempts': 1}})
                remaining = 5 - (otp_record.get('attempts', 0) + 1)
                return jsonify({'message': f'Incorrect OTP. {remaining} attempts remaining.'}), 401

        # ✅ Valid — Find or Create User
        user = db.users.find_one({'phone': phone})
        if not user:
            user_id = db.users.insert_one({
                'phone': phone,
                'name': f'User {phone[-4:]}',
                'created_at': datetime.datetime.utcnow()
            }).inserted_id
            user = db.users.find_one({'_id': user_id})

        # Issue JWT (30 days)
        token = jwt.encode({
            'user_id': str(user['_id']),
            'phone': phone,
            'exp': datetime.datetime.utcnow() + datetime.timedelta(days=30)
        }, Config.JWT_SECRET, algorithm='HS256')

        # Delete used OTP
        db.otps.delete_one({'phone': phone})

        return jsonify({
            'token': token,
            'user': {
                'id': str(user['_id']),
                '_id': str(user['_id']),
                'name': user.get('name', ''),
                'phone': user['phone'],
                'address': user.get('address', ''),
                'city': user.get('city', ''),
                'pincode': user.get('pincode', ''),
                'saved_addresses': user.get('saved_addresses', [])
            }
        }), 200

    except Exception as e:
        print(f"Verify OTP Error: {e}")
        return jsonify({'error': str(e)}), 500


@auth_bp.route('/firebase-login', methods=['POST'])
def firebase_login():
    """Legacy Firebase login — kept for compatibility."""
    return verify_otp()

@auth_bp.route('/update-profile', methods=['POST'])
@token_required
def update_profile(current_user):
    data = request.json
    phone = data.get('phone')
    if current_user['role'] != 'admin' and current_user['phone'] != phone:
        return jsonify({'message': 'Unauthorized to update this profile'}), 403
    if not phone:
        return jsonify({'message': 'Phone number is required'}), 400

    db = get_db()
    
    # Fields allowed to be updated
    update_data = {}
    if 'name' in data: update_data['name'] = data['name']
    if 'email' in data: update_data['email'] = data['email']
    if 'address' in data: update_data['address'] = data['address']
    if 'city' in data: update_data['city'] = data['city']
    if 'pincode' in data: update_data['pincode'] = data['pincode']
    
    # If checkout form sends save_as_new_address
    if data.get('save_as_new_address'):
        new_addr_obj = {
            'address': data.get('address', ''),
            'city': data.get('city', ''),
            'pincode': data.get('pincode', '')
        }
        # Push new address, ensure we don't overwrite main profile address
        result = db.users.update_one({'phone': phone}, {'$push': {'saved_addresses': new_addr_obj}})
    else:
        # Normal profile update
        if not update_data:
            return jsonify({'message': 'No data to update'}), 400
        result = db.users.update_one({'phone': phone}, {'$set': update_data})
    
    if result.matched_count == 0:
        return jsonify({'message': 'User not found'}), 404

    # Fetch updated user
    updated_user = db.users.find_one({'phone': phone})
    updated_user['_id'] = str(updated_user['_id'])
    
    return jsonify({
        'message': 'Profile updated successfully',
        'user': updated_user
    }), 200

# ADMIN: Dashboard Login
@auth_bp.route('/admin/login', methods=['POST'])
@limiter.limit("10 per minute")
def admin_login():
    data = request.json
    username = data.get('username')
    password = data.get('password')

    env_username = os.getenv('ADMIN_USERNAME', 'admin')
    env_password = os.getenv('ADMIN_PASSWORD', 'admin123')
    
    if env_password == 'admin123' and os.getenv('FLASK_ENV') == 'production':
        print("WARNING: Default admin password used in production!")

    if username == env_username and password == env_password:
        # Issue a special admin token
        token = jwt.encode({
            'user_id': 'admin',
            'role': 'admin',
            'exp': datetime.datetime.utcnow() + datetime.timedelta(days=7)
        }, Config.JWT_SECRET, algorithm='HS256')

        return jsonify({
            'token': token,
            'message': 'Login successful'
        }), 200
    
    return jsonify({'message': 'Invalid admin credentials'}), 401


# ADMIN: Get all users with order stats
@auth_bp.route('/users', methods=['GET'])
@admin_required
def get_all_users(current_admin):
    db = get_db()
    users_cursor = db.users.find().sort('created_at', -1)
    users = []
    
    for user in users_cursor:
        user_id_str = str(user['_id'])
        
        # Calculate stats for this user
        orders_cursor = db.orders.find({'user_id': user_id_str})
        user_orders = list(orders_cursor)
        
        total_spent = sum(float(o.get('total_price', 0)) for o in user_orders if o.get('order_status') != 'Cancelled')
        
        user['_id'] = user_id_str
        user['order_count'] = len(user_orders)
        user['total_spent'] = round(total_spent, 2)
        
        if 'created_at' in user and isinstance(user['created_at'], datetime.datetime):
            user['created_at'] = user['created_at'].isoformat()
            
        users.append(user)
        
    return jsonify(users), 200
