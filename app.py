# app.py - Complete Secure Parallel Micro Buy Bot (Railway Ready)
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, BackgroundTasks, HTTPException, Depends, Header, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel
from typing import Dict, List, Optional
import asyncio
import logging
import time
import uuid
import os
import requests
from datetime import datetime
import json
from web3 import Web3
from web3.contract import Contract
from eth_account import Account
from eth_account.signers.local import LocalAccount
from dataclasses import dataclass
import hashlib
import secrets
import io
import base64
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
import psutil

# ==================== RAILWAY CONFIGURATION ====================
# Get PORT from environment (Railway sets this automatically)
PORT = int(os.environ.get("PORT", 8000))

# Data directory for persistent storage (Railway volume)
DATA_DIR = os.environ.get("DATA_DIR", ".")

# Ensure data directory exists
os.makedirs(DATA_DIR, exist_ok=True)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(os.path.join(DATA_DIR, 'parallel_micro_buy.log'))
    ]
)
logger = logging.getLogger(__name__)

# ==================== ETH PRICE SERVICE ====================
class ETHPriceService:
    _price_cache = None
    _cache_time = 0
    _cache_ttl = 300  # 5 minutes
    
    @classmethod
    def get_eth_price_usd(cls) -> float:
        current_time = time.time()
        
        # Return cached price if still valid
        if cls._price_cache and current_time - cls._cache_time < cls._cache_ttl:
            logger.debug(f"Using cached ETH price: ${cls._price_cache:.2f}")
            return cls._price_cache
        
        # Fetch new price
        logger.info("Fetching new ETH price from APIs...")
        price_sources = [
            {
                'url': 'https://api.coinbase.com/v2/prices/ETH-USD/spot',
                'extract': lambda data: float(data['data']['amount'])
            },
            {
                'url': 'https://api.binance.com/api/v3/ticker/price?symbol=ETHUSDT',
                'extract': lambda data: float(data['price'])
            }
        ]
        
        for source in price_sources:
            try:
                response = requests.get(source['url'], timeout=5)
                response.raise_for_status()
                data = response.json()
                price = source['extract'](data)
                
                if price and price > 0:
                    logger.info(f"ETH price fetched: ${price:.2f} from {source['url'].split('/')[2]}")
                    cls._price_cache = float(price)
                    cls._cache_time = current_time
                    return cls._price_cache
                    
            except Exception as e:
                logger.warning(f"Failed to fetch ETH price from {source['url']}: {e}")
                continue
        
        # Fallback
        if cls._price_cache:
            logger.warning(f"Using expired cached ETH price: ${cls._price_cache:.2f}")
            return cls._price_cache
        else:
            logger.warning("Using fallback ETH price: $3000")
            cls._price_cache = 3000.0
            cls._cache_time = current_time
            return cls._price_cache

# ==================== BOT CONFIGURATION CLASSES ====================
@dataclass
class BotConfig:
    """Configuration for the Parallel Micro Buy Bot"""
    rpc_url: str
    master_private_key: str

@dataclass
class MicroBuyConfig:
    """Configuration for micro buy operations"""
    token_address: str
    speed: str = "medium"
    num_cycles: int = 10

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup - create background task
    asyncio.create_task(cleanup_completed_operations())
    yield
    # Shutdown - cleanup if needed

# Initialize FastAPI
app = FastAPI(title="Parallel Micro Buy Bot API", lifespan=lifespan)

# ==================== PYDANTIC MODELS ====================
class UserCreate(BaseModel):
    username: str
    password: str
    role: str = "user"

class UserLogin(BaseModel):
    username: str
    password: str

class ChangePassword(BaseModel):
    old_password: str
    new_password: str

class SecureBotSettings(BaseModel):
    pk: str
    node: str = ""
    token_ca: str = ""
    speed: str = "medium"
    num_cycles: int = 10
    buy_amount_wei: int = 10
    password: str

class OperationRequest(BaseModel):
    token_address: str
    speed: str = "medium"
    num_cycles: int = 10

class SystemStats(BaseModel):
    total_users: int
    active_users: int
    total_operations: int
    active_operations: int
    completed_operations: int
    failed_operations: int
    system_uptime: float
    memory_usage: float
    cpu_usage: float

