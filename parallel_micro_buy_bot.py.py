# app.py - Complete Parallel Micro Buy Bot with Admin & User Management
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, BackgroundTasks, HTTPException, Depends
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

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('parallel_micro_buy.log')
    ]
)
logger = logging.getLogger(__name__)

# Bot Configuration Classes
@dataclass
class BotConfig:
    """Configuration for the Parallel Micro Buy Bot"""
    rpc_url: str = "https://base-mainnet.g.alchemy.com/v2/tmYsnJzVHFkg-7jqyLA0G5jbGe4PSsYR"
    master_private_key: str = ""

@dataclass
class MicroBuyConfig:
    """Configuration for micro buy operations"""
    token_address: str
    speed: str = "medium"
    num_cycles: int = 10

# User Management Classes
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

class UserManager:
    def __init__(self):
        self.users_file = "users.json"
        self.sessions_file = "sessions.json"
        self.load_users()
        self.load_sessions()
    
    def load_users(self):
        """Load users from JSON file"""
        try:
            if os.path.exists(self.users_file):
                with open(self.users_file, 'r') as f:
                    self.users = json.load(f)
            else:
                # Create default admin user
                self.users = {
                    "admin": {
                        "password": self.hash_password("admin123"),
                        "role": "admin",
                        "created_at": datetime.now().isoformat(),
                        "is_active": True
                    }
                }
                self.save_users()
                logger.info("Default admin user created: admin/admin123")
        except Exception as e:
            logger.error(f"Error loading users: {e}")
            self.users = {}
    
    def load_sessions(self):
        """Load sessions from JSON file"""
        try:
            if os.path.exists(self.sessions_file):
                with open(self.sessions_file, 'r') as f:
                    self.sessions = json.load(f)
            else:
                self.sessions = {}
        except Exception as e:
            logger.error(f"Error loading sessions: {e}")
            self.sessions = {}
    
    def save_users(self):
        """Save users to JSON file"""
        try:
            with open(self.users_file, 'w') as f:
                json.dump(self.users, f, indent=2)
        except Exception as e:
            logger.error(f"Error saving users: {e}")
    
    def save_sessions(self):
        """Save sessions to JSON file"""
        try:
            with open(self.sessions_file, 'w') as f:
                json.dump(self.sessions, f, indent=2)
        except Exception as e:
            logger.error(f"Error saving sessions: {e}")
    
    def hash_password(self, password: str) -> str:
        """Hash password using SHA-256"""
        return hashlib.sha256(password.encode()).hexdigest()
    
    def verify_user(self, username: str, password: str) -> bool:
        """Verify user credentials"""
        if username in self.users and self.users[username].get("is_active", True):
            hashed_password = self.hash_password(password)
            return self.users[username]["password"] == hashed_password
        return False
    
    def create_user(self, username: str, password: str, role: str = "user") -> tuple:
        """Create a new user"""
        if username in self.users:
            return False, "User already exists"
        
        if role not in ["admin", "user"]:
            return False, "Invalid role. Must be 'admin' or 'user'"
        
        self.users[username] = {
            "password": self.hash_password(password),
            "role": role,
            "created_at": datetime.now().isoformat(),
            "is_active": True,
            "created_by": "system"
        }
        self.save_users()
        return True, f"User '{username}' created successfully with role '{role}'"
    
    def create_session(self, username: str) -> str:
        """Create a new session for user"""
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
        """Validate session and return user info"""
        if session_id in self.sessions:
            # Update last activity
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
        """Logout user by removing session"""
        if session_id in self.sessions:
            del self.sessions[session_id]
            self.save_sessions()
    
    def change_password(self, username: str, old_password: str, new_password: str) -> bool:
        """Change user password"""
        if username in self.users and self.verify_user(username, old_password):
            self.users[username]["password"] = self.hash_password(new_password)
            self.save_users()
            return True
        return False
    
    def get_all_users(self) -> List[Dict]:
        """Get all users (admin only)"""
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
        """Delete a user (admin only)"""
        if username in self.users and username != "admin":  # Prevent deleting admin
            del self.users[username]
            self.save_users()
            
            # Also remove any active sessions for this user
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
        """Toggle user active/inactive status (admin only)"""
        if username in self.users and username != "admin":  # Prevent deactivating admin
            current_status = self.users[username].get("is_active", True)
            self.users[username]["is_active"] = not current_status
            self.save_users()
            return True
        return False

