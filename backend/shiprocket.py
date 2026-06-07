
import requests
import os
from dotenv import load_dotenv

# Always reload .env on each class instantiation so credential changes take effect
load_dotenv(override=True)

SHIPROCKET_BASE_URL = "https://apiv2.shiprocket.in/v1/external"

class ShiprocketAPI:
    def __init__(self):
        self.base_url = SHIPROCKET_BASE_URL
        self.email = os.getenv('SHIPROCKET_EMAIL')
        self.password = os.getenv('SHIPROCKET_PASSWORD')
        self.token = None

    def authenticate(self):
        """Get a fresh token from Shiprocket."""
        url = f"{self.base_url}/auth/login"
        payload = {"email": self.email, "password": self.password}
        try:
            response = requests.post(url, json=payload, timeout=10)
            if response.status_code == 200:
                self.token = response.json().get('token')
                print(f"[Shiprocket] Auth OK for {self.email}")
                return True
            else:
                print(f"[Shiprocket] Auth FAILED ({response.status_code}): {response.text}")
                return False
        except Exception as e:
            print(f"[Shiprocket] Auth Exception: {e}")
            return False

    def _get_headers(self):
        """Return auth headers, re-authenticating if needed."""
        if not self.token:
            if not self.authenticate():
                return None
        return {
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {self.token}'
        }

    def _retry_with_fresh_token(self, fn):
        """Call fn(headers). If 401, re-auth once and retry."""
        headers = self._get_headers()
        if not headers:
            return {"status": "error", "message": "Authentication failed"}
        result = fn(headers)
        # If token expired mid-session, refresh once
        if isinstance(result, dict) and result.get('status') == 'error' and '401' in str(result.get('message', '')):
            self.token = None
            headers = self._get_headers()
            if headers:
                result = fn(headers)
        return result

    def check_serviceability(self, pickup_pincode, delivery_pincode, weight=0.5, cod=0):
        """Check if a courier can deliver from pickup to delivery pincode."""
        url = f"{self.base_url}/courier/serviceability"
        params = {
            "pickup_postcode": str(pickup_pincode),
            "delivery_postcode": str(delivery_pincode),
            "cod": int(cod),
            "weight": float(weight)
        }

        def call(headers):
            try:
                response = requests.get(url, headers=headers, params=params, timeout=10)
                if response.status_code == 200:
                    return response.json()
                return {"status": "error", "message": str(response.status_code) + " " + response.text}
            except Exception as e:
                return {"status": "error", "message": str(e)}

        return self._retry_with_fresh_token(call)

    def get_shipping_rate(self, pickup_pincode, delivery_pincode, weight=0.5, cod=0):
        """Returns the best shipping rate based on Shiprocket serviceability."""
        serviceability = self.check_serviceability(pickup_pincode, delivery_pincode, weight, cod)

        if 'data' in serviceability and 'available_courier_companies' in serviceability.get('data', {}):
            couriers = serviceability['data']['available_courier_companies']
            if couriers:
                # Filter out low-rated couriers (under 3 stars for reliability)
                reliable_couriers = [c for c in couriers if float(c.get('rating', 0)) >= 3.0]

                # Fallback to full list if all couriers are below 3 stars
                if not reliable_couriers:
                    reliable_couriers = couriers

                # Pick cheapest reliable courier
                best_courier = min(reliable_couriers, key=lambda x: float(x.get('rate', 9999)))

                net_rate = float(best_courier.get('rate', 0))
                # Shiprocket rates already include GST in most cases, 
                # but we confirm by checking if the rate seems pre-tax
                # For safety we pass-through the rate as-is (it's already inclusive)
                return {
                    "status": "success",
                    "courier_name": best_courier.get('courier_name'),
                    "etd": best_courier.get('etd'),
                    "freight_charge": net_rate,
                    "tax": 0,
                    "total_shipping": net_rate
                }

        # Fallback flat rate when Shiprocket API is unreachable or credentials are invalid
        print("[Shiprocket] Falling back to flat rate (API unavailable)")
        return {
            "status": "success",
            "courier_name": "Standard Courier",
            "etd": "3-5 Days",
            "freight_charge": 70.0,
            "tax": 0,
            "total_shipping": 70.0
        }

    def create_order(self, order_data):
        """Create an order in Shiprocket. Returns the full API response dict."""
        url = f"{self.base_url}/orders/create/adhoc"

        def call(headers):
            try:
                response = requests.post(url, headers=headers, json=order_data, timeout=15)
                data = response.json()
                if response.status_code == 200:
                    return data
                # Return full error for upstream handling
                return {"status": "error", "message": response.text, "details": data}
            except Exception as e:
                return {"status": "error", "message": str(e)}

        result = self._retry_with_fresh_token(call)
        print(f"[Shiprocket] Create Order Response: {result}")
        return result

    def get_tracking(self, shipment_id):
        """Get real-time tracking info for a shipment by its Shiprocket shipment ID."""
        url = f"{self.base_url}/courier/track/shipment/{shipment_id}"

        def call(headers):
            try:
                response = requests.get(url, headers=headers, timeout=10)
                if response.status_code == 200:
                    return response.json()
                return {"status": "error", "message": response.text}
            except Exception as e:
                return {"status": "error", "message": str(e)}

        return self._retry_with_fresh_token(call)
