"""
kalman_filter.py
PURPOSE: State estimation for tracked objects using constant velocity model (2D fork).

State vector: [x, y, vx, vy]  (4-state)
Measurement:  [x, y]           (2-measurement)
"""

import numpy as np
from typing import Tuple, Optional
from dataclasses import dataclass


@dataclass
class KalmanState:
    """State vector and covariance for a tracked object (2D)."""
    # State: [x, y, vx, vy]
    x: np.ndarray  # State vector (4,)
    P: np.ndarray  # Covariance matrix (4, 4)

    @property
    def position(self) -> np.ndarray:
        """Get position [x, y]."""
        return self.x[:2].copy()

    @property
    def velocity(self) -> np.ndarray:
        """Get velocity [vx, vy]."""
        return self.x[2:].copy()

    @property
    def speed(self) -> float:
        """Get speed magnitude."""
        return float(np.linalg.norm(self.velocity))


class KalmanFilter:
    """
    Kalman filter for 2D position/velocity estimation.

    Uses constant velocity motion model:
        x[k+1] = F * x[k] + w
        z[k]   = H * x[k] + v

    State vector:  [x, y, vx, vy]
    Measurement:   [x, y]
    """

    def __init__(
        self,
        q_process_noise: float = 0.1,
        r_measurement_noise: float = 2.0
    ):
        """
        Initialize Kalman filter.

        Args:
            q_process_noise: Process noise (motion uncertainty)
            r_measurement_noise: Measurement noise (detection uncertainty)
        """
        self.q = q_process_noise
        self.r = r_measurement_noise

        # Measurement matrix: we observe position only
        self.H = np.array([
            [1, 0, 0, 0],
            [0, 1, 0, 0],
        ], dtype=np.float64)

        # Measurement noise covariance
        self.R = np.eye(2) * (r_measurement_noise ** 2)

    def _get_F(self, dt: float) -> np.ndarray:
        """Get state transition matrix for time step dt."""
        return np.array([
            [1, 0, dt, 0],
            [0, 1, 0, dt],
            [0, 0, 1,  0],
            [0, 0, 0,  1],
        ], dtype=np.float64)

    def _get_Q(self, dt: float) -> np.ndarray:
        """Get process noise covariance for time step dt."""
        q = self.q
        dt2 = dt * dt
        dt3 = dt2 * dt
        dt4 = dt3 * dt

        Q_block = np.array([
            [dt4/4, dt3/2],
            [dt3/2, dt2]
        ]) * q

        Q = np.zeros((4, 4))
        for i in range(2):
            Q[i, i]       = Q_block[0, 0]
            Q[i, i+2]     = Q_block[0, 1]
            Q[i+2, i]     = Q_block[1, 0]
            Q[i+2, i+2]   = Q_block[1, 1]

        return Q

    def initialize(
        self,
        position: np.ndarray,
        velocity: Optional[np.ndarray] = None,
        position_uncertainty: float = 5.0,
        velocity_uncertainty: float = 10.0
    ) -> KalmanState:
        """
        Initialize state from first detection.

        Args:
            position: Initial position [x, y]
            velocity: Initial velocity [vx, vy] (default: zero)
            position_uncertainty: Initial position uncertainty (meters)
            velocity_uncertainty: Initial velocity uncertainty (m/s)

        Returns:
            Initial Kalman state
        """
        pos2 = np.asarray(position).ravel()[:2]
        if velocity is None:
            velocity = np.zeros(2)
        vel2 = np.asarray(velocity).ravel()[:2]

        x = np.concatenate([pos2, vel2])

        P = np.diag([
            position_uncertainty ** 2,
            position_uncertainty ** 2,
            velocity_uncertainty ** 2,
            velocity_uncertainty ** 2,
        ])

        return KalmanState(x=x, P=P)

    def predict(self, state: KalmanState, dt: float) -> KalmanState:
        """
        Predict state forward in time.

        Args:
            state: Current state
            dt: Time step (seconds)

        Returns:
            Predicted state
        """
        F = self._get_F(dt)
        Q = self._get_Q(dt)

        x_pred = F @ state.x
        P_pred = F @ state.P @ F.T + Q

        return KalmanState(x=x_pred, P=P_pred)

    def update(
        self,
        state: KalmanState,
        measurement: np.ndarray
    ) -> Tuple[KalmanState, float]:
        """
        Update state with measurement.

        Args:
            state: Predicted state
            measurement: Position measurement [x, y]

        Returns:
            Tuple of (updated state, innovation/residual magnitude)
        """
        z = measurement.ravel()[:2]
        y = z - self.H @ state.x

        # Innovation covariance
        S = self.H @ state.P @ self.H.T + self.R

        # Kalman gain
        K = state.P @ self.H.T @ np.linalg.inv(S)

        # Updated state
        x_upd = state.x + K @ y

        # Updated covariance (Joseph form for numerical stability)
        I = np.eye(4)
        IKH = I - K @ self.H
        P_upd = IKH @ state.P @ IKH.T + K @ self.R @ K.T

        innovation = float(np.linalg.norm(y))

        return KalmanState(x=x_upd, P=P_upd), innovation

    def gating_distance(
        self,
        state: KalmanState,
        measurement: np.ndarray
    ) -> float:
        """
        Calculate Mahalanobis distance for gating.

        Args:
            state: Predicted state
            measurement: Position measurement [x, y]

        Returns:
            Mahalanobis distance
        """
        z = measurement.ravel()[:2]
        y = z - self.H @ state.x

        S = self.H @ state.P @ self.H.T + self.R

        try:
            S_inv = np.linalg.inv(S)
            d2 = float(y.T @ S_inv @ y)
            return np.sqrt(d2)
        except np.linalg.LinAlgError:
            return float('inf')

    def predict_position(
        self,
        state: KalmanState,
        dt: float
    ) -> np.ndarray:
        """
        Predict position at future time.

        Args:
            state: Current state
            dt: Time ahead (seconds)

        Returns:
            Predicted position [x, y]
        """
        F = self._get_F(dt)
        x_pred = F @ state.x
        return x_pred[:2]