# Initialize user manager
user_manager = UserManager()

# Dependency to get current user from session
async def get_current_user(session_id: str):
    if not session_id:
        raise HTTPException(status_code=401, detail="Session ID required")
    
    user_info = user_manager.validate_session(session_id)
    if not user_info:
        raise HTTPException(status_code=401, detail="Invalid or expired session")
    
    return user_info

# Dependency to check if user is admin
async def require_admin(user_info: Dict = Depends(get_current_user)):
    if user_info["role"] != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    return user_info

# Main Bot Class
class ParallelMicroBuyBot:
    """
    Parallel Micro Buy Bot with proper nonce management
    """
    
    UNISWAP_V2_ROUTER = "0x4752ba5DBc23f44D87826276BF6Fd6b1C372aD24"
    WETH_ADDRESS = "0x4200000000000000000000000000000000000006"
    
    # Fixed buy amount: 10 Wei (0.00000000000000001 ETH)
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
        """Get current ETH price in USD from CoinGecko"""
        try:
            response = requests.get(
                "https://api.coingecko.com/api/v3/simple/price?ids=ethereum&vs_currencies=usd",
                timeout=10
            )
            data = response.json()
            return data['ethereum']['usd']
        except:
            return 2500.0

    def get_current_gas_price(self) -> Dict:
        """Get current gas prices from network"""
        try:
            gas_price = self.w3.eth.gas_price
            gas_price_gwei = float(self.w3.from_wei(gas_price, 'gwei'))
            
            return {
                'gas_price_wei': gas_price,
                'gas_price_gwei': gas_price_gwei,
                'success': True
            }
        except Exception as e:
            logger.error(f"Failed to get gas price: {e}")
            return {
                'gas_price_wei': self.w3.to_wei(10, 'gwei'),
                'gas_price_gwei': 10.0,
                'success': False
            }

    def calculate_gas_costs(self) -> Dict:
        """Calculate gas costs for funding and buying"""
        gas_info = self.get_current_gas_price()
        gas_price_wei = gas_info['gas_price_wei']
        
        FUNDING_GAS_LIMIT = 21000
        BUY_GAS_LIMIT = 200000
        
        funding_gas_eth = float(self.w3.from_wei(FUNDING_GAS_LIMIT * gas_price_wei, 'ether'))
        buy_gas_eth = float(self.w3.from_wei(BUY_GAS_LIMIT * gas_price_wei, 'ether'))
        
        return {
            'funding_gas_eth': funding_gas_eth,
            'buy_gas_eth': buy_gas_eth,
            'total_gas_per_wallet_eth': funding_gas_eth + buy_gas_eth,
            'gas_price_gwei': gas_info['gas_price_gwei'],
            'success': True
        }

    def estimate_cycles_cost_usd(self, speed: str, num_cycles: int) -> Dict:
        """Estimate USD cost for specified number of cycles"""
        speed_config = self.SPEED_CONFIGS[speed]
        wallets_per_cycle = speed_config['wallets_per_cycle']
        
        total_wallets_needed = num_cycles * wallets_per_cycle
        total_transactions = num_cycles * wallets_per_cycle
        
        gas_costs = self.calculate_gas_costs()
        eth_price_usd = self.get_eth_price_usd()
        
        funding_gas_per_wallet_eth = gas_costs['funding_gas_eth']
        buy_gas_per_wallet_eth = gas_costs['buy_gas_eth']
        total_gas_per_wallet_eth = gas_costs['total_gas_per_wallet_eth']
        
        total_funding_gas_eth = funding_gas_per_wallet_eth * total_wallets_needed
        total_buy_gas_eth = buy_gas_per_wallet_eth * total_transactions
        total_gas_eth = total_funding_gas_eth + total_buy_gas_eth
        
        total_buy_eth = self.BUY_AMOUNT_ETH * total_transactions
        
        funding_per_wallet_eth = funding_gas_per_wallet_eth + buy_gas_per_wallet_eth
        
        total_funding_eth = funding_per_wallet_eth * total_wallets_needed
        total_cost_eth = total_funding_eth + total_gas_eth
        
        total_cost_usd = total_cost_eth * eth_price_usd
        total_gas_usd = total_gas_eth * eth_price_usd
        total_funding_usd = total_funding_eth * eth_price_usd
        
        return {
            'estimation_for': f"{num_cycles} cycles at {speed} speed",
            'network_conditions': {
                'eth_price_usd': eth_price_usd,
                'gas_price_gwei': gas_costs['gas_price_gwei'],
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
            'per_wallet_distribution': {
                'funding_amount_eth': funding_per_wallet_eth,
                'buy_amount_eth': self.BUY_AMOUNT_ETH,
                'gas_cost_eth': total_gas_per_wallet_eth,
                'leftover_eth': funding_per_wallet_eth - self.BUY_AMOUNT_ETH - buy_gas_per_wallet_eth
            },
            'requirements': {
                'minimum_eth_required': total_cost_eth,
                'current_balance_eth': self.get_master_balance_eth(),
                'minimum_usd_required': total_cost_usd
            }
        }

    def get_master_balance_eth(self) -> float:
        """Get master wallet balance in ETH"""
        balance_wei = self.w3.eth.get_balance(self.master_account.address)
        return float(self.w3.from_wei(balance_wei, 'ether'))

    def create_wallet(self) -> Dict:
        """Create a new Ethereum wallet"""
        account = Account.create()
        return {
            'address': account.address,
            'private_key': account.key.hex(),
            'balance_eth': 0.0,
            'created_at': time.time()
        }

    def generate_wallets(self, count: int) -> List[Dict]:
        """Generate multiple wallets"""
        wallets = []
        for i in range(count):
            wallet = self.create_wallet()
            wallets.append(wallet)
            self.generated_wallets.append(wallet)
        
        logger.info(f"Generated {count} new wallets")
        return wallets

    def calculate_funding_amount(self) -> float:
        """Calculate how much ETH to send to each wallet"""
        gas_costs = self.calculate_gas_costs()
        
        funding_amount = self.BUY_AMOUNT_ETH + gas_costs['buy_gas_eth']
        funding_amount *= 1.1
        
        return funding_amount

    async def fund_wallet_with_nonce(self, wallet_address: str, amount_eth: float, nonce: int) -> bool:
        """Fund a wallet with specific nonce"""
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
        """Execute all wallet funding in parallel with proper nonce management"""
        # Get current nonce and reserve a range
        base_nonce = self.w3.eth.get_transaction_count(self.master_account.address)
        logger.info(f"Base nonce: {base_nonce}, funding {len(wallets)} wallets")
        
        funding_tasks = []
        
        # Create funding tasks with sequential nonces
        for i, wallet in enumerate(wallets):
            nonce = base_nonce + i
            task = self.fund_wallet_with_nonce(wallet['address'], funding_amount, nonce)
            funding_tasks.append((task, wallet, nonce))
        
        logger.info(f"Executing {len(funding_tasks)} parallel funding transactions with nonces {base_nonce} to {base_nonce + len(wallets) - 1}")
        
        # Execute all funding transactions simultaneously
        results = []
        for task, wallet, nonce in funding_tasks:
            try:
                result = await task
                results.append((result, wallet, nonce))
            except Exception as e:
                results.append((False, wallet, nonce))
                logger.error(f"Funding task failed for nonce {nonce}: {e}")
        
        # Process results
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
        """Execute a micro buy of exactly 10 Wei"""
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
        """Execute all micro buys in parallel for a cycle"""
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
        """Execute a single micro buy cycle with parallel funding and buying"""
        if not self.is_running:
            return {'success': False, 'error': 'Operation stopped by user'}
            
        speed_config = self.SPEED_CONFIGS[config.speed]
        wallet_count = speed_config['wallets_per_cycle']
        
        funding_amount = self.calculate_funding_amount()
        
        logger.info(f"Starting FULL PARALLEL micro buy cycle {cycle_number}: {wallet_count} wallets")
        logger.info(f"Funding each wallet with {funding_amount:.8f} ETH")
        logger.info(f"All {wallet_count} funding transactions will execute simultaneously with proper nonces")
        logger.info(f"All {wallet_count} micro buys will execute simultaneously")
        
        # Generate wallets
        wallets = self.generate_wallets(wallet_count)
        
        # Execute ALL funding transactions in parallel with proper nonce management
        logger.info(f"EXECUTING {wallet_count} PARALLEL FUNDING TRANSACTIONS WITH NONCE MANAGEMENT...")
        funding_start_time = time.time()
        
        funding_results = await self.execute_parallel_funding_with_nonces(wallets, funding_amount)
        funding_time = time.time() - funding_start_time
        
        successful_funding = sum(1 for result in funding_results if result.get('success'))
        logger.info(f"Parallel funding with nonces completed in {funding_time:.2f} seconds: {successful_funding}/{wallet_count} successful")
        
        if successful_funding == 0:
            return {'success': False, 'error': 'All wallet funding failed'}
        
        # Wait for funding to settle
        logger.info("Waiting for funding transactions to confirm...")
        await asyncio.sleep(5)
        
        # Execute ALL micro buys in parallel
        logger.info(f"EXECUTING {successful_funding} PARALLEL MICRO BUYS...")
        buy_start_time = time.time()
        
        buy_results = await self.execute_parallel_micro_buys(wallets, config.token_address)
        buy_time = time.time() - buy_start_time
        
        total_execution_time = funding_time + buy_time
        
        # Count successful buys
        successful_buys = sum(1 for result in buy_results if result.get('success'))
        success_rate = successful_buys / len(buy_results) if buy_results else 0
        
        # Log individual results
        for i, result in enumerate(buy_results):
            if result.get('success'):
                logger.info(f"Wallet {i+1}: Buy successful - {result['hash']}")
            else:
                logger.error(f"Wallet {i+1}: Buy failed - {result.get('error')}")
        
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
        """Stop the current operation"""
        self.is_running = False
        logger.info("Operation stop requested")
        return True

    async def start_operation(self, config: MicroBuyConfig):
        """Start the micro buy operation"""
        self.is_running = True
        self.current_operation = config
        
        try:
            for cycle in range(config.num_cycles):
                if not self.is_running:
                    logger.info("Operation stopped by user")
                    break
                    
                cycle_result = await self.execute_micro_buy_cycle(config, cycle + 1)
                
                if not cycle_result.get('success'):
                    logger.error(f"Cycle {cycle + 1} failed: {cycle_result.get('error')}")
                
                # Wait between cycles if not the last cycle and operation is still running
                if cycle < config.num_cycles - 1 and self.is_running:
                    await asyncio.sleep(self.SPEED_CONFIGS[config.speed]['cycle_interval'])
            
            if self.is_running:
                logger.info("Operation completed successfully")
            else:
                logger.info("Operation was stopped")
                
        except Exception as e:
            logger.error(f"Operation failed: {e}")
        finally:
            self.is_running = False
            self.current_operation = None

# FastAPI Application
app = FastAPI(title="Parallel Micro Buy Bot API")

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Store active operations and user settings
active_operations: Dict[str, Dict] = {}
user_settings: Dict[str, Dict] = {}
log_consumers: Dict[str, List[WebSocket]] = {}

# Pydantic models for requests
class BotSettings(BaseModel):
    pk: str
    node: str = "https://base-mainnet.g.alchemy.com/v2/tmYsnJzVHFkg-7jqyLA0G5jbGe4PSsYR"
    token_ca: str = ""
    speed: str = "medium"
    num_cycles: int = 10
    buy_amount_wei: int = 10

class OperationRequest(BaseModel):
    token_address: str
    speed: str = "medium"
    num_cycles: int = 10

class LogHandler(logging.Handler):
    def __init__(self, user_id: str):
        super().__init__()
        self.user_id = user_id
        self.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))

    def emit(self, record):
        log_entry = self.format(record)
        asyncio.create_task(broadcast_log(self.user_id, log_entry))

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

