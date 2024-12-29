"""Wrapper."""
import logging

import aiohttp

_LOGGER = logging.getLogger(__name__)

class LoggingSession:
    """Wrapper for aiohttp.ClientSession to log requests and responses."""

    def __init__(self, session: aiohttp.ClientSession) ->None:
        """Initialize with an existing aiohttp ClientSession."""
        self._session = session

    async def get(self, url, **kwargs):
        """Perform a GET request and log the details."""
        _LOGGER.error(f"Sending GET request to: {url}")  # Log the URL being requested  # noqa: G004
        response = await self._session.get(url, **kwargs)
        _LOGGER.error(f"Received response: {response.status}")  # Log the response status # noqa: G004
        response_text = await response.text()
        _LOGGER.error(f"Response body: {response_text}")  # Log the response body # noqa: G004
        return response

    async def post(self, url, data=None, json=None, **kwargs):
        """Perform a POST request and log the details."""
        _LOGGER.error(f"Sending POST request to: {url}")  # Log the URL being requested # noqa: G004
        if json is not None:
            _LOGGER.error(f"Request JSON data: {json}")  # Log JSON data if provided # noqa: G004
        elif data is not None:
            _LOGGER.error(f"Request data: {data}")  # Log form data if provided# noqa: G004

        response = await self._session.post(url, data=data, json=json, **kwargs)
        _LOGGER.error(f"Received response: {response.status}")  # Log the response status# noqa: G004
        response_text = await response.text()
        _LOGGER.error(f"Response body: {response_text}")  # Log the response body # noqa: G004
        return response


