FROM ghcr.io/home-assistant/home-assistant:2026.9.0

# The library is mounted at /workspace and imported from source during development.
ENV PYTHONPATH=/workspace

# Run hass directly (no s6 supervision needed for development) and skip pip for the
# library that is provided via PYTHONPATH.
ENTRYPOINT ["python3", "-m", "homeassistant"]
CMD ["--config", "/config", "--skip-pip-packages", "pyklyqa-pet"]
