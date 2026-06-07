import os
from functools import wraps
from flask import request, jsonify
import jwt
from config import Config
from extensions import get_db

def token_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        token = None
        auth_header = request.headers.get('Authorization')
        if auth_header and auth_header.startswith('Bearer '):
            token = auth_header.split(' ')[1]

        if not token:
            return jsonify({'message': 'Token is missing!'}), 401

        try:
            data = jwt.decode(token, Config.JWT_SECRET, algorithms=['HS256'])
            db = get_db()
            
            # If admin token is used on a normal route, allow it
            if data.get('role') == 'admin':
                current_user = {'role': 'admin', 'user_id': 'admin'}
            else:
                current_user = db.users.find_one({'_id': data.get('user_id')})
                if not current_user:
                    return jsonify({'message': 'User not found!'}), 401
                current_user['_id'] = str(current_user['_id'])
                current_user['role'] = 'user'
                
        except jwt.ExpiredSignatureError:
            return jsonify({'message': 'Token has expired!'}), 401
        except jwt.InvalidTokenError:
            return jsonify({'message': 'Invalid token!'}), 401

        return f(current_user, *args, **kwargs)
    return decorated

def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        token = None
        auth_header = request.headers.get('Authorization')
        if auth_header and auth_header.startswith('Bearer '):
            token = auth_header.split(' ')[1]

        if not token:
            return jsonify({'message': 'Token is missing!'}), 401

        try:
            data = jwt.decode(token, Config.JWT_SECRET, algorithms=['HS256'])
            if data.get('role') != 'admin':
                return jsonify({'message': 'Admin access required!'}), 403
            current_admin = {'role': 'admin', 'user_id': 'admin'}
        except jwt.ExpiredSignatureError:
            return jsonify({'message': 'Token has expired!'}), 401
        except jwt.InvalidTokenError:
            return jsonify({'message': 'Invalid token!'}), 401

        return f(current_admin, *args, **kwargs)
    return decorated
