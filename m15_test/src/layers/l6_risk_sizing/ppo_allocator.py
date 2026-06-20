from stable_baselines3 import PPO
from stable_baselines3.common.env_checker import check_env
import os

class PPOAllocator:
    def __init__(self, env, verbose=1):
        self.env = env
        # Check if environment is valid Gymnasium
        check_env(self.env, warn=True)
        
        self.model = PPO("MlpPolicy", self.env, verbose=verbose, learning_rate=3e-4, n_steps=2048)
        
    def train(self, total_timesteps=10000):
        print(f"Training PPO Allocator for {total_timesteps} timesteps...")
        self.model.learn(total_timesteps=total_timesteps)
        
    def save(self, path="models/ppo_allocator"):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        self.model.save(path)
        print(f"PPO Model saved to {path}.zip")
        
    def load(self, path="models/ppo_allocator"):
        self.model = PPO.load(path, env=self.env)
        print(f"PPO Model loaded from {path}.zip")
        
    def predict_allocation(self, obs):
        """
        Given the current observation, returns the softmaxed weights.
        """
        action, _states = self.model.predict(obs, deterministic=True)
        # Apply the same softmax as the environment
        import numpy as np
        exp_a = np.exp(action - np.max(action))
        weights = exp_a / exp_a.sum()
        return weights
