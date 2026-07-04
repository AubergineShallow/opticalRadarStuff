"""
metrics.py
PURPOSE: Performance metrics with Prometheus export support.
"""

import time
from typing import Dict, Optional, Callable
from dataclasses import dataclass, field
from threading import Lock


@dataclass
class MetricValue:
    """Single metric value with metadata."""
    name: str
    value: float
    timestamp: float
    labels: Dict[str, str] = field(default_factory=dict)
    metric_type: str = "gauge"  # gauge, counter, histogram


class MetricsCollector:
    """
    Collect and export performance metrics.
    
    Features:
        - Gauge, counter, and histogram metrics
        - Labels for multi-dimensional data
        - Prometheus exposition format
        - Thread-safe updates
    """
    
    def __init__(self):
        self._metrics: Dict[str, MetricValue] = {}
        self._lock = Lock()
        self._histograms: Dict[str, list] = {}
        self._http_server = None
        self._http_thread = None
    
    def _key(self, name: str, labels: Dict[str, str]) -> str:
        """Create unique key from name and labels."""
        label_str = ','.join(f'{k}={v}' for k, v in sorted(labels.items()))
        return f"{name}{{{label_str}}}"
    
    def set_gauge(
        self,
        name: str,
        value: float,
        labels: Optional[Dict[str, str]] = None
    ) -> None:
        """
        Set a gauge metric (can go up or down).
        
        Args:
            name: Metric name
            value: Current value
            labels: Optional labels
        """
        labels = labels or {}
        key = self._key(name, labels)
        
        with self._lock:
            self._metrics[key] = MetricValue(
                name=name,
                value=value,
                timestamp=time.time(),
                labels=labels,
                metric_type="gauge"
            )
    
    def increment_counter(
        self,
        name: str,
        value: float = 1.0,
        labels: Optional[Dict[str, str]] = None
    ) -> None:
        """
        Increment a counter metric (only goes up).
        
        Args:
            name: Metric name
            value: Amount to increment
            labels: Optional labels
        """
        labels = labels or {}
        key = self._key(name, labels)
        
        with self._lock:
            if key in self._metrics:
                self._metrics[key].value += value
                self._metrics[key].timestamp = time.time()
            else:
                self._metrics[key] = MetricValue(
                    name=name,
                    value=value,
                    timestamp=time.time(),
                    labels=labels,
                    metric_type="counter"
                )
    
    def observe_histogram(
        self,
        name: str,
        value: float,
        labels: Optional[Dict[str, str]] = None
    ) -> None:
        """
        Record a histogram observation.
        
        Args:
            name: Metric name
            value: Observed value
            labels: Optional labels
        """
        labels = labels or {}
        key = self._key(name, labels)
        
        with self._lock:
            if key not in self._histograms:
                self._histograms[key] = []
            self._histograms[key].append(value)
            
            # Keep last 1000 observations
            if len(self._histograms[key]) > 1000:
                self._histograms[key] = self._histograms[key][-1000:]
    
    def get_gauge(
        self,
        name: str,
        labels: Optional[Dict[str, str]] = None
    ) -> Optional[float]:
        """Get current gauge value."""
        labels = labels or {}
        key = self._key(name, labels)
        with self._lock:
            if key in self._metrics:
                return self._metrics[key].value
        return None
    
    def get_histogram_stats(
        self,
        name: str,
        labels: Optional[Dict[str, str]] = None
    ) -> Optional[Dict[str, float]]:
        """Get histogram statistics."""
        labels = labels or {}
        key = self._key(name, labels)
        
        with self._lock:
            if key not in self._histograms or not self._histograms[key]:
                return None
            
            values = sorted(self._histograms[key])
            n = len(values)
            
            return {
                'count': n,
                'sum': sum(values),
                'min': values[0],
                'max': values[-1],
                'mean': sum(values) / n,
                'p50': values[n // 2],
                'p95': values[int(n * 0.95)] if n >= 20 else values[-1],
                'p99': values[int(n * 0.99)] if n >= 100 else values[-1],
            }
    
    def to_prometheus(self) -> str:
        """
        Export metrics in Prometheus exposition format.
        
        Returns:
            Prometheus-formatted metrics string
        """
        lines = []
        
        with self._lock:
            # Regular metrics
            for key, metric in self._metrics.items():
                labels = ','.join(f'{k}="{v}"' for k, v in metric.labels.items())
                if labels:
                    line = f'{metric.name}{{{labels}}} {metric.value}'
                else:
                    line = f'{metric.name} {metric.value}'
                lines.append(line)
            
            # Histogram summaries
            for key, values in self._histograms.items():
                if not values:
                    continue
                
                # Extract name from key
                name = key.split('{')[0]
                n = len(values)
                sorted_vals = sorted(values)
                
                lines.append(f'{name}_count {n}')
                lines.append(f'{name}_sum {sum(values)}')
                lines.append(f'{name}{{quantile="0.5"}} {sorted_vals[n // 2]}')
                lines.append(f'{name}{{quantile="0.95"}} {sorted_vals[int(n * 0.95)] if n >= 20 else sorted_vals[-1]}')
                lines.append(f'{name}{{quantile="0.99"}} {sorted_vals[int(n * 0.99)] if n >= 100 else sorted_vals[-1]}')
        
        return '\n'.join(lines)
    
    def snapshot(self) -> Dict[str, float]:
        """
        Return a plain {metric_key: value} dict of all current gauges/counters
        plus histogram means — suitable for folding into a status broadcast (P5.2).
        """
        out: Dict[str, float] = {}
        with self._lock:
            for key, metric in self._metrics.items():
                out[key] = metric.value
            for key, values in self._histograms.items():
                if values:
                    name = key.split('{')[0]
                    out[f"{name}_mean"] = sum(values) / len(values)
        return out

    def reset(self) -> None:
        """Clear all metrics."""
        with self._lock:
            self._metrics.clear()
            self._histograms.clear()

    # ------------------------------------------------------------------ #
    # Prometheus exposition endpoint                                      #
    # ------------------------------------------------------------------ #
    def start_http_exporter(self, port: int = 8000) -> bool:
        """Serve to_prometheus() over HTTP GET /metrics (and /).

        This is what makes monitoring.prometheus_port a real setting — the
        exposition format existed but nothing ever served it. Failure to bind
        (port taken) is logged and non-fatal; metrics still reach the UI via
        the status broadcast.
        """
        if self._http_server is not None:
            return True

        import threading
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

        collector = self

        class _Handler(BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802 (stdlib API name)
                if self.path.split('?')[0] not in ('/', '/metrics'):
                    self.send_response(404)
                    self.end_headers()
                    return
                body = collector.to_prometheus().encode('utf-8')
                self.send_response(200)
                self.send_header('Content-Type',
                                 'text/plain; version=0.0.4; charset=utf-8')
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, fmt, *args):
                pass  # keep scrape noise out of the server console

        try:
            self._http_server = ThreadingHTTPServer(('0.0.0.0', port), _Handler)
        except OSError as e:
            print(f"Metrics exporter failed to bind port {port}: {e}")
            self._http_server = None
            return False

        self._http_thread = threading.Thread(
            target=self._http_server.serve_forever, daemon=True)
        self._http_thread.start()
        return True

    def stop_http_exporter(self) -> None:
        """Shut down the exposition endpoint (idempotent)."""
        server = self._http_server
        if server is None:
            return
        self._http_server = None
        try:
            server.shutdown()
            server.server_close()
        except Exception:
            pass
        if self._http_thread:
            self._http_thread.join(timeout=2.0)
            self._http_thread = None


# Standard metric names
METRIC_PACKETS_RECEIVED = "optical_radar_packets_received_total"
METRIC_PACKETS_PROCESSED = "optical_radar_packets_processed_total"
METRIC_AUTH_FAILURES = "optical_radar_auth_failures_total"
METRIC_PROCESSING_TIME = "optical_radar_processing_time_seconds"
METRIC_ACTIVE_TRACKS = "optical_radar_active_tracks"
METRIC_CAMERA_HEALTH = "optical_radar_camera_health"
METRIC_CALIBRATION_SCORE = "optical_radar_calibration_score"
METRIC_VOXEL_UPDATE_TIME = "optical_radar_voxel_update_time_seconds"


# Global metrics instance
_metrics: Optional[MetricsCollector] = None


def get_metrics() -> MetricsCollector:
    """Get global metrics collector."""
    global _metrics
    if _metrics is None:
        _metrics = MetricsCollector()
    return _metrics


class Timer:
    """Context manager for timing code blocks."""
    
    def __init__(self, metric_name: str, labels: Optional[Dict[str, str]] = None):
        self.metric_name = metric_name
        self.labels = labels
        self.start_time = 0.0
    
    def __enter__(self):
        self.start_time = time.perf_counter()
        return self
    
    def __exit__(self, *args):
        duration = time.perf_counter() - self.start_time
        get_metrics().observe_histogram(self.metric_name, duration, self.labels)
