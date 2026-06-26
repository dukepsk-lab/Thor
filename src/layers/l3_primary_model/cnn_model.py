import torch
import torch.nn as nn
import pandas as pd
import numpy as np

class TemporalCNN(nn.Module):
    """
    A 1D-CNN designed to extract structural and sequential features from recent time-series windows.
    """
    def __init__(self, num_features: int, sequence_length: int, num_classes: int = 3):
        super(TemporalCNN, self).__init__()
        
        self.conv1 = nn.Conv1d(in_channels=num_features, out_channels=32, kernel_size=3, padding=1)
        self.relu = nn.ReLU()
        self.pool = nn.MaxPool1d(kernel_size=2)
        
        self.conv2 = nn.Conv1d(in_channels=32, out_channels=64, kernel_size=3, padding=1)
        
        # Calculate flattened dimension
        self.flattened_dim = 64 * (sequence_length // 2 // 2)
        
        self.fc1 = nn.Linear(self.flattened_dim, 64)
        self.fc2 = nn.Linear(64, num_classes)
        self.softmax = nn.Softmax(dim=1)

    def forward(self, x):
        # x shape: (batch_size, num_features, sequence_length)
        x = self.conv1(x)
        x = self.relu(x)
        x = self.pool(x)
        
        x = self.conv2(x)
        x = self.relu(x)
        x = self.pool(x)
        
        x = x.view(x.size(0), -1)
        
        x = self.fc1(x)
        x = self.relu(x)
        x = self.fc2(x)
        return self.softmax(x)

class CNNWrapper:
    """
    Wrapper to align the PyTorch CNN interface with our pandas-based pipeline.
    """
    def __init__(self, model: TemporalCNN):
        self.model = model
        self.model.eval()

    def predict_proba(self, X_tensor: torch.Tensor, index: pd.Index) -> pd.DataFrame:
        """
        X_tensor shape: (batch_size, num_features, seq_length)
        """
        with torch.no_grad():
            probas = self.model(X_tensor).numpy()
            
        return pd.DataFrame(probas, index=index, columns=['prob_short', 'prob_flat', 'prob_long'])