# Authentication Routes
@app.post("/api/login")
async def login(login_data: UserLogin):
    if user_manager.verify_user(login_data.username, login_data.password):
        session_id = user_manager.create_session(login_data.username)
        
        # Initialize user settings if not exists
        if login_data.username not in user_settings:
            user_settings[login_data.username] = {}
        
        # Initialize log handler for this user
        logger = logging.getLogger()
        log_handler = LogHandler(session_id)
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

@app.post("/api/logout")
async def logout(session_id: str):
    user_manager.logout(session_id)
    return {"success": True, "message": "Logout successful"}

@app.post("/api/change-password")
async def change_password(change_data: ChangePassword, user_info: Dict = Depends(get_current_user)):
    username = user_info["username"]
    if user_manager.change_password(username, change_data.old_password, change_data.new_password):
        return {"success": True, "message": "Password changed successfully"}
    else:
        return {"success": False, "error": "Invalid old password"}

# Admin-only Routes
@app.post("/api/admin/create-user")
async def create_user(user_data: UserCreate, admin_info: Dict = Depends(require_admin)):
    success, message = user_manager.create_user(user_data.username, user_data.password, user_data.role)
    return {"success": success, "message": message}

@app.get("/api/admin/users")
async def get_all_users(admin_info: Dict = Depends(require_admin)):
    users = user_manager.get_all_users()
    return {"success": True, "users": users}

