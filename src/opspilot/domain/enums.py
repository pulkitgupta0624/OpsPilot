"""Shared domain enumerations."""

from enum import StrEnum


class FaultType(StrEnum):
    MEMORY_LEAK = "memory_leak"
    DB_POOL_EXHAUSTION = "db_pool_exhaustion"
    SLOW_DEPENDENCY = "slow_dependency"
    BAD_DEPLOYMENT = "bad_deployment"
    DISK_FULL = "disk_full"


class DecoyType(StrEnum):
    HARMLESS_DEPLOYMENT = "harmless_deployment"
    TRANSIENT_BLIP = "transient_blip"
    TRAFFIC_SPIKE = "traffic_spike"


class ActionType(StrEnum):
    RESTART_SERVICE = "restart_service"
    ROLLBACK_DEPLOYMENT = "rollback_deployment"
    SCALE_OUT = "scale_out"
    CLEAR_DISK = "clear_disk"
    CLEAR_DISK_SPACE = "clear_disk_space"
    INCREASE_DB_POOL = "increase_db_pool"
    ENABLE_CIRCUIT_BREAKER = "enable_circuit_breaker"