# ==================== SECURE KEY MANAGER ====================
class SecureKeyManager:
    def __init__(self):
        self.keys_file = os.path.join(DATA_DIR, "encrypted_keys.json")
        self.salt_file = os.path.join(DATA_DIR, "encryption_salt.key")
        self._ensure_encryption_keys()
    
    def _ensure_encryption_keys(self):
        if not os.path.exists(self.salt_file):
            salt = os.urandom(32)
            with open(self.salt_file, 'wb') as f:
                f.write(salt)
    
    def _get_fernet_key(self, password: str):
        import cryptography.fernet as fernet
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
        
        with open(self.salt_file, 'rb') as f:
            salt = f.read()
        
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=100000,
        )
        key = base64.urlsafe_b64encode(kdf.derive(password.encode()))
        return fernet.Fernet(key)
    
    def encrypt_private_key(self, private_key: str, password: str) -> str:
        fernet = self._get_fernet_key(password)
        encrypted_key = fernet.encrypt(private_key.encode())
        return base64.urlsafe_b64encode(encrypted_key).decode()
    
    def decrypt_private_key(self, encrypted_key: str, password: str) -> Optional[str]:
        try:
            fernet = self._get_fernet_key(password)
            encrypted_data = base64.urlsafe_b64decode(encrypted_key.encode())
            decrypted_key = fernet.decrypt(encrypted_data)
            return decrypted_key.decode()
        except Exception as e:
            logger.error(f"Failed to decrypt private key: {e}")
            return None
    
    def save_encrypted_key(self, username: str, encrypted_key: str):
        try:
            if os.path.exists(self.keys_file):
                with open(self.keys_file, 'r') as f:
                    keys_data = json.load(f)
            else:
                keys_data = {}
            
            keys_data[username] = encrypted_key
            
            with open(self.keys_file, 'w') as f:
                json.dump(keys_data, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save encrypted key: {e}")
    
    def get_encrypted_key(self, username: str) -> Optional[str]:
        try:
            if os.path.exists(self.keys_file):
                with open(self.keys_file, 'r') as f:
                    keys_data = json.load(f)
                return keys_data.get(username)
            return None
        except Exception as e:
            logger.error(f"Failed to get encrypted key: {e}")
            return None
    
    def delete_encrypted_key(self, username: str):
        try:
            if os.path.exists(self.keys_file):
                with open(self.keys_file, 'r') as f:
                    keys_data = json.load(f)
                
                if username in keys_data:
                    del keys_data[username]
                    with open(self.keys_file, 'w') as f:
                        json.dump(keys_data, f, indent=2)
                    return True
            return False
        except Exception as e:
            logger.error(f"Failed to delete encrypted key: {e}")
            return False

# ==================== USER MANAGER ====================
class SecureUserManager:
    def __init__(self):
        self.users_file = os.path.join(DATA_DIR, "users.json")
        self.sessions_file = os.path.join(DATA_DIR, "sessions.json")
        self.user_logs_file = os.path.join(DATA_DIR, "user_logs.json")
        self.key_manager = SecureKeyManager()
        self.load_users()
        self.load_sessions()
        self.load_user_logs()
    
    def load_users(self):
        try:
            if os.path.exists(self.users_file):
                with open(self.users_file, 'r') as f:
                    self.users = json.load(f)
            else:
                self.users = {
                    "admin": {
                        "password": self.hash_password("admin123"),
                        "role": "admin",
                        "created_at": datetime.now().isoformat(),
                        "is_active": True,
                        "settings": {
                            "node": "",
                            "pk": "",
                            "token_ca": "",
                            "speed": "medium",
                            "num_cycles": 10,
                            "buy_amount_wei": 10
                        }
                    }
                }
                self.save_users()
                logger.info("Default admin user created: admin/admin123")
        except Exception as e:
            logger.error(f"Error loading users: {e}")
            self.users = {}
    
    def load_sessions(self):
        try:
            if os.path.exists(self.sessions_file):
                with open(self.sessions_file, 'r') as f:
                    self.sessions = json.load(f)
            else:
                self.sessions = {}
        except Exception as e:
            logger.error(f"Error loading sessions: {e}")
            self.sessions = {}
    
    def load_user_logs(self):
        try:
            if os.path.exists(self.user_logs_file):
                with open(self.user_logs_file, 'r') as f:
                    self.user_logs = json.load(f)
            else:
                self.user_logs = {}
        except Exception as e:
            logger.error(f"Error loading user logs: {e}")
            self.user_logs = {}
    
    def save_users(self):
        try:
            with open(self.users_file, 'w') as f:
                json.dump(self.users, f, indent=2)
        except Exception as e:
            logger.error(f"Error saving users: {e}")
    
    def save_sessions(self):
        try:
            with open(self.sessions_file, 'w') as f:
                json.dump(self.sessions, f, indent=2)
        except Exception as e:
            logger.error(f"Error saving sessions: {e}")
    
    def save_user_logs(self):
        try:
            with open(self.user_logs_file, 'w') as f:
                json.dump(self.user_logs, f, indent=2)
        except Exception as e:
            logger.error(f"Error saving user logs: {e}")
    
    def hash_password(self, password: str) -> str:
        return hashlib.sha256(password.encode()).hexdigest()
    
    def verify_user(self, username: str, password: str) -> bool:
        if username in self.users and self.users[username].get("is_active", True):
            hashed_password = self.hash_password(password)
            return self.users[username]["password"] == hashed_password
        return False
    
    def create_user(self, username: str, password: str, role: str = "user") -> tuple:
        if username in self.users:
            return False, "User already exists"
        
        if role not in ["admin", "user"]:
            return False, "Invalid role. Must be 'admin' or 'user'"
        
        self.users[username] = {
            "password": self.hash_password(password),
            "role": role,
            "created_at": datetime.now().isoformat(),
            "is_active": True,
            "created_by": "system",
            "settings": {
                "node": "",
                "pk": "",
                "token_ca": "",
                "speed": "medium",
                "num_cycles": 10,
                "buy_amount_wei": 10
            }
        }
        self.save_users()
        
        if username not in self.user_logs:
            self.user_logs[username] = []
            self.save_user_logs()
            
        return True, f"User '{username}' created successfully with role '{role}'"
    
    def create_session(self, username: str) -> str:
        session_id = str(uuid.uuid4())
        self.sessions[session_id] = {
            "username": username,
            "role": self.users[username]["role"],
            "login_time": datetime.now().isoformat(),
            "last_activity": datetime.now().isoformat()
        }
        self.save_sessions()
        return session_id
    
    def validate_session(self, session_id: str) -> Optional[Dict]:
        if session_id in self.sessions:
            self.sessions[session_id]["last_activity"] = datetime.now().isoformat()
            self.save_sessions()
            
            username = self.sessions[session_id]["username"]
            if username in self.users and self.users[username].get("is_active", True):
                return {
                    "username": username,
                    "role": self.sessions[session_id]["role"]
                }
        return None
    
    def logout(self, session_id: str):
        if session_id in self.sessions:
            del self.sessions[session_id]
            self.save_sessions()
    
    def change_password(self, username: str, old_password: str, new_password: str) -> bool:
        if username in self.users and self.verify_user(username, old_password):
            encrypted_key = self.key_manager.get_encrypted_key(username)
            if encrypted_key:
                private_key = self.key_manager.decrypt_private_key(encrypted_key, old_password)
                if private_key:
                    new_encrypted_key = self.key_manager.encrypt_private_key(private_key, new_password)
                    self.key_manager.save_encrypted_key(username, new_encrypted_key)
            
            self.users[username]["password"] = self.hash_password(new_password)
            self.save_users()
            return True
        return False
    
    def get_all_users(self) -> List[Dict]:
        users_list = []
        for username, user_data in self.users.items():
            users_list.append({
                "username": username,
                "role": user_data["role"],
                "created_at": user_data["created_at"],
                "is_active": user_data.get("is_active", True)
            })
        return users_list
    
    def delete_user(self, username: str) -> bool:
        if username in self.users and username != "admin":
            self.key_manager.delete_encrypted_key(username)
            del self.users[username]
            self.save_users()
            
            if username in self.user_logs:
                del self.user_logs[username]
                self.save_user_logs()
            
            sessions_to_remove = []
            for session_id, session_data in self.sessions.items():
                if session_data["username"] == username:
                    sessions_to_remove.append(session_id)
            
            for session_id in sessions_to_remove:
                del self.sessions[session_id]
            self.save_sessions()
            
            return True
        return False
    
    def toggle_user_status(self, username: str) -> bool:
        if username in self.users and username != "admin":
            current_status = self.users[username].get("is_active", True)
            self.users[username]["is_active"] = not current_status
            self.save_users()
            return True
        return False
    
    def get_user_settings(self, username: str) -> Dict:
        if username in self.users:
            settings = self.users[username].get("settings", {}).copy()
            if 'pk' in settings:
                settings['pk'] = ''
            return settings
        return {}
    
    def save_user_settings(self, username: str, settings: Dict, password: str):
        if username in self.users:
            private_key = settings.get('pk', '')
            safe_settings = settings.copy()
            safe_settings['pk'] = ''
            
            self.users[username]["settings"] = safe_settings
            self.save_users()
            
            if private_key and private_key.strip():
                encrypted_key = self.key_manager.encrypt_private_key(private_key, password)
                self.key_manager.save_encrypted_key(username, encrypted_key)
                logger.info(f"Private key encrypted and stored for user: {username}")
            elif private_key == '':
                self.key_manager.delete_encrypted_key(username)
                logger.info(f"Private key cleared for user: {username}")
    
    def get_decrypted_private_key(self, username: str, password: str) -> Optional[str]:
        encrypted_key = self.key_manager.get_encrypted_key(username)
        if encrypted_key:
            return self.key_manager.decrypt_private_key(encrypted_key, password)
        return None
    
    def add_user_log(self, username: str, message: str):
        if username not in self.user_logs:
            self.user_logs[username] = []
        
        log_entry = {
            "timestamp": datetime.now().isoformat(),
            "message": message
        }
        self.user_logs[username].append(log_entry)
        
        if len(self.user_logs[username]) > 1000:
            self.user_logs[username] = self.user_logs[username][-1000:]
        
        self.save_user_logs()
    
    def get_user_logs(self, username: str) -> List[Dict]:
        return self.user_logs.get(username, [])

# Initialize user manager
user_manager = SecureUserManager()

# ==================== DEPENDENCIES ====================
async def get_current_user(x_session_id: str = Header(None)):
    if not x_session_id:
        raise HTTPException(status_code=401, detail="Session ID required")
    
    user_info = user_manager.validate_session(x_session_id)
    if not user_info:
        raise HTTPException(status_code=401, detail="Invalid or expired session")
    
    return user_info

async def require_admin(user_info: Dict = Depends(get_current_user)):
    if user_info["role"] != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    return user_info

# ==================== PARALLEL MICRO BUY BOT ====================
class ParallelMicroBuyBot:
    UNISWAP_V2_ROUTER = "0x4752ba5DBc23f44D87826276BF6Fd6b1C372aD24"
    WETH_ADDRESS = "0x4200000000000000000000000000000000000006"
    
    BUY_AMOUNT_WEI = 10
    BUY_AMOUNT_ETH = 0.00000000000000001
    
    SPEED_CONFIGS = {
        "slow": {"wallets_per_cycle": 3, "cycle_interval": 20},
        "medium": {"wallets_per_cycle": 10, "cycle_interval": 20},
        "fast": {"wallets_per_cycle": 25, "cycle_interval": 20}
    }
    
    UNISWAP_V2_ROUTER_ABI = [
        {
            "inputs": [
                {"internalType": "uint256", "name": "amountOutMin", "type": "uint256"},
                {"internalType": "address[]", "name": "path", "type": "address[]"},
                {"internalType": "address", "name": "to", "type": "address"},
                {"internalType": "uint256", "name": "deadline", "type": "uint256"}
            ],
            "name": "swapExactETHForTokens",
            "outputs": [{"internalType": "uint256[]", "name": "amounts", "type": "uint256[]"}],
            "stateMutability": "payable",
            "type": "function"
        }
    ]

    def __init__(self, config: BotConfig):
        self.config = config
        self.w3 = Web3(Web3.HTTPProvider(config.rpc_url))
        
        if not self.w3.is_connected():
            raise Exception("Failed to connect to RPC")
        
        self.master_account: LocalAccount = Account.from_key(config.master_private_key)
        logger.info(f"Master wallet: {self.master_account.address}")
        
        self.generated_wallets: List[Dict] = []
        self.is_running = False
        self.current_operation = None
        
        self.uniswap_v2_router = self.w3.eth.contract(
            address=self.w3.to_checksum_address(self.UNISWAP_V2_ROUTER),
            abi=self.UNISWAP_V2_ROUTER_ABI
        )

    def get_eth_price_usd(self) -> float:
        return ETHPriceService.get_eth_price_usd()

    def get_current_gas_price(self) -> Dict:
        current_time = time.time()
        
        if hasattr(self, '_gas_price_cache') and self._gas_price_cache:
            cache_time = getattr(self, '_gas_price_cache_time', 0)
            if current_time - cache_time < 60:
                logger.debug(f"Using cached gas price: {self._gas_price_cache['gas_price_gwei']:.2f} Gwei")
                return self._gas_price_cache
        
        try:
            try:
                gas_price = self.w3.eth.gas_price
                gas_price_gwei = float(self.w3.from_wei(gas_price, 'gwei'))
                
                if gas_price_gwei > 0:
                    logger.info(f"Base gas price from RPC: {gas_price_gwei:.6f} Gwei")
                    result = {
                        'gas_price_wei': gas_price,
                        'gas_price_gwei': gas_price_gwei,
                        'source': 'rpc',
                        'success': True
                    }
                    self._gas_price_cache = result
                    self._gas_price_cache_time = current_time
                    return result
                else:
                    logger.warning(f"Invalid gas price from RPC: {gas_price_gwei} Gwei")
            except Exception as e:
                logger.warning(f"RPC gas price failed: {e}")
            
            try:
                fee_history = self.w3.eth.fee_history(1, 'latest', [50])
                if fee_history and fee_history['baseFeePerGas']:
                    base_fee = fee_history['baseFeePerGas'][-1]
                    gas_price = int(base_fee * 1.1)
                    gas_price_gwei = float(self.w3.from_wei(gas_price, 'gwei'))
                    
                    logger.info(f"Base gas price from fee history: {gas_price_gwei:.6f} Gwei")
                    result = {
                        'gas_price_wei': gas_price,
                        'gas_price_gwei': gas_price_gwei,
                        'source': 'fee_history',
                        'success': True
                    }
                    self._gas_price_cache = result
                    self._gas_price_cache_time = current_time
                    return result
            except Exception as e:
                logger.warning(f"Fee history method failed: {e}")
            
            base_typical_gas_gwei = 0.01
            base_gas_wei = self.w3.to_wei(base_typical_gas_gwei, 'gwei')
            
            logger.info(f"Using typical Base gas price: {base_typical_gas_gwei:.6f} Gwei")
            result = {
                'gas_price_wei': base_gas_wei,
                'gas_price_gwei': base_typical_gas_gwei,
                'source': 'fallback',
                'success': True
            }
            self._gas_price_cache = result
            self._gas_price_cache_time = current_time
            return result
            
        except Exception as e:
            logger.error(f"All gas price strategies failed: {e}")
            fallback_gas = self.w3.to_wei(0.01, 'gwei')
            result = {
                'gas_price_wei': fallback_gas,
                'gas_price_gwei': 0.01,
                'source': 'emergency_fallback',
                'success': False
            }
            self._gas_price_cache = result
            self._gas_price_cache_time = current_time
            return result
    
    def calculate_gas_costs(self) -> Dict:
        gas_info = self.get_current_gas_price()
        gas_price_wei = gas_info['gas_price_wei']
        
        FUNDING_GAS_LIMIT = 21000
        BUY_GAS_LIMIT = 250000
        
        funding_gas_eth = float(self.w3.from_wei(FUNDING_GAS_LIMIT * gas_price_wei, 'ether'))
        buy_gas_eth = float(self.w3.from_wei(BUY_GAS_LIMIT * gas_price_wei, 'ether'))
        
        return {
            'funding_gas_eth': funding_gas_eth,
            'buy_gas_eth': buy_gas_eth,
            'total_gas_per_wallet_eth': funding_gas_eth + buy_gas_eth,
            'gas_price_gwei': gas_info['gas_price_gwei'],
            'gas_source': gas_info.get('source', 'unknown'),
            'success': True
        }

    def estimate_cycles_cost_usd(self, speed: str, num_cycles: int) -> Dict:
        try:
            if speed not in self.SPEED_CONFIGS:
                return {
                    'error': f"Invalid speed: {speed}. Must be one of {list(self.SPEED_CONFIGS.keys())}",
                    'success': False
                }
        
            if num_cycles <= 0 or num_cycles > 1000:
                return {
                    'error': f"Invalid cycle count: {num_cycles}. Must be between 1 and 1000",
                    'success': False
                }
        
            speed_config = self.SPEED_CONFIGS[speed]
            wallets_per_cycle = speed_config['wallets_per_cycle']
            
            total_wallets_needed = num_cycles * wallets_per_cycle
            total_transactions = num_cycles * wallets_per_cycle
            
            gas_costs = self.calculate_gas_costs()
            eth_price_usd = self.get_eth_price_usd()
            current_balance = self.get_master_balance_eth()
            
            funding_gas_per_wallet_eth = gas_costs['funding_gas_eth']
            buy_gas_per_wallet_eth = gas_costs['buy_gas_eth']
            total_gas_per_wallet_eth = gas_costs['total_gas_per_wallet_eth']
            
            total_funding_gas_eth = funding_gas_per_wallet_eth * total_wallets_needed
            total_buy_gas_eth = buy_gas_per_wallet_eth * total_transactions
            total_gas_eth = total_funding_gas_eth + total_buy_gas_eth
            
            total_buy_eth = self.BUY_AMOUNT_ETH * total_transactions
            
            funding_per_wallet_eth = self.BUY_AMOUNT_ETH + buy_gas_per_wallet_eth + funding_gas_per_wallet_eth
            
            total_funding_eth = funding_per_wallet_eth * total_wallets_needed
            total_cost_eth = total_funding_eth + total_gas_eth
            
            total_cost_usd = total_cost_eth * eth_price_usd
            total_gas_usd = total_gas_eth * eth_price_usd
            total_funding_usd = total_funding_eth * eth_price_usd
            
            has_sufficient_balance = current_balance >= total_cost_eth
            balance_warning = None
            if not has_sufficient_balance:
                balance_warning = f"Insufficient balance. Need {total_cost_eth:.6f} ETH, have {current_balance:.6f} ETH"
            
            estimation_data = {
                'estimation_for': f"{num_cycles} cycles at {speed} speed",
                'network_conditions': {
                    'eth_price_usd': eth_price_usd,
                    'gas_price_gwei': gas_costs['gas_price_gwei'],
                    'gas_source': gas_costs.get('gas_source', 'estimated'),
                    'buy_amount_wei': self.BUY_AMOUNT_WEI,
                    'buy_amount_eth': self.BUY_AMOUNT_ETH
                },
                'transaction_counts': {
                    'total_cycles': num_cycles,
                    'total_transactions': total_transactions,
                    'wallets_needed': total_wallets_needed,
                    'wallets_per_cycle': wallets_per_cycle,
                    'funding_transactions': total_wallets_needed,
                    'buy_transactions': total_transactions
                },
                'cost_breakdown_eth': {
                    'funding_per_wallet_eth': funding_per_wallet_eth,
                    'gas_per_wallet_eth': total_gas_per_wallet_eth,
                    'total_funding_eth': total_funding_eth,
                    'total_gas_eth': total_gas_eth,
                    'total_buy_amount_eth': total_buy_eth,
                    'total_cost_eth': total_cost_eth
                },
                'cost_breakdown_usd': {
                    'funding_per_wallet_usd': funding_per_wallet_eth * eth_price_usd,
                    'gas_per_wallet_usd': total_gas_per_wallet_eth * eth_price_usd,
                    'total_funding_usd': total_funding_usd,
                    'total_gas_usd': total_gas_usd,
                    'total_buy_amount_usd': total_buy_eth * eth_price_usd,
                    'total_cost_usd': total_cost_usd
                },
                'requirements': {
                    'minimum_eth_required': total_cost_eth,
                    'current_balance_eth': current_balance,
                    'minimum_usd_required': total_cost_usd,
                    'has_sufficient_balance': has_sufficient_balance
                },
                'success': True
            }
            
            if balance_warning:
                estimation_data['warning'] = balance_warning
            
            return estimation_data
            
        except Exception as e:
            logger.error(f"Error in cost estimation: {e}")
            return {
                'estimation_for': f"{num_cycles} cycles at {speed} speed",
                'error': str(e),
                'success': False,
                'network_conditions': {
                    'eth_price_usd': self.get_eth_price_usd(),
                    'gas_price_gwei': 0.1,
                    'gas_source': 'fallback',
                    'buy_amount_wei': self.BUY_AMOUNT_WEI,
                    'buy_amount_eth': self.BUY_AMOUNT_ETH
                },
                'requirements': {
                    'minimum_eth_required': 0.01,
                    'current_balance_eth': self.get_master_balance_eth(),
                    'minimum_usd_required': 25.0,
                    'has_sufficient_balance': False
                }
            }
    
    def get_master_balance_eth(self) -> float:
        try:
            balance_wei = self.w3.eth.get_balance(self.master_account.address)
            return float(self.w3.from_wei(balance_wei, 'ether'))
        except Exception as e:
            logger.error(f"Error getting balance: {e}")
            return 0.0

    def create_wallet(self) -> Dict:
        account = Account.create()
        return {
            'address': account.address,
            'private_key': account.key.hex(),
            'balance_eth': 0.0,
            'created_at': time.time()
        }

    def generate_wallets(self, count: int) -> List[Dict]:
        wallets = []
        for i in range(count):
            wallet = self.create_wallet()
            wallets.append(wallet)
            self.generated_wallets.append(wallet)
        
        logger.info(f"Generated {count} new wallets")
        return wallets

    def calculate_funding_amount(self) -> float:
        gas_costs = self.calculate_gas_costs()
        funding_amount = self.BUY_AMOUNT_ETH + gas_costs['buy_gas_eth']
        funding_amount *= 1.1
        return funding_amount

    async def fund_wallet_with_nonce(self, wallet_address: str, amount_eth: float, nonce: int) -> bool:
        try:
            amount_wei = self.w3.to_wei(amount_eth, 'ether')
            gas_price = self.w3.eth.gas_price
            gas_limit = 21000
            
            master_balance_wei = self.w3.eth.get_balance(self.master_account.address)
            total_cost_wei = amount_wei + (gas_limit * gas_price)
            
            if master_balance_wei < total_cost_wei:
                logger.error(f"Insufficient funds to fund wallet")
                return False
            
            tx = {
                'to': wallet_address,
                'value': amount_wei,
                'gas': gas_limit,
                'gasPrice': gas_price,
                'nonce': nonce,
                'chainId': 8453
            }
            
            signed_tx = self.master_account.sign_transaction(tx)
            raw_tx = signed_tx.rawTransaction if hasattr(signed_tx, 'rawTransaction') else signed_tx.raw_transaction
            
            tx_hash = self.w3.eth.send_raw_transaction(raw_tx)
            receipt = await asyncio.get_event_loop().run_in_executor(
                None, 
                lambda: self.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
            )
            
            if receipt.status == 1:
                logger.info(f"Funded wallet {wallet_address} with {amount_eth:.8f} ETH (nonce: {nonce})")
                return True
            else:
                logger.error(f"Funding transaction failed for nonce {nonce}")
                return False
                
        except Exception as e:
            logger.error(f"Error funding wallet {wallet_address} with nonce {nonce}: {e}")
            return False

    async def execute_parallel_funding_with_nonces(self, wallets: List[Dict], funding_amount: float) -> List[Dict]:
        base_nonce = self.w3.eth.get_transaction_count(self.master_account.address)
        logger.info(f"Base nonce: {base_nonce}, funding {len(wallets)} wallets")
        
        funding_tasks = []
        
        for i, wallet in enumerate(wallets):
            nonce = base_nonce + i
            task = self.fund_wallet_with_nonce(wallet['address'], funding_amount, nonce)
            funding_tasks.append((task, wallet, nonce))
        
        logger.info(f"Executing {len(funding_tasks)} parallel funding transactions")
        
        results = []
        for task, wallet, nonce in funding_tasks:
            try:
                result = await task
                results.append((result, wallet, nonce))
            except Exception as e:
                results.append((False, wallet, nonce))
                logger.error(f"Funding task failed for nonce {nonce}: {e}")
        
        processed_results = []
        successful_funding = 0
        
        for result, wallet, nonce in results:
            if result:
                successful_funding += 1
                wallet['balance_eth'] = funding_amount
                processed_results.append({
                    'success': True,
                    'wallet_address': wallet['address'],
                    'nonce': nonce
                })
            else:
                processed_results.append({
                    'success': False,
                    'error': 'Funding failed',
                    'wallet_address': wallet['address'],
                    'nonce': nonce
                })
        
        logger.info(f"Parallel funding with nonces completed: {successful_funding}/{len(wallets)} successful")
        return processed_results

    async def execute_micro_buy(self, wallet: Dict, token_address: str) -> Dict:
        try:
            account = Account.from_key(wallet['private_key'])
            
            wallet_balance_wei = self.w3.eth.get_balance(account.address)
            required_wei = self.BUY_AMOUNT_WEI
            
            if wallet_balance_wei < required_wei:
                return {'success': False, 'error': 'Insufficient wallet balance'}
            
            path = [self.WETH_ADDRESS, self.w3.to_checksum_address(token_address)]
            deadline = int(time.time()) + 1200
            
            gas_price = self.w3.eth.gas_price
            
            swap_data = self.uniswap_v2_router.functions.swapExactETHForTokens(
                0,
                path,
                account.address,
                deadline
            ).build_transaction({
                'from': account.address,
                'value': self.BUY_AMOUNT_WEI,
                'gas': 200000,
                'gasPrice': gas_price,
                'nonce': self.w3.eth.get_transaction_count(account.address),
                'chainId': 8453
            })
            
            if 'from' in swap_data:
                del swap_data['from']
            
            signed_tx = account.sign_transaction(swap_data)
            raw_tx = signed_tx.rawTransaction if hasattr(signed_tx, 'rawTransaction') else signed_tx.raw_transaction
            
            tx_hash = self.w3.eth.send_raw_transaction(raw_tx)
            
            receipt = await asyncio.get_event_loop().run_in_executor(
                None, 
                lambda: self.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=180)
            )
            
            if receipt.status == 1:
                gas_used_eth = float(self.w3.from_wei(receipt.gasUsed * receipt.effectiveGasPrice, 'ether'))
                logger.info(f"Parallel micro buy successful. Hash: {tx_hash.hex()}")
                
                return {
                    'success': True,
                    'hash': tx_hash.hex(),
                    'buy_amount_wei': self.BUY_AMOUNT_WEI,
                    'gas_used_eth': gas_used_eth
                }
            else:
                return {'success': False, 'error': 'Transaction failed'}
                
        except Exception as e:
            return {'success': False, 'error': str(e)}

    async def execute_parallel_micro_buys(self, wallets: List[Dict], token_address: str) -> List[Dict]:
        buy_tasks = []
        for wallet in wallets:
            if wallet['balance_eth'] >= self.BUY_AMOUNT_ETH:
                task = self.execute_micro_buy(wallet, token_address)
                buy_tasks.append(task)
        
        logger.info(f"Executing {len(buy_tasks)} parallel micro buys...")
        results = await asyncio.gather(*buy_tasks, return_exceptions=True)
        
        processed_results = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                processed_results.append({
                    'success': False, 
                    'error': str(result),
                    'wallet_index': i
                })
            else:
                result['wallet_index'] = i
                processed_results.append(result)
        
        return processed_results

    async def execute_micro_buy_cycle(self, config: MicroBuyConfig, cycle_number: int) -> Dict:
        if not self.is_running:
            return {'success': False, 'error': 'Operation stopped by user'}
            
        speed_config = self.SPEED_CONFIGS[config.speed]
        wallet_count = speed_config['wallets_per_cycle']
        
        funding_amount = self.calculate_funding_amount()
        
        logger.info(f"Starting FULL PARALLEL micro buy cycle {cycle_number}: {wallet_count} wallets")
        logger.info(f"Funding each wallet with {funding_amount:.8f} ETH")
        
        wallets = self.generate_wallets(wallet_count)
        
        logger.info(f"EXECUTING {wallet_count} PARALLEL FUNDING TRANSACTIONS WITH NONCE MANAGEMENT...")
        funding_start_time = time.time()
        
        funding_results = await self.execute_parallel_funding_with_nonces(wallets, funding_amount)
        funding_time = time.time() - funding_start_time
        
        successful_funding = sum(1 for result in funding_results if result.get('success'))
        logger.info(f"Parallel funding with nonces completed in {funding_time:.2f} seconds: {successful_funding}/{wallet_count} successful")
        
        if successful_funding == 0:
            return {'success': False, 'error': 'All wallet funding failed'}
        
        logger.info("Waiting for funding transactions to confirm...")
        await asyncio.sleep(5)
        
        logger.info(f"EXECUTING {successful_funding} PARALLEL MICRO BUYS...")
        buy_start_time = time.time()
        
        buy_results = await self.execute_parallel_micro_buys(wallets, config.token_address)
        buy_time = time.time() - buy_start_time
        
        total_execution_time = funding_time + buy_time
        
        successful_buys = sum(1 for result in buy_results if result.get('success'))
        success_rate = successful_buys / len(buy_results) if buy_results else 0
        
        logger.info(f"Full parallel cycle completed in {total_execution_time:.2f} seconds")
        logger.info(f"Results: {successful_buys}/{len(buy_results)} successful ({success_rate:.1%})")
        
        return {
            'success': True,
            'wallets_used': len(wallets),
            'successful_buys': successful_buys,
            'success_rate': success_rate,
            'total_buys': len(buy_results),
            'buy_amount_wei': self.BUY_AMOUNT_WEI,
            'funded_wallets': successful_funding,
            'funding_time_seconds': funding_time,
            'buy_time_seconds': buy_time,
            'total_execution_time_seconds': total_execution_time,
            'parallel_funding': True,
            'parallel_buying': True
        }

    def stop_operation(self):
        self.is_running = False
        logger.info("Operation stop requested")
        return True

    async def start_operation(self, config: MicroBuyConfig, operation_id: str, username: str):
        self.is_running = True
        self.current_operation = config
        
        try:
            for cycle in range(config.num_cycles):
                if not self.is_running:
                    logger.info("Operation stopped by user")
                    user_manager.add_user_log(username, "Operation was stopped by user")
                    break
                 
                if operation_id in active_operations:
                    active_operations[operation_id]["progress"]["cycles_completed"] = cycle
                    active_operations[operation_id]["status"] = "running"
                    user_manager.add_user_log(username, f"Starting cycle {cycle + 1}/{config.num_cycles}")

                cycle_result = await self.execute_micro_buy_cycle(config, cycle + 1)
                
                if cycle_result.get('success'):
                    if operation_id in active_operations:
                        active_operations[operation_id]["progress"]["successful_buys"] += cycle_result["successful_buys"]
                        active_operations[operation_id]["progress"]["total_buys"] += cycle_result["total_buys"]
                        active_operations[operation_id]["progress"]["cycles_completed"] = cycle + 1
                        user_manager.add_user_log(username, f"Cycle {cycle + 1} completed: {cycle_result['successful_buys']}/{cycle_result['total_buys']} successful")
                    
                if cycle < config.num_cycles - 1 and self.is_running:
                    await asyncio.sleep(self.SPEED_CONFIGS[config.speed]['cycle_interval'])
            
            if operation_id in active_operations:
                if self.is_running:
                    active_operations[operation_id]["status"] = "completed"
                    logger.info("Operation completed successfully")
                    user_manager.add_user_log(username, "Operation completed successfully")
                else:
                    active_operations[operation_id]["status"] = "stopped"
                    logger.info("Operation was stopped")
                    user_manager.add_user_log(username, "Operation was stopped")
                    
        except Exception as e:
            logger.error(f"Operation failed: {e}")
            if operation_id in active_operations:
                active_operations[operation_id]["status"] = "failed"
            user_manager.add_user_log(username, f"Operation failed: {str(e)}")
        finally:
            self.is_running = False
            self.current_operation = None