@app.delete("/api/admin/users/{username}")
async def delete_user(username: str, admin_info: Dict = Depends(require_admin)):
    if user_manager.delete_user(username):
        return {"success": True, "message": f"User '{username}' deleted successfully"}
    else:
        return {"success": False, "error": "Failed to delete user"}

@app.post("/api/admin/users/{username}/toggle")
async def toggle_user_status(username: str, admin_info: Dict = Depends(require_admin)):
    if user_manager.toggle_user_status(username):
        return {"success": True, "message": f"User status toggled successfully"}
    else:
        return {"success": False, "error": "Failed to toggle user status"}

# User-specific Routes
@app.post("/api/{session_id}/settings")
async def save_settings(session_id: str, settings: BotSettings, user_info: Dict = Depends(get_current_user)):
    username = user_info["username"]
    user_settings[username] = settings.dict()
    return {"success": True, "message": "Settings saved"}

@app.get("/api/{session_id}/settings")
async def get_settings(session_id: str, user_info: Dict = Depends(get_current_user)):
    username = user_info["username"]
    settings = user_settings.get(username, {})
    return {"success": True, "settings": settings}

@app.get("/api/{session_id}/wallet-info")
async def get_wallet_info(session_id: str, user_info: Dict = Depends(get_current_user)):
    username = user_info["username"]
    settings = user_settings.get(username, {})
    
    if not settings or 'pk' not in settings or not settings['pk']:
        return {"success": False, "error": "No wallet configured"}
    
    try:
        bot_config = BotConfig(
            rpc_url=settings.get('node', 'https://base-mainnet.g.alchemy.com/v2/tmYsnJzVHFkg-7jqyLA0G5jbGe4PSsYR'),
            master_private_key=settings['pk']
        )
        bot = ParallelMicroBuyBot(bot_config)
        
        balance = bot.get_master_balance_eth()
        eth_price = bot.get_eth_price_usd()
        
        return {
            "success": True,
            "wallet_address": bot.master_account.address,
            "balance_eth": balance,
            "balance_usd": balance * eth_price
        }
    except Exception as e:
        return {"success": False, "error": str(e)}

