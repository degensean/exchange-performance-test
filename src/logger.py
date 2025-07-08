"""
Logging configuration for the exchange performance testing framework
"""
import logging
import sys
from pathlib import Path
from datetime import datetime
import os

def setup_logging(log_level: str | None = None, log_to_file: bool | None = None, log_dir: str | None = None) -> logging.Logger:
    """
    Set up logging configuration for the application
    
    Args:
        log_level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL). If None, reads from LOG_LEVEL env var
        log_to_file: Whether to log to file in addition to console. If None, reads from LOG_TO_FILE env var
        log_dir: Directory to store log files. If None, reads from LOG_DIR env var
    
    Returns:
        Configured logger instance
    """
    # Read from environment variables if not provided as parameters
    if log_level is None:
        log_level = os.getenv("LOG_LEVEL", "INFO").split('#')[0].strip()  # Remove comments
    if log_to_file is None:
        log_to_file = os.getenv("LOG_TO_FILE", "true").split('#')[0].strip().lower() == "true"
    if log_dir is None:
        log_dir = os.getenv("LOG_DIR", "logs").split('#')[0].strip()
    
    # Create logs directory if it doesn't exist
    if log_to_file:
        Path(log_dir).mkdir(exist_ok=True)
    
    # Configure root logger
    logger = logging.getLogger("exchange_performance")
    logger.setLevel(getattr(logging, log_level.upper()))
    
    # Clear any existing handlers
    logger.handlers.clear()
    
    # Create formatter
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    # Console handler (use stderr to avoid conflicts with Rich Live display)
    console_handler = logging.StreamHandler(sys.stderr)
    console_handler.setLevel(getattr(logging, log_level.upper()))  # Use same level as main logger
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)
    
    # File handler (if enabled)
    if log_to_file:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        log_file = Path(log_dir) / f"exchange_performance_{timestamp}.log"
        
        # Use UTF-8 encoding to handle international characters
        file_handler = logging.FileHandler(log_file, encoding='utf-8')
        file_handler.setLevel(getattr(logging, log_level.upper()))
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
        
        logger.info(f"Logging to file: {log_file}")
    
    return logger

def get_logger(name: str | None = None) -> logging.Logger:
    """Get a logger instance with the specified name"""
    if name:
        return logging.getLogger(f"exchange_performance.{name}")
    return logging.getLogger("exchange_performance")