# ==================== FASTAPI APPLICATION ====================
app = FastAPI(title="Parallel Micro Buy Bot API", lifespan=lifespan)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Store active operations
active_operations: Dict[str, Dict] = {}
log_consumers: Dict[str, List[WebSocket]] = {}

class LogHandler(logging.Handler):
    def __init__(self, user_id: str):
        super().__init__()
        self.user_id = user_id
        self.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))

    def emit(self, record):
        log_entry = self.format(record)
        asyncio.create_task(broadcast_log(self.user_id, log_entry))
        user_manager.add_user_log(self.user_id, log_entry)

async def broadcast_log(user_id: str, message: str):
    if user_id in log_consumers:
        disconnected = []
        for websocket in log_consumers[user_id]:
            try:
                await websocket.send_text(json.dumps({
                    "type": "log",
                    "message": message,
                    "timestamp": datetime.now().isoformat()
                }))
            except:
                disconnected.append(websocket)
        
        for ws in disconnected:
            log_consumers[user_id].remove(ws)

# ==================== AUTHENTICATION ROUTES ====================
@app.post("/api/login")
async def login(login_data: UserLogin):
    if user_manager.verify_user(login_data.username, login_data.password):
        session_id = user_manager.create_session(login_data.username)
        
        logger = logging.getLogger()
        log_handler = LogHandler(login_data.username)
        logger.addHandler(log_handler)
        
        return {
            "success": True, 
            "session_id": session_id, 
            "username": login_data.username,
            "role": user_manager.users[login_data.username]["role"],
            "message": "Login successful"
        }
    else:
        return {"success": False, "error": "Invalid username or password"}