@app.post("/api/{session_id}/estimate-cost")
async def estimate_cost(session_id: str, request: OperationRequest, user_info: Dict = Depends(get_current_user)):
    username = user_info["username"]
    settings = user_settings.get(username, {})
    
    if not settings or 'pk' not in settings:
        return {"success": False, "error": "Please configure wallet first"}
    
    try:
        bot_config = BotConfig(
            rpc_url=settings.get('node', 'https://base-mainnet.g.alchemy.com/v2/tmYsnJzVHFkg-7jqyLA0G5jbGe4PSsYR'),
            master_private_key=settings['pk']
        )
        bot = ParallelMicroBuyBot(bot_config)
        
        estimation = bot.estimate_cycles_cost_usd(request.speed, request.num_cycles)
        
        return {"success": True, "estimation": estimation}
    except Exception as e:
        return {"success": False, "error": str(e)}

@app.post("/api/{session_id}/start-operation")
async def start_operation(session_id: str, request: OperationRequest, background_tasks: BackgroundTasks, user_info: Dict = Depends(get_current_user)):
    username = user_info["username"]
    settings = user_settings.get(username, {})
    
    if not settings or 'pk' not in settings:
        return {"success": False, "error": "Please configure wallet first"}
    
    operation_id = str(uuid.uuid4())
    
    try:
        bot_config = BotConfig(
            rpc_url=settings.get('node', 'https://base-mainnet.g.alchemy.com/v2/tmYsnJzVHFkg-7jqyLA0G5jbGe4PSsYR'),
            master_private_key=settings['pk']
        )
        
        bot = ParallelMicroBuyBot(bot_config)
        
        micro_config = MicroBuyConfig(
            token_address=request.token_address,
            speed=request.speed,
            num_cycles=request.num_cycles
        )
        
        active_operations[operation_id] = {
            "user_id": session_id,
            "username": username,
            "bot": bot,
            "config": micro_config,
            "start_time": datetime.now(),
            "status": "running",
            "progress": {
                "cycles_completed": 0,
                "total_cycles": request.num_cycles,
                "successful_buys": 0,
                "total_buys": 0
            }
        }
        
        # Start operation in background
        background_tasks.add_task(run_operation, operation_id)
        
        return {"success": True, "operation_id": operation_id}
    except Exception as e:
        return {"success": False, "error": str(e)}

