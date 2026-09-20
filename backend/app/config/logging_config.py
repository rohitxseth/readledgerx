import logging
import colorlog


class MultiColorFormatter(colorlog.ColoredFormatter):
    def format(self, record):
        timestamp_color = "\033[90m"
        module_color = "\033[36m"
        message_color = "\033[97m"
        reset = "\033[0m"

        level_colors = {
            "DEBUG": "\033[36m",
            "INFO": "\033[32m",
            "WARNING": "\033[33m",
            "ERROR": "\033[31m",
            "CRITICAL": "\033[91m",
        }
        level_color = level_colors.get(record.levelname, "\033[37m")

        timestamp = f"{timestamp_color}{self.formatTime(record, '%H:%M:%S')}{reset}"
        module_name = record.name.split(".")[-1]
        module = f"{module_color}{module_name}{reset}"
        level = f"{level_color}{record.levelname[:4]}{reset}"
        message = f"{message_color}{record.getMessage()}{reset}"

        return f"{timestamp} {level} {module} → {message}"


def setup_logging(level: int = logging.INFO):
    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)

    handler = colorlog.StreamHandler()
    handler.setFormatter(
        MultiColorFormatter(
            datefmt="%H:%M:%S",
            log_colors={
                "DEBUG": "cyan",
                "INFO": "green",
                "WARNING": "yellow",
                "ERROR": "red",
                "CRITICAL": "red,bg_white",
            },
        )
    )
    handler.setLevel(level)
    root_logger.addHandler(handler)
