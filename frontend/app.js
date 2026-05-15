// app.js - Complete Fixed Version with Proper Session Handling
class ParallelMicroBuyBotApp {
    constructor() {
        this.sessionId = null;
        this.username = null;
        this.userRole = null;
        this.ws = null;
        this.operations = new Map();
        this.userPassword = null;
        this.pollingInterval = null;
        this.isSessionValid = true;
        this.failedRequests = 0;

        this.initializeEventListeners();
        this.checkExistingSession();
    }

    initializeEventListeners() {
        // Login form
        const loginForm = document.getElementById('loginForm');
        if (loginForm) {
            loginForm.addEventListener('submit', (e) => {
                e.preventDefault();
                this.handleLogin(e);
            });
        }

        // Logout
        const logoutBtn = document.getElementById('logoutBtn');
        if (logoutBtn) {
            logoutBtn.addEventListener('click', () => this.handleLogout());
        }

        // Settings
        const settingsBtn = document.getElementById('settingsBtn');
        const closeSettingsBtn = document.getElementById('closeSettingsBtn');
        const cancelSettingsBtn = document.getElementById('cancelSettingsBtn');
        const settingsForm = document.getElementById('settingsForm');
        
        if (settingsBtn) settingsBtn.addEventListener('click', () => this.openSettings());
        if (closeSettingsBtn) closeSettingsBtn.addEventListener('click', () => this.closeSettings());
        if (cancelSettingsBtn) cancelSettingsBtn.addEventListener('click', () => this.closeSettings());
        if (settingsForm) settingsForm.addEventListener('submit', (e) => this.saveSettings(e));

        // Operations
        const operationForm = document.getElementById('operationForm');
        const estimateCostBtn = document.getElementById('estimateCostBtn');
        
        if (operationForm) operationForm.addEventListener('submit', (e) => this.startOperation(e));
        if (estimateCostBtn) estimateCostBtn.addEventListener('click', () => this.estimateCost());

        // Logs
        const clearLogsBtn = document.getElementById('clearLogsBtn');
        const downloadLogsBtn = document.getElementById('downloadLogsBtn');
        
        if (clearLogsBtn) clearLogsBtn.addEventListener('click', () => this.clearLogs());
        if (downloadLogsBtn) downloadLogsBtn.addEventListener('click', () => this.downloadLogs());

        // Node validation
        const validateNodeBtn = document.getElementById('validateNodeBtn');
        if (validateNodeBtn) validateNodeBtn.addEventListener('click', () => this.validateNode());

        // Cost modal
        const closeCostBtn = document.getElementById('closeCostBtn');
        if (closeCostBtn) closeCostBtn.addEventListener('click', () => this.closeCostModal());

        // Close modals on outside click
        document.addEventListener('click', (e) => {
            if (e.target.classList && e.target.classList.contains('modal')) {
                this.closeSettings();
                this.closeCostModal();
                this.closeManageUsersModal();
                this.closeCreateUserModal();
                this.closeChangePasswordModal();
            }
        });

        // Initialize modal events after a short delay
        setTimeout(() => this.initializeModalEvents(), 100);
    }

    initializeModalEvents() {
        // Manage Users Modal
        const closeManageUsersBtn = document.getElementById('closeManageUsersBtn');
        const closeManageUsersBtn2 = document.getElementById('closeManageUsersBtn2');
        if (closeManageUsersBtn) closeManageUsersBtn.addEventListener('click', () => this.closeManageUsersModal());
        if (closeManageUsersBtn2) closeManageUsersBtn2.addEventListener('click', () => this.closeManageUsersModal());

        // Create User Modal
        const closeCreateUserBtn = document.getElementById('closeCreateUserBtn');
        const closeCreateUserBtn2 = document.getElementById('closeCreateUserBtn2');
        const createUserForm = document.getElementById('createUserForm');
        if (closeCreateUserBtn) closeCreateUserBtn.addEventListener('click', () => this.closeCreateUserModal());
        if (closeCreateUserBtn2) closeCreateUserBtn2.addEventListener('click', () => this.closeCreateUserModal());
        if (createUserForm) createUserForm.addEventListener('submit', (e) => this.handleCreateUser(e));

        // Change Password Modal
        const closeChangePasswordBtn = document.getElementById('closeChangePasswordBtn');
        const closeChangePasswordBtn2 = document.getElementById('closeChangePasswordBtn2');
        const changePasswordForm = document.getElementById('changePasswordForm');
        if (closeChangePasswordBtn) closeChangePasswordBtn.addEventListener('click', () => this.closeChangePasswordModal());
        if (closeChangePasswordBtn2) closeChangePasswordBtn2.addEventListener('click', () => this.closeChangePasswordModal());
        if (changePasswordForm) changePasswordForm.addEventListener('submit', (e) => this.handleChangePassword(e));
    }

    async checkExistingSession() {
        const savedSessionId = localStorage.getItem('sessionId');
        const savedUsername = localStorage.getItem('username');
        const savedUserRole = localStorage.getItem('userRole');
        const savedPassword = localStorage.getItem('userPassword');

        if (savedSessionId && savedUsername && savedUserRole) {
            this.sessionId = savedSessionId;
            this.username = savedUsername;
            this.userRole = savedUserRole;
            this.userPassword = savedPassword;
            
            try {
                // Test the session with a lightweight API call
                const response = await fetch('/api/operations', {
                    headers: { 'X-Session-ID': this.sessionId }
                });
                
                if (response.status === 401) {
                    throw new Error('Session expired');
                }
                
                if (response.ok) {
                    this.showAppScreen();
                    return;
                }
            } catch (error) {
                console.log('Session expired:', error);
                this.clearSession();
            }
        }
        
        this.showLoginScreen();
    }