@app.post("/api/debug-login")
async def debug_login(login_data: UserLogin):
    """Debug login endpoint to see what's happening"""
    print(f"DEBUG: Login attempt for user: {login_data.username}")
    
    user_exists = login_data.username in user_manager.users
    print(f"DEBUG: User exists: {user_exists}")
    
    if user_exists:
        user_data = user_manager.users[login_data.username]
        print(f"DEBUG: User data: {user_data}")
        is_verified = user_manager.verify_user(login_data.username, login_data.password)
        print(f"DEBUG: Password verified: {is_verified}")
    
    if user_manager.verify_user(login_data.username, login_data.password):
        session_id = user_manager.create_session(login_data.username)
        print(f"DEBUG: Login successful, session created: {session_id}")
        return {
            "success": True, 
            "session_id": session_id, 
            "username": login_data.username,
            "role": user_manager.users[login_data.username]["role"],
            "message": "Login successful"
        }
    else:
        print(f"DEBUG: Login failed")
        return {"success": False, "error": "Invalid username or password"}

@app.post("/api/logout")
async def logout(user_info: Dict = Depends(get_current_user)):
    user_manager.logout(user_info["username"])
    return {"success": True, "message": "Logout successful"}

@app.post("/api/change-password")
async def change_password(
    change_data: ChangePassword,
    user_info: Dict = Depends(get_current_user)
):
    username = user_info["username"]
    if user_manager.change_password(username, change_data.old_password, change_data.new_password):
        return {"success": True, "message": "Password changed successfully"}
    else:
        return {"success": False, "error": "Invalid old password"}

