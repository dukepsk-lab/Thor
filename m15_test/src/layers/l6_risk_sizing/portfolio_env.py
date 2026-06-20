import numpy as np
import gymnasium as gym
from gymnasium import spaces
from typing import List, Dict

class PortfolioEnv(gym.Env):
    """
    A custom Gymnasium environment for Multi-Asset Portfolio Allocation.
    The agent receives primary signals, meta-probabilities, and volatilities.
    The action is a continuous vector which is softmax-normalized to represent portfolio weights.
    """
    metadata = {"render_modes": ["human"]}

    def __init__(self, 
                 df_features: np.ndarray, 
                 df_returns: np.ndarray, 
                 df_spreads_pct: np.ndarray,
                 symbols: List[str],
                 initial_balance: float = 10000.0,
                 commission_per_lot: float = 7.0,
                 contract_size: float = 100000.0,
                 risk_penalty_coeff: float = 0.1):
        super(PortfolioEnv, self).__init__()
        
        # Data
        self.features = df_features # Shape: (time_steps, num_assets * features_per_asset)
        self.returns = df_returns   # Shape: (time_steps, num_assets)
        self.spreads_pct = df_spreads_pct # Shape: (time_steps, num_assets)
        self.symbols = symbols
        self.num_assets = len(symbols)
        self.time_steps = len(df_features)
        
        # Cost Configuration
        self.initial_balance = initial_balance
        # $7 per lot (100,000 units) -> 7 / 100000 = 0.00007 (0.007%)
        self.commission_rate = commission_per_lot / contract_size
        self.risk_penalty_coeff = risk_penalty_coeff
        
        # State tracking
        self.current_step = 0
        self.balance = self.initial_balance
        # Weights: [Cash, Asset1, Asset2, ...]
        self.current_weights = np.zeros(self.num_assets + 1)
        self.current_weights[0] = 1.0 # 100% in cash initially
        
        # Actions: Continuous vector that will be Softmaxed
        # Shape: (num_assets + 1)
        self.action_space = spaces.Box(low=-10, high=10, shape=(self.num_assets + 1,), dtype=np.float32)
        
        # Observation: The features for the current step + current weights
        # Features length + weights length
        obs_len = self.features.shape[1] + len(self.current_weights)
        self.observation_space = spaces.Box(low=-np.inf, high=np.inf, shape=(obs_len,), dtype=np.float32)

    def _get_obs(self):
        feat = self.features[self.current_step]
        obs = np.concatenate([feat, self.current_weights])
        return obs.astype(np.float32)

    def reset(self, seed=None, options=None):
        super().reset(seed=seed)
        self.current_step = 0
        self.balance = self.initial_balance
        self.current_weights = np.zeros(self.num_assets + 1)
        self.current_weights[0] = 1.0
        return self._get_obs(), {}

    def step(self, action):
        # Softmax the action to get Dirichlet-like weights (sum to 1)
        exp_a = np.exp(action - np.max(action))
        target_weights = exp_a / exp_a.sum()
        
        # Calculate Turnover (for transaction costs)
        weight_changes = np.abs(target_weights[1:] - self.current_weights[1:])
        turnover = np.sum(weight_changes)
        
        # Get real spread costs for this specific step (as a percentage of price)
        current_spreads_pct = self.spreads_pct[self.current_step]
        
        # Total transaction cost = (Base Commission Rate * Turnover) + (Real Spread Pct * specific asset turnover)
        # Note: spread is paid when crossing the bid/ask, applying half-spread cost for each trade (entry/exit)
        spread_cost = np.sum(weight_changes * (current_spreads_pct / 2.0))
        commission_cost = turnover * self.commission_rate
        total_transaction_costs = commission_cost + spread_cost
        
        # Get actual asset returns for this step
        step_returns = self.returns[self.current_step]
        
        # Portfolio return = sum(weight * return)
        portfolio_return = np.sum(target_weights[1:] * step_returns)
        
        # Risk penalty
        risk_penalty = self.risk_penalty_coeff * np.std(step_returns * target_weights[1:])
        
        # Net Reward
        reward = portfolio_return - total_transaction_costs - risk_penalty
        
        # Update state
        self.balance *= (1 + portfolio_return - total_transaction_costs)
        self.current_weights = target_weights
        
        self.current_step += 1
        terminated = self.current_step >= self.time_steps - 1
        truncated = False
        
        info = {
            "portfolio_return": portfolio_return,
            "turnover": turnover,
            "transaction_costs": total_transaction_costs,
            "reward": reward,
            "balance": self.balance
        }
        
        return self._get_obs(), reward, terminated, truncated, info