    clearSession() {
        localStorage.removeItem('sessionId');
        localStorage.removeItem('username');
        localStorage.removeItem('userRole');
        localStorage.removeItem('userPassword');
        this.sessionId = null;
        this.username = null;
        this.userRole = null;
        this.userPassword = null;
        
        if (this.pollingInterval) {
            clearInterval(this.pollingInterval);
            this.pollingInterval = null;
        }
        
        if (this.ws) {
            this.ws.close();
            this.ws = null;
        }
    }

    showLoginScreen() {
        const loginScreen = document.getElementById('loginScreen');
        const appScreen = document.getElementById('appScreen');
        const loginError = document.getElementById('loginError');
        
        if (loginScreen) loginScreen.classList.add('active');
        if (appScreen) appScreen.classList.remove('active');
        if (loginError) loginError.style.display = 'none';
    }

    showAppScreen() {
        const loginScreen = document.getElementById('loginScreen');
        const appScreen = document.getElementById('appScreen');
        
        if (loginScreen) loginScreen.classList.remove('active');
        if (appScreen) appScreen.classList.add('active');

        const usernameDisplay = document.getElementById('usernameDisplay');
        const userRoleSpan = document.getElementById('userRole');
        
        if (usernameDisplay) usernameDisplay.textContent = this.username;
        if (userRoleSpan) {
            userRoleSpan.textContent = this.userRole.toUpperCase();
            userRoleSpan.className = `user-role role-${this.userRole}`;
        }

        this.showAdminPanel();
        this.loadWalletInfo();
        this.loadNetworkInfo();
        this.loadSettings();
        this.connectWebSocket();
        this.startOperationPolling();

        if (this.userRole === 'admin') {
            this.loadAdminStats();
            setInterval(() => this.loadAdminStats(), 10000);
        }
    }

    showAdminPanel() {
        const adminPanel = document.getElementById('adminPanel');
        if (!adminPanel) return;

        if (this.userRole === 'admin') {
            adminPanel.style.display = 'block';
            const adminUsername = document.getElementById('adminUsername');
            if (adminUsername) adminUsername.textContent = this.username;
            
            const adminControlsSection = document.getElementById('adminControlsSection');
            if (adminControlsSection) {
                adminControlsSection.innerHTML = `
                    <h3>👑 Admin Controls</h3>
                    <div style="color: #28a745; margin-bottom: 10px; font-size: 14px;">
                        ✅ Logged in as: ${this.username} (ADMIN)
                    </div>
                    <div style="display: flex; gap: 10px; margin-top: 10px; flex-wrap: wrap; margin-bottom: 20px;">
                        <button onclick="app.openManageUsersModal()" class="btn btn-primary">👥 Manage Users</button>
                        <button onclick="app.openCreateUserModal()" class="btn btn-success">➕ Create User</button>
                        <button onclick="app.openChangePasswordModal()" class="btn btn-warning">🔒 Change Password</button>
                        <button onclick="app.testAdminAccess()" class="btn btn-secondary">🔍 Test Access</button>
                    </div>
                `;
            }
            
            const adminStatsSection = document.getElementById('adminStatsSection');
            if (adminStatsSection) {
                adminStatsSection.innerHTML = '<h4>📊 Loading Statistics...</h4>';
            }
        } else {
            adminPanel.style.display = 'none';
        }
    }