# ==================== ADMIN ROUTES ====================
async def require_admin(user_info: Dict = Depends(get_current_user)):
    if user_info.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    return user_info

@app.get("/api/admin/check-access")
async def check_admin_access(user_info: Dict = Depends(require_admin)):
    return {
        "success": True, 
        "message": "Admin access confirmed",
        "username": user_info["username"],
        "role": user_info["role"]
    }

@app.post("/api/admin/create-user")
async def admin_create_user(
    user_data: UserCreate,
    user_info: Dict = Depends(require_admin)
):
    try:
        print(f"Creating user: {user_data.username}, role: {user_data.role}")
        
        if not user_data.username or not user_data.password:
            return {"success": False, "message": "Username and password are required"}
        
        if len(user_data.username) < 3:
            return {"success": False, "message": "Username must be at least 3 characters"}
        
        if len(user_data.password) < 6:
            return {"success": False, "message": "Password must be at least 6 characters"}
        
        if user_data.role not in ["admin", "user"]:
            return {"success": False, "message": "Role must be 'admin' or 'user'"}
        
        success, message = user_manager.create_user(user_data.username, user_data.password, user_data.role)
        
        if success:
            print(f"User created successfully: {user_data.username}")
            return {"success": True, "message": message}
        else:
            print(f"User creation failed: {message}")
            return {"success": False, "message": message}
            
    except Exception as e:
        print(f"Error creating user: {str(e)}")
        return {"success": False, "message": f"Server error: {str(e)}"}

