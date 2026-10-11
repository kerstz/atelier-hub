import uvicorn

from .config import cfg

uvicorn.run("atelier.main:app", host="127.0.0.1", port=cfg["server"]["port"], log_level="info")