@app.post("/api/{session_id}/stop-operation/{operation_id}")
async def stop_operation(session_id: str, operation_id: str, user_info: Dict = Depends(get_current_user)):
    """Stop an operation immediately"""
    if operation_id not in active_operations:
        return {"success": False, "error": "Operation not found"}
    
    operation = active_operations[operation_id]
    if operation["user_id"] != session_id:
        return {"success": False, "error": "Operation not owned by user"}
    
    # Stop the bot operation
    operation["bot"].stop_operation()
    operation["status"] = "stopped"
    
    return {"success": True, "message": "Operation stopped successfully"}

@app.post("/api/{session_id}/cancel-operation/{operation_id}")
async def cancel_operation(session_id: str, operation_id: str, user_info: Dict = Depends(get_current_user)):
    """Cancel operation (alias for stop)"""
    return await stop_operation(session_id, operation_id, user_info)

@app.get("/api/{session_id}/operations")
async def get_operations(session_id: str, user_info: Dict = Depends(get_current_user)):
    user_operations = {
        op_id: op for op_id, op in active_operations.items() 
        if op["user_id"] == session_id
    }
    return {"success": True, "operations": user_operations}

async def run_operation(operation_id: str):
    try:
        operation = active_operations[operation_id]
        bot = operation["bot"]
        config = operation["config"]
        
        # Run the actual bot operation
        await bot.start_operation(config)
        
        # Update final status
        if bot.is_running:
            operation["status"] = "completed"
            await broadcast_log(operation["user_id"], "Operation completed successfully")
        else:
            operation["status"] = "stopped"
            await broadcast_log(operation["user_id"], "Operation was stopped")
        
    except Exception as e:
        operation["status"] = "failed"
        await broadcast_log(operation["user_id"], f"Operation failed: {str(e)}")

@app.websocket("/ws/{session_id}/logs")
async def websocket_log_endpoint(websocket: WebSocket, session_id: str):
    await websocket.accept()
    
    # Validate session
    user_info = user_manager.validate_session(session_id)
    if not user_info:
        await websocket.close()
        return
    
    if session_id not in log_consumers:
        log_consumers[session_id] = []
    
    log_consumers[session_id].append(websocket)
    
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        if session_id in log_consumers:
            log_consumers[session_id] = [ws for ws in log_consumers[session_id] if ws != websocket]

# Create frontend directory if it doesn't exist
frontend_dir = "frontend"
if not os.path.exists(frontend_dir):
    os.makedirs(frontend_dir)

# Serve frontend
app.mount("/", StaticFiles(directory=frontend_dir, html=True), name="frontend")

@app.get("/")
async def read_index():
    return FileResponse('frontend/index.html')

def start():
    """Start the server"""
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

if __name__ == "__main__":
    start()