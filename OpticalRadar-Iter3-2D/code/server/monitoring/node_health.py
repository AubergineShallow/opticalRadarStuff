"""
node_health.py
PURPOSE: Track health status of camera nodes.
"""

import time
from typing import Dict, Optional, List
from dataclasses import dataclass, field
from enum import Enum


class NodeStatus(Enum):
    """Node health status."""
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    OFFLINE = "offline"


@dataclass
class NodeHealthRecord:
    """Health record for a single node."""
    node_id: str
    last_packet_time: float = 0.0
    packet_count: int = 0
    sequence_gaps: int = 0
    last_sequence: int = -1
    health_flags: int = 0
    
    # Calculated metrics
    packets_per_second: float = 0.0
    latency_ms: float = 0.0
    
    # Thresholds
    offline_timeout_sec: float = 30.0
    degraded_pps_threshold: float = 15.0  # Below this = degraded
    
    # Static Configuration (from Announce)
    sensor_config: Optional[Dict] = None
    ip_address: str = "unknown"
    
    def update(
        self,
        timestamp: float,
        sequence: int,
        health_flags: int,
        receive_time: float,
        ip_address: str = "unknown"
    ) -> None:
        """Update health record with new packet."""
        now = receive_time
        
        if ip_address != "unknown":
            self.ip_address = ip_address
        
        # Calculate packets per second (EMA)
        if self.last_packet_time > 0:
            dt = now - self.last_packet_time
            if dt > 0:
                instant_pps = 1.0 / dt
                alpha = 0.1  # Smoothing factor
                self.packets_per_second = (
                    alpha * instant_pps + (1 - alpha) * self.packets_per_second
                )
        
        # Check sequence gaps
        if self.last_sequence >= 0:
            expected = (self.last_sequence + 1) & 0xFFFFFFFF
            if sequence != expected:
                self.sequence_gaps += 1
        
        # Latency (packet timestamp vs receive time)
        self.latency_ms = (receive_time - timestamp) * 1000
        
        self.last_packet_time = now
        self.last_sequence = sequence
        self.packet_count += 1
        self.health_flags = health_flags
        
    def update_config(self, config: Dict) -> None:
        """Update static sensor configuration."""
        self.sensor_config = config
    
    def get_status(self, current_time: Optional[float] = None) -> NodeStatus:
        """Determine current health status."""
        now = current_time or time.time()
        
        # Check if offline
        if self.last_packet_time == 0:
            return NodeStatus.OFFLINE
        
        time_since_last = now - self.last_packet_time
        if time_since_last > self.offline_timeout_sec:
            return NodeStatus.OFFLINE
        
        # Check health flags
        gps_ok = bool(self.health_flags & 0x01)
        camera_ok = bool(self.health_flags & 0x02)
        imu_ok = bool(self.health_flags & 0x04)
        
        if not (gps_ok and camera_ok):
            return NodeStatus.UNHEALTHY
        
        # Check packet rate
        if self.packets_per_second < self.degraded_pps_threshold:
            return NodeStatus.DEGRADED
        
        # Check sequence gaps (more than 1% packet loss = degraded)
        if self.packet_count > 100:
            gap_rate = self.sequence_gaps / self.packet_count
            if gap_rate > 0.01:
                return NodeStatus.DEGRADED
        
        return NodeStatus.HEALTHY


