import os

# Server socket
bind = f"0.0.0.0:{os.getenv('PORT', '5000')}"
backlog = 512  # Increase backlog to handle more connections

# Worker processes
workers = int(os.getenv('GUNICORN_WORKERS', '1'))   # Number of worker parallel processes
worker_class = "sync"
worker_connections = 500   # Maximum number of simultaneous clients per worker
timeout = 900  # Increased timeout to 15 minutes for video downloads - allow longer downloads 
keepalive = 2   # Keepalive for persistent connections

# Restart workers after this many requests, to help with memory leaks
max_requests = 500
max_requests_jitter = 50

# Logging - log to console (visible in Render)
loglevel = os.getenv('GUNICORN_LOG_LEVEL', 'warning')
accesslog = None  # Log to stdout
errorlog = '-'   # Log to stderr
capture_output = True   # Capture stdout/stderr in error log
access_log_format = '%(h)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s" %(D)s'

# Memory optimization for free plan
preload_app = True  # Preload app to reduce memory usage. Share memory between workers
worker_tmp_dir = "/dev/shm"  # Use shared memory if available

# Process naming
proc_name = 'youtube-downloader-api'

# Server mechanics
daemon = False  # Run in the foreground (not as a daemon)
pidfile = None
user = None     # Run as the current user
group = None    # Run as the current group
tmp_upload_dir = None

# Disable access logging to reduce I/O
disable_redirect_access_to_syslog = True

# SSL (if needed)
keyfile = None
certfile = None