@app.get("/api/admin/users")
async def get_all_users(user_info: Dict = Depends(require_admin)):
    users = user_manager.get_all_users()
    return {"success": True, "users": users}

@app.delete("/api/admin/users/{username}")
async def delete_user(username: str, user_info: Dict = Depends(require_admin)):
    if user_manager.delete_user(username):
        return {"success": True, "message": f"User '{username}' deleted successfully"}
    else:
        return {"success": False, "error": "Failed to delete user"}

@app.post("/api/admin/users/{username}/toggle")
async def toggle_user_status(username: str, user_info: Dict = Depends(require_admin)):
    if user_manager.toggle_user_status(username):
        return {"success": True, "message": f"User status toggled successfully"}
    else:
        return {"success": False, "error": "Failed to toggle user status"}

@app.get("/api/admin/system-stats")
async def get_system_stats(user_info: Dict = Depends(require_admin)):
    try:
        total_operations = len(active_operations)
        
        running_ops = sum(1 for op in active_operations.values() if op.get("status") == "running")
        completed_ops = sum(1 for op in active_operations.values() if op.get("status") == "completed")
        stopped_ops = sum(1 for op in active_operations.values() if op.get("status") == "stopped")
        failed_ops = sum(1 for op in active_operations.values() if op.get("status") == "failed")
        
        total_successful_buys = sum(op.get("progress", {}).get("successful_buys", 0) for op in active_operations.values())
        total_attempted_buys = sum(op.get("progress", {}).get("total_buys", 0) for op in active_operations.values())
        success_rate = (total_successful_buys / total_attempted_buys * 100) if total_attempted_buys > 0 else 0
        
        active_sessions = len(user_manager.sessions)
        total_users = len(user_manager.users)
        
        active_users_last_hour = 0
        current_time = datetime.now().timestamp()
        for session in user_manager.sessions.values():
            last_activity = datetime.fromisoformat(session["last_activity"]).timestamp()
            if current_time - last_activity < 3600:
                active_users_last_hour += 1
        
        total_cycles_completed = sum(op.get("progress", {}).get("cycles_completed", 0) for op in active_operations.values())
        total_cycles_planned = sum(op.get("config", {}).num_cycles for op in active_operations.values() if hasattr(op.get("config"), 'num_cycles'))
        completion_rate = (total_cycles_completed / total_cycles_planned * 100) if total_cycles_planned > 0 else 0
        
        unique_tokens = len(set(op.get("config", {}).token_address for op in active_operations.values() if hasattr(op.get("config"), 'token_address')))
        
        unique_nodes = set()
        for username, user_data in user_manager.users.items():
            node = user_data.get("settings", {}).get("node")
            if node:
                unique_nodes.add(node)
        
        stats = {
            "success": True,
            "stats": {
                "total_users": total_users,
                "active_sessions": active_sessions,
                "active_users_last_hour": active_users_last_hour,
                "total_operations": total_operations,
                "running_operations": running_ops,
                "completed_operations": completed_ops,
                "stopped_operations": stopped_ops,
                "failed_operations": failed_ops,
                "total_successful_buys": total_successful_buys,
                "total_attempted_buys": total_attempted_buys,
                "success_rate": round(success_rate, 2),
                "completion_rate": round(completion_rate, 2),
                "total_cycles_completed": total_cycles_completed,
                "total_cycles_planned": total_cycles_planned,
                "unique_tokens_traded": unique_tokens,
                "unique_rpc_nodes": len(unique_nodes),
                "websocket_connections": sum(len(consumers) for consumers in log_consumers.values()),
                "active_operation_threads": running_ops
            }
        }
        
        return stats
        
    except Exception as e:
        logger.error(f"Error generating system stats: {e}")
        return {
            "success": False, 
            "error": str(e),
            "stats": {
                "total_users": len(user_manager.users),
                "active_sessions": len(user_manager.sessions),
                "active_users_last_hour": 0,
                "total_operations": len(active_operations),
                "running_operations": 0,
                "completed_operations": 0,
                "total_successful_buys": 0,
                "total_attempted_buys": 0,
                "success_rate": 0,
                "completion_rate": 0
            }
        }

