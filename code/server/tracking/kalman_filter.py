
"""
kalman_filter.py
PURPOSE: State estimation for tracked objects using constant velocity model.
"""

import numpy as np
from typing import Tuple, Optional
from dataclasses import dataclass


@dataclass
class KalmanState:
    """State vector and covariance for a tracked object."""
    # State: [x, y, z, vx, vy, vz]
    x: np.ndarray  # State vector (6,)
    P: np.ndarray  # Covariance matrix (6, 6)
    
    @property
    def position(self) -> np.ndarray:
        """Get position [x, y, z]."""
        return self.x[:3].copy()
    
    @property
    def velocity(self) -> np.ndarray:
        """Get velocity [vx, vy, vz]."""
        return self.x[3:].copy()
    
    @property
    def speed(self) -> float:
        """Get speed magnitude."""
        return float(np.linalg.norm(self.velocity))


class KalmanFilter:
    """
    Kalman filter for 3D position/velocity estimation.
    
    Uses constant velocity motion model:
        x[k+1] = F * x[k] + w
        z[k] = H * x[k] + v
    
    State vector: [x, y, z, vx, vy, vz]
    Measurement: [x, y, z]
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
            [1, 0, 0, 0, 0, 0],
            [0, 1, 0, 0, 0, 0],
            [0, 0, 1, 0, 0, 0]
        ], dtype=np.float64)
        
        # Measurement noise covariance
        self.R = np.eye(3) * (r_measurement_noise ** 2)
    
    def _get_F(self, dt: float) -> np.ndarray:
        """Get state transition matrix for time step dt."""
        return np.array([
            [1, 0, 0, dt, 0, 0],
            [0, 1, 0, 0, dt, 0],
            [0, 0, 1, 0, 0, dt],
            [0, 0, 0, 1, 0, 0],
            [0, 0, 0, 0, 1, 0],
            [0, 0, 0, 0, 0, 1]
        ], dtype=np.float64)
    
    def _get_Q(self, dt: float) -> np.ndarray:
        """Get process noise covariance for time step dt."""
        # Discrete-time process noise for constant velocity model
        q = self.q
        dt2 = dt * dt
        dt3 = dt2 * dt
        dt4 = dt3 * dt
        
        # Block structure for 3D
        Q_block = np.array([
            [dt4/4, dt3/2],
            [dt3/2, dt2]
        ]) * q
        
        Q = np.zeros((6, 6))
        for i in range(3):
            Q[i, i] = Q_block[0, 0]
            Q[i, i+3] = Q_block[0, 1]
            Q[i+3, i] = Q_block[1, 0]
            Q[i+3, i+3] = Q_block[1, 1]
        
        return Q
    
    def initialize(
        self,
        position: np.ndarray,
        velocity: Optional[np.ndarray] = None,
        position_uncertainty: float = 5.0,
        velocity_uncertainty: float = 10.0,
        measurement_covariance: Optional[np.ndarray] = None
    ) -> KalmanState:
        """
        Initialize state from first detection.

        Args:
            position: Initial position [x, y, z]
            velocity: Initial velocity [vx, vy, vz] (default: zero)
            position_uncertainty: Initial position uncertainty (meters)
            velocity_uncertainty: Initial velocity uncertainty (m/s)
            measurement_covariance: Optional 3x3 positional covariance for this
                first detection (e.g. from triangulation geometry). When given,
                it seeds the position block of P so a poorly-constrained first
                fix starts appropriately uncertain instead of a flat isotropic
                guess.

        Returns:
            Initial Kalman state
        """
        if velocity is None:
            velocity = np.zeros(3)

        x = np.concatenate([position, velocity])

        P = np.diag([
            position_uncertainty ** 2,
            position_uncertainty ** 2,
            position_uncertainty ** 2,
            velocity_uncertainty ** 2,
            velocity_uncertainty ** 2,
            velocity_uncertainty ** 2
        ])

        if measurement_covariance is not None:
            R0 = np.asarray(measurement_covariance, dtype=float).reshape(3, 3)
            P[:3, :3] = R0

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
    
    def predict_batch(self, states: list, dt: float) -> list:
        """
        Predict many tracks forward in time in one vectorized call.

        Equivalent to calling predict() on each state individually, but
        much cheaper when there are many active tracks: F and Q only get
        built once (not once per track), and the per-track matrix algebra
        becomes a single batched matmul via numpy broadcasting instead of
        N separate small (6x6) matmuls with their own Python/numpy
        call overhead.

        Args:
            states: List of current KalmanStates (length N)
            dt: Time step (seconds), shared by all states

        Returns:
            List of predicted KalmanStates, same order as input
        """
        if not states:
            return []

        F = self._get_F(dt)
        Q = self._get_Q(dt)

        X = np.stack([s.x for s in states])  # (N, 6)
        P = np.stack([s.P for s in states])  # (N, 6, 6)

        # x_pred_i = F @ x_i for every i  <=>  X @ F.T
        X_pred = X @ F.T  # (N, 6)
        # P_pred_i = F @ P_i @ F.T + Q for every i.
        # numpy broadcasts F (6,6) against the leading N dimension of P
        # automatically, so this runs all N in one vectorized call.
        P_pred = F @ P @ F.T + Q  # (N, 6, 6)

        return [
            KalmanState(x=X_pred[i], P=P_pred[i])
            for i in range(len(states))
        ]

    def update(
        self,
        state: KalmanState,
        measurement: np.ndarray,
        R: Optional[np.ndarray] = None
    ) -> Tuple[KalmanState, float]:
        """
        Update state with measurement.

        Args:
            state: Predicted state
            measurement: Position measurement [x, y, z]
            R: Optional 3x3 measurement noise covariance for THIS measurement
                (e.g. derived from the triangulation geometry / node optics that
                produced the detection). Defaults to the filter's fixed isotropic
                R when None, preserving prior behaviour.

        Returns:
            Tuple of (updated state, innovation/residual magnitude)
        """
        Reff = self.R if R is None else np.asarray(R, dtype=float).reshape(3, 3)

        # Innovation (measurement residual)
        z = measurement.reshape(3)
        y = z - self.H @ state.x

        # Innovation covariance
        S = self.H @ state.P @ self.H.T + Reff

        # Kalman gain
        K = state.P @ self.H.T @ np.linalg.inv(S)

        # Updated state
        x_upd = state.x + K @ y

        # Updated covariance (Joseph form for numerical stability)
        I = np.eye(6)
        IKH = I - K @ self.H
        P_upd = IKH @ state.P @ IKH.T + K @ Reff @ K.T

        # Residual magnitude (for gating/validation)
        innovation = float(np.linalg.norm(y))

        return KalmanState(x=x_upd, P=P_upd), innovation
    
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
            Predicted position [x, y, z]
        """
        F = self._get_F(dt)
        x_pred = F @ state.x
        return x_pred[:3]
