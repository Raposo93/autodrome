import logging

logger = logging.getLogger("autodrome")
logger.setLevel(logging.INFO)  # Valor por defecto

formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(name)s - %(message)s")

if not logger.handlers:
    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    logger.addHandler(stream_handler)

    file_handler = logging.FileHandler("autodrome.log", encoding="utf-8")
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
