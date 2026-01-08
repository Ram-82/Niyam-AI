import json
import os
from typing import Dict, List, Optional
import logging

logger = logging.getLogger(__name__)

class MockDB:
    def __init__(self, data_dir: str = "data"):
        self.data_dir = data_dir
        if not os.path.exists(data_dir):
            os.makedirs(data_dir)
            
        self.users_file = os.path.join(data_dir, "users.json")
        self.businesses_file = os.path.join(data_dir, "businesses.json")
        
        self._ensure_file(self.users_file)
        self._ensure_file(self.businesses_file)

    def _ensure_file(self, filepath: str):
        if not os.path.exists(filepath):
            with open(filepath, 'w') as f:
                json.dump([], f)

    def _read_file(self, filepath: str) -> List[Dict]:
        try:
            with open(filepath, 'r') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Error reading {filepath}: {e}")
            return []

    def _write_file(self, filepath: str, data: List[Dict]):
        try:
            with open(filepath, 'w') as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.error(f"Error writing {filepath}: {e}")

    # User operations
    def get_user_by_email(self, email: str) -> Optional[Dict]:
        users = self._read_file(self.users_file)
        for user in users:
            if user.get("email") == email:
                return user
        return None

    def get_user_by_id(self, user_id: str) -> Optional[Dict]:
        users = self._read_file(self.users_file)
        for user in users:
            if user.get("id") == user_id:
                return user
        return None

    def create_user(self, user_data: Dict) -> Dict:
        users = self._read_file(self.users_file)
        users.append(user_data)
        self._write_file(self.users_file, users)
        return user_data
        
    def update_user_last_login(self, user_id: str, timestamp: str):
        users = self._read_file(self.users_file)
        for user in users:
            if user.get("id") == user_id:
                user["last_login"] = timestamp
                break
        self._write_file(self.users_file, users)

    # Business operations
    def create_business(self, business_data: Dict) -> Dict:
        businesses = self._read_file(self.businesses_file)
        businesses.append(business_data)
        self._write_file(self.businesses_file, businesses)
        return business_data

    def get_business_by_id(self, business_id: str) -> Optional[Dict]:
        businesses = self._read_file(self.businesses_file)
        for business in businesses:
            if business.get("id") == business_id:
                return business
        return None
