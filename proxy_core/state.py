import queue

log_queue = queue.Queue()

COOLDOWNS = {}
CONSECUTIVE_429S = {}
LAST_429_TIME = {}
CONSECUTIVE_RPD_429S = {}
LAST_USED = {}
LAST_REQUEST_TIME = {}

# Compactor statistics
COMPACTOR_ORIG_BYTES = 0
COMPACTOR_COMP_BYTES = 0