@app.get("/api/admin/all-operations")
async def get_all_operations(user_info: Dict = Depends(require_admin)):
    try:
        formatted_ops = {}
        for op_id, op in active_operations.items():
            formatted_ops[op_id] = {
                "username": op["username"],
                "config": {
                    "token_address": op["config"].token_address,
                    "speed": op["config"].speed,
                    "num_cycles": op["config"].num_cycles
                },
                "start_time": op["start_time"],
                "status": op["status"],
                "progress": op["progress"]
            }
        
        return {"success": True, "operations": formatted_ops}
    except Exception as e:
        return {"success": False, "error": str(e)}

# ==================== USER ROUTES ====================
@app.post("/api/settings")
async def save_settings(
    settings: SecureBotSettings,
    user_info: Dict = Depends(get_current_user)
):
    username = user_info["username"]
    
    if not user_manager.verify_user(username, settings.password):
        return {"success": False, "error": "Invalid password"}
    
    try:
        user_manager.save_user_settings(username, settings.dict(), settings.password)
        user_manager.add_user_log(username, "Settings updated successfully")
        return {"success": True, "message": "Settings saved securely"}
    except Exception as e:
        user_manager.add_user_log(username, f"Failed to save settings: {str(e)}")
        return {"success": False, "error": str(e)}

@app.get("/api/settings")
async def get_settings(user_info: Dict = Depends(get_current_user)):
    username = user_info["username"]
    settings = user_manager.get_user_settings(username)
    return {"success": True, "settings": settings}

@app.get("/api/wallet-info")
async def get_wallet_info(
    user_info: Dict = Depends(get_current_user),
    password: str = Header(None)
):
    username = user_info["username"]
    
    if not password:
        return {"success": False, "error": "Password required", "wallet_configured": False}
    
    if not user_manager.verify_user(username, password):
        return {"success": False, "error": "Invalid password"}
    
    private_key = user_manager.get_decrypted_private_key(username, password)
    if not private_key:
        return {"success": False, "error": "No wallet configured", "wallet_configured": False}
    
    try:
        settings = user_manager.get_user_settings(username)
        if not settings.get('node'):
            return {"success": False, "error": "RPC node not configured"}
        
        bot_config = BotConfig(
            rpc_url=settings.get('node'),
            master_private_key=private_key
        )
        bot = ParallelMicroBuyBot(bot_config)
        
        balance = bot.get_master_balance_eth()
        eth_price = ETHPriceService.get_eth_price_usd()
        
        return {
            "success": True,
            "wallet_address": bot.master_account.address,
            "balance_eth": balance,
            "balance_usd": balance * eth_price,
            "rpc_url": settings.get('node'),
            "wallet_configured": True
        }
    except Exception as e:
        return {"success": False, "error": str(e)}

@app.get("/api/gas-info")
async def get_gas_info(
    user_info: Dict = Depends(get_current_user),
    password: str = Header(None)
):
    username = user_info["username"]
    
    if not password:
        return {"success": False, "error": "Password required"}
    
    if not user_manager.verify_user(username, password):
        return {"success": False, "error": "Invalid password"}
    
    private_key = user_manager.get_decrypted_private_key(username, password)
    if not private_key:
        return {"success": False, "error": "Please configure wallet first"}
    
    try:
        settings = user_manager.get_user_settings(username)
        if not settings.get('node'):
            return {"success": False, "error": "RPC node not configured"}
        
        bot_config = BotConfig(
            rpc_url=settings.get('node'),
            master_private_key=private_key
        )
        bot = ParallelMicroBuyBot(bot_config)
        
        gas_info = bot.get_current_gas_price()
        gas_costs = bot.calculate_gas_costs()
        eth_price = ETHPriceService.get_eth_price_usd()
        
        funding_gas_per_wallet_eth = gas_costs['funding_gas_eth']
        buy_gas_per_tx_eth = gas_costs['buy_gas_eth']
        
        total_funding_gas_1000_tx_eth = funding_gas_per_wallet_eth * 1000
        total_buy_gas_1000_tx_eth = buy_gas_per_tx_eth * 1000
        total_gas_1000_tx_eth = total_funding_gas_1000_tx_eth + total_buy_gas_1000_tx_eth
        
        buy_amount_per_tx_eth = bot.BUY_AMOUNT_ETH
        total_buy_amount_1000_tx_eth = buy_amount_per_tx_eth * 1000
        
        total_micro_buy_cost_1000_tx_eth = total_gas_1000_tx_eth + total_buy_amount_1000_tx_eth
        
        return {
            "success": True,
            "gas_info": {
                "gas_price_gwei": gas_info['gas_price_gwei'],
                "source": gas_info.get('source', 'unknown'),
                "success": gas_info.get('success', False)
            },
            "cost_breakdown_per_tx": {
                "funding_gas_eth": funding_gas_per_wallet_eth,
                "buy_gas_eth": buy_gas_per_tx_eth,
                "total_gas_eth": funding_gas_per_wallet_eth + buy_gas_per_tx_eth,
                "buy_amount_eth": buy_amount_per_tx_eth,
                "total_cost_eth": funding_gas_per_wallet_eth + buy_gas_per_tx_eth + buy_amount_per_tx_eth
            },
            "cost_1000_tx": {
                "total_gas_eth": total_gas_1000_tx_eth,
                "total_gas_usd": total_gas_1000_tx_eth * eth_price,
                "total_buy_amount_eth": total_buy_amount_1000_tx_eth,
                "total_buy_amount_usd": total_buy_amount_1000_tx_eth * eth_price,
                "total_micro_buy_cost_eth": total_micro_buy_cost_1000_tx_eth,
                "total_micro_buy_cost_usd": total_micro_buy_cost_1000_tx_eth * eth_price
            },
            "network_info": {
                "eth_price_usd": eth_price,
                "timestamp": datetime.now().isoformat()
            }
        }
    except Exception as e:
        return {"success": False, "error": str(e)}