    async handleLogin(e) {
        e.preventDefault();
        console.log('Login attempt started');

        const username = document.getElementById('username').value;
        const password = document.getElementById('password').value;
        const errorDiv = document.getElementById('loginError');

        if (errorDiv) {
            errorDiv.style.display = 'none';
            errorDiv.textContent = '';
        }

        if (!username || !password) {
            if (errorDiv) {
                errorDiv.textContent = 'Please enter both username and password';
                errorDiv.style.display = 'block';
            }
            return;
        }

        try {
            console.log('Sending login request for user:', username);

            const response = await fetch('/api/login', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({ username, password })
            });

            const data = await response.json();
            console.log('Login response:', data);

            if (data.success) {
                this.sessionId = data.session_id;
                this.username = data.username;
                this.userRole = data.role;
                this.userPassword = password;

                localStorage.setItem('sessionId', this.sessionId);
                localStorage.setItem('username', this.username);
                localStorage.setItem('userRole', this.userRole);
                localStorage.setItem('userPassword', this.userPassword);

                console.log('Login successful, showing app screen');
                this.showAppScreen();
            } else {
                if (errorDiv) {
                    errorDiv.textContent = data.error || 'Login failed';
                    errorDiv.style.display = 'block';
                }
                console.log('Login failed:', data.error);
            }

        } catch (error) {
            console.error('Login error:', error);
            if (errorDiv) {
                errorDiv.textContent = 'Network error: ' + error.message;
                errorDiv.style.display = 'block';
            }
        }
    }

    async handleLogout() {
        try {
            await this.apiCall('/api/logout', 'POST');
        } catch (error) {
            console.log('Logout error:', error);
        }

        this.clearSession();
        this.showLoginScreen();
    }

    async loadWalletInfo() {
        // Don't attempt if session is invalid
        if (!this.isSessionValid) {
            console.log('Session invalid, skipping wallet info load');
            return;
        }
        
        try {
            const response = await this.apiCall('/api/wallet-info', 'GET', null, this.userPassword);

            if (response.success) {
                const walletInfo = document.getElementById('walletInfo');
                if (walletInfo) {
                    walletInfo.innerHTML = `
                        <div class="wallet-address">${response.wallet_address}</div>
                        <div class="wallet-balance">
                            Balance: ${response.balance_eth.toFixed(6)} ETH ($${response.balance_usd.toFixed(2)})
                        </div>
                        <div class="rpc-info">
                            RPC Node: ${response.rpc_url}
                        </div>
                    `;
                }
                this.failedRequests = 0;
            } else if (response.wallet_configured === false) {
                const walletInfo = document.getElementById('walletInfo');
                if (walletInfo) walletInfo.innerHTML = '<p>Please configure your wallet in Settings</p>';
            } else if (response.error === 'Password required') {
                const password = await this.promptForPassword();
                if (password) {
                    this.userPassword = password;
                    localStorage.setItem('userPassword', this.userPassword);
                    this.loadWalletInfo();
                }
            } else {
                const walletInfo = document.getElementById('walletInfo');
                if (walletInfo) walletInfo.innerHTML = `<p>Error: ${response.error}</p>`;
            }
        } catch (error) {
            console.error('Failed to load wallet info:', error);
            if (error.message === 'Session expired') {
                this.handleSessionExpired();
            } else {
                const walletInfo = document.getElementById('walletInfo');
                if (walletInfo) walletInfo.innerHTML = '<p>Error loading wallet info</p>';
            }
        }
    }

    async loadNetworkInfo() {
        // Don't attempt if session is invalid
        if (!this.isSessionValid) {
            console.log('Session invalid, skipping network info load');
            return;
        }
        
        try {
            const response = await this.apiCall('/api/gas-info', 'GET', null, this.userPassword);

            if (response.success) {
                this.displayNetworkInfo(response);
                this.failedRequests = 0;
            } else if (response.error === 'Password required') {
                const password = await this.promptForPassword();
                if (password) {
                    this.userPassword = password;
                    localStorage.setItem('userPassword', this.userPassword);
                    this.loadNetworkInfo();
                }
            } else {
                const networkInfo = document.getElementById('networkInfo');
                if (networkInfo) networkInfo.innerHTML = `<p>Error: ${response.error}</p>`;
            }
        } catch (error) {
            console.error('Failed to load network info:', error);
            if (error.message === 'Session expired') {
                this.handleSessionExpired();
            } else {
                const networkInfo = document.getElementById('networkInfo');
                if (networkInfo) networkInfo.innerHTML = '<p>Error loading network information</p>';
            }
        }
    }

    handleSessionExpired() {
        console.log('Session expired, clearing and redirecting');
        this.isSessionValid = false;
        this.clearSession();
        
        // Show a message to the user
        alert('Your session has expired. Please log in again.');
        
        // Stop all polling
        if (this.pollingInterval) {
            clearInterval(this.pollingInterval);
            this.pollingInterval = null;
        }
        
        // Redirect to login
        this.showLoginScreen();
    }

    displayNetworkInfo(data) {
        const networkInfo = document.getElementById('networkInfo');
        if (!networkInfo) return;
        
        const gasInfo = data.gas_info;
        const cost1000 = data.cost_1000_tx;
        const network = data.network_info;

        const gasPriceColor = this.getGasPriceColor(gasInfo.gas_price_gwei);

        let sourceBadge = '';
        let sourceText = '';
        if (gasInfo.source === 'rpc') {
            sourceBadge = '<span style="background: #27ae60; padding: 3px 8px; border-radius: 12px; font-size: 10px; color: white; font-weight: bold;">LIVE</span>';
            sourceText = 'Live from blockchain';
        } else if (gasInfo.source === 'fee_history') {
            sourceBadge = '<span style="background: #2980b9; padding: 3px 8px; border-radius: 12px; font-size: 10px; color: white; font-weight: bold;">FEE HISTORY</span>';
            sourceText = 'Calculated from fee history';
        } else if (gasInfo.source === 'fallback') {
            sourceBadge = '<span style="background: #f39c12; padding: 3px 8px; border-radius: 12px; font-size: 10px; color: black; font-weight: bold;">TYPICAL</span>';
            sourceText = 'Typical Base chain price';
        } else {
            sourceBadge = '<span style="background: #7f8c8d; padding: 3px 8px; border-radius: 12px; font-size: 10px; color: white; font-weight: bold;">ESTIMATED</span>';
            sourceText = 'Estimated price';
        }

        networkInfo.innerHTML = `
            <div class="gas-price" style="color: ${gasPriceColor}">
                ${gasInfo.gas_price_gwei.toFixed(6)} Gwei ${sourceBadge}
            </div>
            <div class="gas-source">
                ${sourceText}
            </div>
            
            <div class="cost-breakdown">
                <div style="margin-bottom: 12px; font-weight: 600; font-size: 14px; color: #ffffff;">💡 Cost for 1000 Micro Buys:</div>
                
                <div class="cost-item">
                    <span>Network Fees:</span>
                    <span>${cost1000.total_gas_eth.toFixed(8)} ETH ($${cost1000.total_gas_usd.toFixed(2)})</span>
                </div>
                
                <div class="cost-item">
                    <span>Token Purchases:</span>
                    <span>${cost1000.total_buy_amount_eth.toFixed(8)} ETH ($${cost1000.total_buy_amount_usd.toFixed(2)})</span>
                </div>
                
                <div class="cost-total">
                    <span>Total Estimated Cost:</span>
                    <span>${cost1000.total_micro_buy_cost_eth.toFixed(8)} ETH ($${cost1000.total_micro_buy_cost_usd.toFixed(2)})</span>
                </div>
            </div>
            
            <div class="update-time">
                ETH: $${network.eth_price_usd.toFixed(2)} | Updated: ${new Date().toLocaleTimeString()}
            </div>
        `;
    }

    getGasPriceColor(gasPriceGwei) {
        if (gasPriceGwei < 0.001) return '#28a745';
        if (gasPriceGwei < 0.01) return '#20c997';
        if (gasPriceGwei < 0.1) return '#ffc107';
        if (gasPriceGwei < 1) return '#fd7e14';
        return '#dc3545';
    }

    async promptForPassword() {
        return new Promise((resolve) => {
            const password = prompt('Please enter your password to continue:');
            resolve(password);
        });
    }

    async saveSettings(e) {
        e.preventDefault();

        const settings = {
            pk: document.getElementById('settingsPk').value,
            node: document.getElementById('settingsNode').value,
            token_ca: document.getElementById('settingsTokenCA').value,
            buy_amount_wei: parseInt(document.getElementById('settingsBuyAmount').value),
            password: this.userPassword
        };

        if (!settings.password) {
            settings.password = await this.promptForPassword();
            if (!settings.password) {
                alert('Password is required to save settings');
                return;
            }
            this.userPassword = settings.password;
            localStorage.setItem('userPassword', this.userPassword);
        }

        try {
            const response = await this.apiCall('/api/settings', 'POST', settings);

            if (response.success) {
                alert('Settings saved successfully!');
                this.closeSettings();
                this.loadWalletInfo();
            } else {
                alert('Failed to save settings: ' + response.error);
            }
        } catch (error) {
            alert('Error saving settings: ' + error.message);
        }
    }

    async loadSettings() {
        try {
            const response = await this.apiCall('/api/settings', 'GET');

            if (response.success && response.settings) {
                const settings = response.settings;
                const settingsPk = document.getElementById('settingsPk');
                const settingsNode = document.getElementById('settingsNode');
                const settingsTokenCA = document.getElementById('settingsTokenCA');
                const settingsBuyAmount = document.getElementById('settingsBuyAmount');
                const tokenAddress = document.getElementById('tokenAddress');
                
                if (settingsPk) settingsPk.value = settings.pk || '';
                if (settingsNode) settingsNode.value = settings.node || '';
                if (settingsTokenCA) settingsTokenCA.value = settings.token_ca || '';
                if (settingsBuyAmount) settingsBuyAmount.value = settings.buy_amount_wei || 10;
                if (tokenAddress && settings.token_ca) tokenAddress.value = settings.token_ca;
            }
        } catch (error) {
            console.error('Failed to load settings:', error);
        }
    }

    async validateNode() {
        const nodeUrl = document.getElementById('settingsNode').value;
        if (!nodeUrl) {
            alert('Please enter a node URL');
            return;
        }

        try {
            const response = await this.apiCall('/api/validate-node', 'POST', {
                node_url: nodeUrl
            });

            if (response.success) {
                if (response.is_connected) {
                    alert(`✅ Node is working! Latest block: ${response.latest_block}`);
                } else {
                    alert('❌ Node is not connected');
                }
            } else {
                alert('❌ Node validation failed: ' + response.error);
            }
        } catch (error) {
            alert('Error validating node: ' + error.message);
        }
    }

    openSettings() {
        const modal = document.getElementById('settingsModal');
        if (modal) modal.classList.add('active');
    }

    closeSettings() {
        const modal = document.getElementById('settingsModal');
        if (modal) modal.classList.remove('active');
    }

    openChangePasswordModal() {
        const modal = document.getElementById('changePasswordModal');
        if (modal) modal.classList.add('active');
    }

    closeChangePasswordModal() {
        const modal = document.getElementById('changePasswordModal');
        if (modal) modal.classList.remove('active');
        const form = document.getElementById('changePasswordForm');
        if (form) form.reset();
    }

    openManageUsersModal() {
        console.log('Opening manage users modal');
        const modal = document.getElementById('manageUsersModal');
        if (modal) modal.classList.add('active');
        this.loadUsers();
    }

    closeManageUsersModal() {
        console.log('Closing manage users modal');
        const modal = document.getElementById('manageUsersModal');
        if (modal) modal.classList.remove('active');
    }

    openCreateUserModal() {
        console.log('Opening create user modal');
        const modal = document.getElementById('createUserModal');
        if (modal) modal.classList.add('active');
    }

    closeCreateUserModal() {
        console.log('Closing create user modal');
        const modal = document.getElementById('createUserModal');
        if (modal) modal.classList.remove('active');
        const form = document.getElementById('createUserForm');
        if (form) form.reset();
    }

    async estimateCost() {
        const tokenAddress = document.getElementById('tokenAddress').value;
        const speed = document.getElementById('speed').value;
        const numCycles = parseInt(document.getElementById('numCycles').value);

        if (!tokenAddress) {
            alert('Please enter a token address');
            return;
        }

        if (!this.userPassword) {
            const password = await this.promptForPassword();
            if (!password) {
                alert('Password is required to estimate cost');
                return;
            }
            this.userPassword = password;
            localStorage.setItem('userPassword', this.userPassword);
        }

        try {
            const response = await this.apiCall('/api/estimate-cost', 'POST', {
                token_address: tokenAddress,
                speed: speed,
                num_cycles: numCycles
            }, this.userPassword);

            if (response.success) {
                this.showCostEstimation(response.estimation);
            } else {
                alert('Failed to estimate cost: ' + response.error);
            }
        } catch (error) {
            alert('Error estimating cost: ' + error.message);
        }
    }

    showCostEstimation(estimation) {
        const content = document.getElementById('costEstimationContent');
        if (!content) return;

        let warningHtml = '';
        if (estimation.warning) {
            warningHtml = `<div class="cost-warning">⚠️ ${estimation.warning}</div>`;
        }

        content.innerHTML = `
            <h3>${estimation.estimation_for}</h3>
            ${warningHtml}
            <div class="cost-breakdown">
                <h4>Network Conditions:</h4>
                <div class="cost-item">
                    <span>ETH Price:</span>
                    <span>$${estimation.network_conditions.eth_price_usd.toFixed(2)}</span>
                </div>
                <div class="cost-item">
                    <span>Gas Price:</span>
                    <span>${estimation.network_conditions.gas_price_gwei} Gwei</span>
                </div>
                
                <h4>Transaction Counts:</h4>
                <div class="cost-item">
                    <span>Total Cycles:</span>
                    <span>${estimation.transaction_counts.total_cycles}</span>
                </div>
                <div class="cost-item">
                    <span>Total Micro Buys:</span>
                    <span>${estimation.transaction_counts.total_transactions.toLocaleString()}</span>
                </div>
                <div class="cost-item">
                    <span>Wallets Needed:</span>
                    <span>${estimation.transaction_counts.wallets_needed.toLocaleString()}</span>
                </div>
                
                <h4>Cost Breakdown (USD):</h4>
                ${Object.entries(estimation.cost_breakdown_usd).map(([key, value]) => `
                    <div class="cost-item">
                        <span>${this.formatKey(key)}:</span>
                        <span>$${typeof value === 'number' ? value.toFixed(2) : value}</span>
                    </div>
                `).join('')}
                
                <div class="cost-total">
                    <span>TOTAL COST:</span>
                    <span>$${estimation.cost_breakdown_usd.total_cost_usd.toFixed(2)}</span>
                </div>
            </div>
        `;

        const modal = document.getElementById('costModal');
        if (modal) modal.classList.add('active');
    }

    formatKey(key) {
        return key.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase());
    }

    closeCostModal() {
        const modal = document.getElementById('costModal');
        if (modal) modal.classList.remove('active');
    }

    async startOperation(e) {
        e.preventDefault();

        const tokenAddress = document.getElementById('tokenAddress').value;
        const speed = document.getElementById('speed').value;
        const numCycles = parseInt(document.getElementById('numCycles').value);

        if (!tokenAddress) {
            alert('Please enter a token address');
            return;
        }

        if (!this.userPassword) {
            const password = await this.promptForPassword();
            if (!password) {
                alert('Password is required to start operation');
                return;
            }
            this.userPassword = password;
            localStorage.setItem('userPassword', this.userPassword);
        }

        const startBtn = document.getElementById('startOperationBtn');
        if (startBtn) {
            startBtn.disabled = true;
            startBtn.textContent = 'Starting...';
        }

        try {
            const response = await this.apiCall('/api/start-operation', 'POST', {
                token_address: tokenAddress,
                speed: speed,
                num_cycles: numCycles
            }, this.userPassword);

            if (response.success) {
                this.addLog(`🚀 Operation started: ${response.operation_id}`);
                this.loadOperations();
            } else {
                alert('Failed to start operation: ' + response.error);
            }
        } catch (error) {
            alert('Error starting operation: ' + error.message);
        } finally {
            if (startBtn) {
                startBtn.disabled = false;
                startBtn.textContent = 'Start Parallel Operation';
            }
        }
    }

    async loadOperations() {
        // Don't attempt if session is invalid
        if (!this.isSessionValid) {
            return;
        }
        
        try {
            const response = await this.apiCall('/api/operations', 'GET');

            if (response.success) {
                this.displayOperations(response.operations);
                this.failedRequests = 0;
            }
        } catch (error) {
            console.error('Failed to load operations:', error);
            if (error.message === 'Session expired') {
                this.handleSessionExpired();
            }
        }
    }

    displayOperations(operations) {
        const container = document.getElementById('activeOperations');
        if (!container) return;

        const filteredOperations = {};
        Object.entries(operations).forEach(([id, op]) => {
            const startTime = new Date(op.start_time).getTime();
            const currentTime = new Date().getTime();
            const ageInSeconds = (currentTime - startTime) / 1000;

            if (op.status === 'running' || (op.status !== 'running' && ageInSeconds < 30)) {
                filteredOperations[id] = op;
            }
        });

        if (Object.keys(filteredOperations).length === 0) {
            container.innerHTML = '<p>No active operations</p>';
            return;
        }

        container.innerHTML = Object.entries(filteredOperations).map(([id, op]) => `
            <div class="operation-item">
                <div class="operation-header">
                    <strong>Operation ${id.slice(-8)}</strong>
                    <span class="operation-status status-${op.status}">${op.status.toUpperCase()}</span>
                </div>
                <div>Token: ${op.config.token_address.slice(0, 10)}...${op.config.token_address.slice(-8)}</div>
                <div>Speed: ${op.config.speed} | Cycles: ${op.config.num_cycles}</div>
                <div>Started: ${new Date(op.start_time).toLocaleString()}</div>
                <div class="operation-progress">
                    <div>Progress: ${op.progress.cycles_completed}/${op.progress.total_cycles} cycles</div>
                    <div>Successful Buys: ${op.progress.successful_buys}</div>
                    <div class="progress-bar">
                        <div class="progress-fill" style="width: ${(op.progress.cycles_completed / op.progress.total_cycles) * 100}%"></div>
                    </div>
                </div>
                ${op.status === 'running' ? `
                    <div style="display: flex; gap: 0.5rem; margin-top: 0.5rem;">
                        <button onclick="app.stopOperation('${id}')" class="btn-danger">
                            🛑 Stop Operation
                        </button>
                    </div>
                ` : `
                    <div style="margin-top: 0.5rem; color: #666; font-size: 12px;">
                        Operation ${op.status} - will auto-remove shortly
                    </div>
                `}
            </div>
        `).join('');
    }

    async stopOperation(operationId) {
        if (!confirm('Are you sure you want to STOP this operation immediately?')) {
            return;
        }

        try {
            const response = await this.apiCall(`/api/stop-operation/${operationId}`, 'POST');

            if (response.success) {
                this.addLog(`🛑 Operation ${operationId} STOPPED immediately`);
                this.loadOperations();
            } else {
                alert('Failed to stop operation: ' + response.error);
            }
        } catch (error) {
            alert('Error stopping operation: ' + error.message);
        }
    }

    async downloadLogs() {
        try {
            const response = await fetch('/api/download-logs', {
                headers: {
                    'X-Session-ID': this.sessionId
                }
            });

            if (response.ok) {
                const blob = await response.blob();
                const url = window.URL.createObjectURL(blob);
                const a = document.createElement('a');
                a.style.display = 'none';
                a.href = url;
                a.download = `micro_buy_bot_logs_${this.username}_${new Date().toISOString().slice(0, 19).replace(/:/g, '-')}.txt`;
                document.body.appendChild(a);
                a.click();
                window.URL.revokeObjectURL(url);
                document.body.removeChild(a);
                this.addLog('📥 Logs downloaded successfully');
            } else {
                alert('Failed to download logs');
            }
        } catch (error) {
            alert('Error downloading logs: ' + error.message);
        }
    }

    connectWebSocket() {
        if (!this.sessionId) return;

        const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        const wsUrl = `${protocol}//${window.location.host}/ws/${this.sessionId}/logs`;

        this.ws = new WebSocket(wsUrl);

        this.ws.onmessage = (event) => {
            const data = JSON.parse(event.data);
            if (data.type === 'log') {
                this.addLog(data.message, data.timestamp);
            }
        };

        this.ws.onopen = () => {
            console.log('WebSocket connected');
            this.addLog('WebSocket connected - Live logs active');
        };

        this.ws.onclose = () => {
            console.log('WebSocket disconnected');
            if (this.isSessionValid) {
                this.addLog('WebSocket disconnected - Reconnecting...');
                setTimeout(() => this.connectWebSocket(), 5000);
            }
        };

        this.ws.onerror = (error) => {
            console.error('WebSocket error:', error);
            this.addLog('WebSocket connection error');
        };
    }

    addLog(message, timestamp = new Date().toISOString()) {
        const logOutput = document.getElementById('logOutput');
        if (!logOutput) return;
        
        const logEntry = document.createElement('div');
        logEntry.className = 'log-entry';

        const time = new Date(timestamp).toLocaleTimeString();
        logEntry.innerHTML = `
            <span class="log-timestamp">[${time}]</span> ${message}
        `;

        logOutput.appendChild(logEntry);
        logOutput.scrollTop = logOutput.scrollHeight;
    }

    clearLogs() {
        const logOutput = document.getElementById('logOutput');
        if (logOutput) logOutput.innerHTML = '';
    }

    startOperationPolling() {
        // Clear existing interval if any
        if (this.pollingInterval) {
            clearInterval(this.pollingInterval);
        }
        
        this.pollingInterval = setInterval(() => {
            if (this.isSessionValid) {
                this.loadOperations();
                // Refresh wallet and network info every 5 minutes
                if (Date.now() % 300000 < 5000) {
                    this.loadWalletInfo();
                    this.loadNetworkInfo();
                }
            }
        }, 5000);
    }

    async testAdminAccess() {
        try {
            const response = await this.apiCall('/api/admin/check-access', 'GET');
            if (response.success) {
                alert(`✅ Admin access confirmed!\nUser: ${response.username}\nRole: ${response.role}`);
                return true;
            }
        } catch (error) {
            alert('❌ Admin access denied: ' + error.message);
            return false;
        }
    }

    async loadAdminStats() {
        if (this.userRole !== 'admin') return;
        
        try {
            const [systemStats, allOperations] = await Promise.all([
                this.apiCall('/api/admin/system-stats', 'GET'),
                this.apiCall('/api/admin/all-operations', 'GET')
            ]);
            this.displayAdminStats(systemStats, allOperations);
        } catch (error) {
            console.error('Failed to load admin stats:', error);
            const statsContainer = document.getElementById('adminStatsContainer') || document.getElementById('adminStats');
            if (statsContainer) {
                statsContainer.innerHTML = '<div style="color: #dc3545;">Error loading statistics</div>';
            }
        }
    }

    displayAdminStats(systemStats, allOperations) {
        if (this.userRole !== 'admin') return;

        let statsContainer = document.getElementById('adminStatsContainer');
        if (!statsContainer) {
            statsContainer = document.getElementById('adminStats');
        }
        if (!statsContainer) {
            const adminStatsSection = document.getElementById('adminStatsSection');
            if (adminStatsSection) {
                statsContainer = document.createElement('div');
                statsContainer.id = 'adminStatsContainer';
                adminStatsSection.appendChild(statsContainer);
            }
        }
        
        if (!statsContainer) {
            console.warn('Stats container not found');
            return;
        }

        let statsHTML = '<h4>📊 Bot Statistics</h4>';

        if (systemStats.success) {
            const stats = systemStats.stats;
            statsHTML += `
                <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 15px; margin-top: 10px;">
                    <div style="background: rgba(255,255,255,0.1); padding: 15px; border-radius: 10px;">
                        <h5 style="margin: 0 0 10px 0; color: #00A389;">👥 Users</h5>
                        <div>Total: ${stats.total_users || 0}</div>
                        <div>Active Sessions: ${stats.active_sessions || 0}</div>
                        <div>Active (1h): ${stats.active_users_last_hour || 0}</div>
                    </div>
                    
                    <div style="background: rgba(255,255,255,0.1); padding: 15px; border-radius: 10px;">
                        <h5 style="margin: 0 0 10px 0; color: #00A389;">🔄 Operations</h5>
                        <div>Total: ${stats.total_operations || 0}</div>
                        <div>Running: ${stats.running_operations || 0}</div>
                        <div>Completed: ${stats.completed_operations || 0}</div>
                    </div>
                    
                    <div style="background: rgba(255,255,255,0.1); padding: 15px; border-radius: 10px;">
                        <h5 style="margin: 0 0 10px 0; color: #00A389;">📈 Performance</h5>
                        <div>Success Rate: ${stats.success_rate || 0}%</div>
                        <div>Completion: ${stats.completion_rate || 0}%</div>
                        <div>Successful Buys: ${stats.total_successful_buys || 0}</div>
                    </div>
                </div>
            `;
        } else {
            statsHTML += `
                <div style="color: #dc3545; background: rgba(220,53,69,0.2); padding: 10px; border-radius: 5px;">
                    <div>❌ Error loading statistics: ${systemStats.error || 'Unknown error'}</div>
                    <button onclick="app.loadAdminStats()" style="margin-top: 10px; padding: 5px 10px; background: #ffc107; border: none; border-radius: 5px; cursor: pointer;">
                        Retry
                    </button>
                </div>
            `;
        }

        if (allOperations.success && allOperations.operations && Object.keys(allOperations.operations).length > 0) {
            statsHTML += `
                <div style="margin-top: 20px;">
                    <h5>🚀 Currently Active Operations</h5>
                    <div style="max-height: 150px; overflow-y: auto; background: rgba(0,0,0,0.2); padding: 10px; border-radius: 5px;">
                        ${Object.entries(allOperations.operations).map(([id, op]) => `
                            <div style="margin: 5px 0; padding: 8px; background: rgba(255,255,255,0.05); border-radius: 3px; border-left: 3px solid #00A389; font-size: 12px;">
                                <strong>${op.username || 'Unknown'}</strong> | 
                                ${op.config?.token_address ? op.config.token_address.slice(0, 8) + '...' : 'No token'} | 
                                <span class="status-${op.status || 'unknown'}">${(op.status || 'UNKNOWN').toUpperCase()}</span> |
                                Progress: ${op.progress?.cycles_completed || 0}/${op.progress?.total_cycles || 0}
                            </div>
                        `).join('')}
                    </div>
                </div>
            `;
        }

        statsContainer.innerHTML = statsHTML;
    }

    async loadUsers() {
        try {
            const response = await this.apiCall('/api/admin/users', 'GET');

            if (response.success) {
                this.displayUsers(response.users);
            } else {
                alert('Failed to load users: ' + response.error);
            }
        } catch (error) {
            alert('Error loading users: ' + error.message);
        }
    }

    displayUsers(users) {
        const container = document.getElementById('usersList');
        if (!container) return;

        if (users.length === 0) {
            container.innerHTML = '<p>No users found</p>';
            return;
        }

        container.innerHTML = users.map(user => `
            <div class="user-item">
                <div class="user-details">
                    <div>
                        <span class="user-username">${user.username}</span>
                        <span class="user-role-badge role-${user.role}">${user.role.toUpperCase()}</span>
                    </div>
                    <div class="user-status">
                        Created: ${new Date(user.created_at).toLocaleDateString()} | 
                        Status: <span class="status-${user.is_active ? 'active' : 'inactive'}">
                            ${user.is_active ? 'Active' : 'Inactive'}
                        </span>
                    </div>
                </div>
                <div class="user-actions">
                    ${user.username !== 'admin' ? `
                        <button onclick="app.toggleUserStatus('${user.username}')" class="btn-warning">
                            ${user.is_active ? 'Deactivate' : 'Activate'}
                        </button>
                        <button onclick="app.deleteUser('${user.username}')" class="btn-danger">
                            Delete
                        </button>
                    ` : '<span style="color: #6c757d;">System Admin</span>'}
                </div>
            </div>
        `).join('');
    }

    async createUser(username, password, role) {
        try {
            console.log('Creating user:', { username, role });

            const response = await this.apiCall('/api/admin/create-user', 'POST', {
                username,
                password,
                role
            });

            console.log('Create user response:', response);

            if (response.success) {
                alert('✅ User created successfully!');
                this.closeCreateUserModal();
                this.loadUsers();
            } else {
                alert('❌ Failed to create user: ' + (response.message || response.error));
            }
        } catch (error) {
            console.error('Error creating user:', error);
            alert('❌ Error creating user: ' + error.message);
        }
    }

    handleCreateUser(e) {
        e.preventDefault();
        console.log('Create user form submitted');

        const username = document.getElementById('newUsername').value.trim();
        const password = document.getElementById('newUserPassword').value;
        const role = document.getElementById('newUserRole').value;

        console.log('Form data:', { username, password, role });

        if (!username || !password) {
            alert('Please fill in all fields');
            return;
        }

        if (username.length < 3) {
            alert('Username must be at least 3 characters long');
            return;
        }

        if (password.length < 6) {
            alert('Password must be at least 6 characters long');
            return;
        }

        this.createUser(username, password, role);
    }

    async deleteUser(username) {
        if (!confirm(`Are you sure you want to delete user "${username}"? This action cannot be undone.`)) {
            return;
        }

        try {
            const response = await this.apiCall(`/api/admin/users/${username}`, 'DELETE');

            if (response.success) {
                alert('User deleted successfully!');
                this.loadUsers();
            } else {
                alert('Failed to delete user: ' + response.error);
            }
        } catch (error) {
            alert('Error deleting user: ' + error.message);
        }
    }

    async toggleUserStatus(username) {
        try {
            const response = await this.apiCall(`/api/admin/users/${username}/toggle`, 'POST');

            if (response.success) {
                alert('User status updated successfully!');
                this.loadUsers();
            } else {
                alert('Failed to update user status: ' + response.error);
            }
        } catch (error) {
            alert('Error updating user status: ' + error.message);
        }
    }

    async changePassword(oldPassword, newPassword) {
        try {
            const response = await this.apiCall('/api/change-password', 'POST', {
                old_password: oldPassword,
                new_password: newPassword
            });

            if (response.success) {
                alert('Password changed successfully!');
                this.closeChangePasswordModal();
                if (oldPassword === this.userPassword) {
                    this.userPassword = newPassword;
                    localStorage.setItem('userPassword', this.userPassword);
                }
            } else {
                alert('Failed to change password: ' + response.error);
            }
        } catch (error) {
            alert('Error changing password: ' + error.message);
        }
    }

    handleChangePassword(e) {
        e.preventDefault();

        const oldPassword = document.getElementById('oldPassword').value;
        const newPassword = document.getElementById('newPassword').value;
        const confirmPassword = document.getElementById('confirmPassword').value;

        if (!oldPassword || !newPassword || !confirmPassword) {
            alert('Please fill in all fields');
            return;
        }

        if (newPassword !== confirmPassword) {
            alert('New passwords do not match!');
            return;
        }

        if (newPassword.length < 6) {
            alert('New password must be at least 6 characters long');
            return;
        }

        this.changePassword(oldPassword, newPassword);
    }

    async apiCall(endpoint, method = 'GET', data = null, password = null) {
        const options = {
            method,
            headers: {
                'Content-Type': 'application/json',
            },
        };

        // Always add session ID if available
        if (this.sessionId) {
            options.headers['X-Session-ID'] = this.sessionId;
        }

        // Add password header if provided (for wallet operations)
        if (password) {
            options.headers['Password'] = password;
        }

        if (data && method !== 'GET') {
            options.body = JSON.stringify(data);
        }

        try {
            const response = await fetch(endpoint, options);

            // Handle 401 Unauthorized
            if (response.status === 401) {
                console.warn('API call returned 401:', endpoint);
                this.isSessionValid = false;
                throw new Error('Session expired');
            }

            if (!response.ok) {
                throw new Error(`HTTP error! status: ${response.status}`);
            }

            return await response.json();
            
        } catch (error) {
            if (error.message === 'Session expired') {
                this.handleSessionExpired();
            }
            throw error;
        }
    }
}

// Initialize the application when DOM is loaded
document.addEventListener('DOMContentLoaded', () => {
    window.app = new ParallelMicroBuyBotApp();
});