class NodeHealthMonitor:
    """
    Monitor health of all camera nodes.
    
    Features:
        - Track packet rates per node
        - Detect offline nodes
        - Calculate health scores
        - Alert on health changes
    """
    
    def __init__(
        self,
        offline_timeout_sec: float = 30.0,
        alert_callback: Optional[callable] = None
    ):
        """
        Initialize health monitor.
        
        Args:
            offline_timeout_sec: Seconds before node considered offline
            alert_callback: Function to call on status changes
        """
        self._nodes: Dict[str, NodeHealthRecord] = {}
        self.offline_timeout = offline_timeout_sec
        self._alert_callback = alert_callback
        self._previous_status: Dict[str, NodeStatus] = {}
    
    def update_node_config(self, node_id: str, config: Dict) -> None:
        """Update configuration for a node."""
        if node_id not in self._nodes:
            self._nodes[node_id] = NodeHealthRecord(
                node_id=node_id,
                offline_timeout_sec=self.offline_timeout
            )
        self._nodes[node_id].update_config(config)

    def record_packet(
        self,
        node_id: str,
        packet_timestamp: float,
        sequence: int,
        health_flags: int,
        ip_address: str = "unknown"
    ) -> None:
        """
        Record receipt of a packet from a node.
        
        Args:
            node_id: Camera ID
            packet_timestamp: Timestamp from packet
            sequence: Sequence number from packet
            health_flags: Health flags from packet
            ip_address: IP address of the sender
        """
        receive_time = time.time()
        
        if node_id not in self._nodes:
            self._nodes[node_id] = NodeHealthRecord(
                node_id=node_id,
                offline_timeout_sec=self.offline_timeout
            )
        
        self._nodes[node_id].update(
            packet_timestamp,
            sequence,
            health_flags,
            receive_time,
            ip_address
        )
        
        # Check for status change
        self._check_status_change(node_id)
    
    def _check_status_change(self, node_id: str) -> None:
        """Check if node status has changed and alert if needed."""
        current = self.get_node_status(node_id)
        previous = self._previous_status.get(node_id)
        
        if previous is not None and current != previous:
            if self._alert_callback:
                self._alert_callback(node_id, previous, current)
        
        self._previous_status[node_id] = current
    
    def get_node_status(self, node_id: str) -> NodeStatus:
        """Get status of a specific node."""
        if node_id not in self._nodes:
            return NodeStatus.OFFLINE
        return self._nodes[node_id].get_status()
    
    def get_node_health(self, node_id: str) -> Optional[NodeHealthRecord]:
        """Get health record for a node."""
        return self._nodes.get(node_id)
    
    def get_all_nodes(self) -> Dict[str, NodeHealthRecord]:
        """Get all node health records."""
        return dict(self._nodes)
    
    def get_healthy_nodes(self) -> List[str]:
        """Get list of healthy node IDs."""
        return [
            node_id for node_id, record in self._nodes.items()
            if record.get_status() == NodeStatus.HEALTHY
        ]
    
    def get_offline_nodes(self) -> List[str]:
        """Get list of offline node IDs."""
        return [
            node_id for node_id, record in self._nodes.items()
            if record.get_status() == NodeStatus.OFFLINE
        ]
    
    def generate_report(self) -> str:
        """Generate human-readable health report."""
        lines = [
            "Node Health Report",
            "=" * 40,
            ""
        ]
        
        for node_id in sorted(self._nodes.keys()):
            record = self._nodes[node_id]
            status = record.get_status()
            
            status_icon = {
                NodeStatus.HEALTHY: "✅",
                NodeStatus.DEGRADED: "⚠️",
                NodeStatus.UNHEALTHY: "❌",
                NodeStatus.OFFLINE: "⬛",
            }.get(status, "?")
            
            lines.append(f"{status_icon} {node_id}: {status.value}")
            lines.append(f"   Packets: {record.packet_count}")
            lines.append(f"   Rate: {record.packets_per_second:.1f} pps")
            lines.append(f"   Latency: {record.latency_ms:.1f} ms")
            lines.append(f"   Gaps: {record.sequence_gaps}")
            
            # Health flags
            gps = "✓" if record.health_flags & 0x01 else "✗"
            cam = "✓" if record.health_flags & 0x02 else "✗"
            imu = "✓" if record.health_flags & 0x04 else "✗"
            lines.append(f"   Flags: GPS={gps} CAM={cam} IMU={imu}")
            lines.append("")
        
        return '\n'.join(lines)
    
    def reset(self) -> None:
        """Clear all node records."""
        self._nodes.clear()
        self._previous_status.clear()