@app.post("/api/estimate-cost")
async def estimate_cost(
    request: OperationRequest,
    user_info: Dict = Depends(get_current_user),
    password: str = Header(None)
):
    username = user_info["username"]
    
    if not password:
        return {"success": False, "error": "Password required"}
    
    if not user_manager.verify_user(username, password):
        return {"success": False, "error": "Invalid password"}
    
    private_key = user_manager.get_decrypted_private_key(username, password)
    if not private_key:
        return {"success": False, "error": "Please configure wallet first"}
    
    try:
        settings = user_manager.get_user_settings(username)
        if not settings.get('node'):
            return {"success": False, "error": "RPC node not configured"}
        
        bot_config = BotConfig(
            rpc_url=settings.get('node'),
            master_private_key=private_key
        )
        bot = ParallelMicroBuyBot(bot_config)
        
        estimation = bot.estimate_cycles_cost_usd(request.speed, request.num_cycles)
        
        return {"success": True, "estimation": estimation}
    except Exception as e:
        return {"success": False, "error": str(e)}

@app.post("/api/start-operation")
async def start_operation(
    request: OperationRequest,
    background_tasks: BackgroundTasks,
    user_info: Dict = Depends(get_current_user),
    password: str = Header(None)
):
    username = user_info["username"]
    
    if not password:
        return {"success": False, "error": "Password required"}
    
    if not user_manager.verify_user(username, password):
        return {"success": False, "error": "Invalid password"}
    
    private_key = user_manager.get_decrypted_private_key(username, password)
    if not private_key:
        return {"success": False, "error": "Please configure wallet first"}
    
    settings = user_manager.get_user_settings(username)
    if not settings.get('node'):
        return {"success": False, "error": "RPC node not configured"}
    
    operation_id = str(uuid.uuid4())
    
    try:
        bot_config = BotConfig(
            rpc_url=settings.get('node'),
            master_private_key=private_key
        )
        
        bot = ParallelMicroBuyBot(bot_config)
        
        micro_config = MicroBuyConfig(
            token_address=request.token_address,
            speed=request.speed,
            num_cycles=request.num_cycles
        )
        
        active_operations[operation_id] = {
            "user_id": username,
            "username": username,
            "bot": bot,
            "config": micro_config,
            "start_time": datetime.now().isoformat(),
            "status": "running",
            "progress": {
                "cycles_completed": 0,
                "total_cycles": request.num_cycles,
                "successful_buys": 0,
                "total_buys": 0
            }
        }
        
        user_manager.add_user_log(username, f"🚀 Operation started: {operation_id}")
        
        background_tasks.add_task(run_operation, operation_id, username)
        
        return {"success": True, "operation_id": operation_id}
    except Exception as e:
        user_manager.add_user_log(username, f"Failed to start operation: {str(e)}")
        return {"success": False, "error": str(e)}

@app.post("/api/stop-operation/{operation_id}")
async def stop_operation(
    operation_id: str,
    user_info: Dict = Depends(get_current_user)
):
    username = user_info["username"]
    
    if operation_id not in active_operations:
        return {"success": False, "error": "Operation not found"}
    
    operation = active_operations[operation_id]
    if operation["user_id"] != username:
        return {"success": False, "error": "Operation not owned by user"}
    
    operation["bot"].stop_operation()
    operation["status"] = "stopped"
    
    user_manager.add_user_log(username, f"🛑 Operation {operation_id} stopped by user")
    
    return {"success": True, "message": "Operation stopped successfully"}

@app.get("/api/operations")
async def get_operations(user_info: Dict = Depends(get_current_user)):
    username = user_info["username"]
    user_operations = {
        op_id: {
            "user_id": op["user_id"],
            "username": op["username"], 
            "config": {
                "token_address": op["config"].token_address,
                "speed": op["config"].speed,
                "num_cycles": op["config"].num_cycles
            },
            "start_time": op["start_time"],
            "status": op["status"],
            "progress": op["progress"]
        } for op_id, op in active_operations.items() 
        if op["user_id"] == username
    }
    return {"success": True, "operations": user_operations}

@app.get("/api/user-logs")
async def get_user_logs(user_info: Dict = Depends(get_current_user)):
    username = user_info["username"]
    logs = user_manager.get_user_logs(username)
    return {"success": True, "logs": logs}

@app.get("/api/download-logs")
async def download_logs(user_info: Dict = Depends(get_current_user)):
    username = user_info["username"]
    logs = user_manager.get_user_logs(username)
    
    log_content = f"Micro Buy Bot Logs - User: {username}\n"
    log_content += f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
    log_content += "=" * 50 + "\n\n"
    
    for log in logs:
        timestamp = datetime.fromisoformat(log['timestamp']).strftime('%Y-%m-%d %H:%M:%S')
        log_content += f"[{timestamp}] {log['message']}\n"
    
    log_file = io.BytesIO(log_content.encode('utf-8'))
    
    return Response(
        content=log_file.getvalue(),
        media_type='text/plain',
        headers={
            'Content-Disposition': f'attachment; filename="micro_buy_bot_logs_{username}_{datetime.now().strftime("%Y%m%d_%H%M%S")}.txt"'
        }
    )

async def cleanup_completed_operations():
    """Clean up completed operations after 1 hour"""
    while True:
        try:
            current_time = time.time()
            operations_to_remove = []
            
            for op_id, op in active_operations.items():
                if op["status"] in ["completed", "stopped", "failed"]:
                    start_time = datetime.fromisoformat(op["start_time"]).timestamp()
                    if current_time - start_time > 3600:
                        operations_to_remove.append(op_id)
            
            for op_id in operations_to_remove:
                del active_operations[op_id]
                logger.info(f"Cleaned up old operation: {op_id}")
                
        except Exception as e:
            logger.error(f"Error in cleanup: {e}")
        
        await asyncio.sleep(300)

async def run_operation(operation_id: str, username: str):
    """Run operation with proper status updates"""
    try:
        operation = active_operations[operation_id]
        bot = operation["bot"]
        config = operation["config"]
        
        await bot.start_operation(config, operation_id, username)
        
        if operation_id in active_operations and active_operations[operation_id]["status"] == "running":
            active_operations[operation_id]["status"] = "completed"
            
    except Exception as e:
        logger.error(f"Operation {operation_id} failed: {e}")
        if operation_id in active_operations:
            active_operations[operation_id]["status"] = "failed"
            active_operations[operation_id]["error"] = str(e)
        user_manager.add_user_log(username, f"Operation failed: {str(e)}")

# ==================== WEBSOCKET ROUTES ====================
@app.websocket("/ws/{session_id}/logs")
async def websocket_log_endpoint(websocket: WebSocket, session_id: str):
    await websocket.accept()
    
    user_info = user_manager.validate_session(session_id)
    if not user_info:
        await websocket.close()
        return
    
    username = user_info["username"]
    
    if username not in log_consumers:
        log_consumers[username] = []
    
    log_consumers[username].append(websocket)
    
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        if username in log_consumers:
            log_consumers[username] = [ws for ws in log_consumers[username] if ws != websocket]

# ==================== STATIC FILES ====================
# Create frontend directory if it doesn't exist
frontend_dir = "frontend"
if not os.path.exists(frontend_dir):
    os.makedirs(frontend_dir)

# Serve frontend
app.mount("/", StaticFiles(directory=frontend_dir, html=True), name="frontend")

@app.get("/")
async def read_index():
    return FileResponse(os.path.join(frontend_dir, 'index.html'))

# ==================== START SERVER ====================
def start():
    """Start the server"""
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)

if __name__ == "__main__":
    start()