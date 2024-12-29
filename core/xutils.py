# homeassistant/components/ewelink/utils.py

import hashlib
import os
from typing import List, Union

from homeassistant.core import HomeAssistant


def source_hash() -> str:
    """Calculate and return a short MD5 hash of all Python source files in the integration's directory.

    Returns:
        str: A 7-character MD5 hash of the Python files' content in the integration directory.
    """
    if source_hash.__doc__:
        return source_hash.__doc__

    try:
        # Initialize MD5 hasher
        hasher = hashlib.md5()
        base_path = os.path.dirname(os.path.dirname(__file__))

        # Walk through the directory structure
        for root, dirs, files in os.walk(base_path):
            dirs.sort()
            for file_name in sorted(files):
                if not file_name.endswith(".py"):
                    continue
                file_path = os.path.join(root, file_name)
                with open(file_path, "rb") as file:
                    hasher.update(file.read())

        # Generate and cache the hash in the function's docstring
        source_hash.__doc__ = hasher.hexdigest()[:7]
        return source_hash.__doc__

    except Exception as exc:
        # Return the exception as a string in case of an error
        return repr(exc)


def system_log_records(hass: HomeAssistant, domain: str) -> Union[List[dict], str]:
    """Retrieve system log records filtered by a specific domain.

    Args:
        hass (HomeAssistant): The Home Assistant instance.
        domain (str): The domain to filter log records.

    Returns:
        Union[List[dict], str]: A list of log entries as dictionaries or an error message string.
    """
    try:
        # Filter system log records by domain
        return [
            entry.to_dict()
            for key, entry in hass.data["system_log"].records.items()
            if domain in str(key)
        ]
    except Exception as exc:
        # Return the exception as a string in case of an error
        return str(exc)

