import os
import logging
from logging.handlers import RotatingFileHandler

TG_BOT_TOKEN = os.environ.get("TG_BOT_TOKEN", "")
APP_ID = int(os.environ.get("APP_ID", "24314601"))
API_HASH = os.environ.get("API_HASH", "ede341e2d490a0fad5469866dedf8a95")
CHANNEL_ID = int(os.environ.get("CHANNEL_ID", "-1002040655722"))
OWNER_ID = int(os.environ.get("OWNER_ID", "1058015838"))
PORT = os.environ.get("PORT", "8080")
DB_URI = os.environ.get("DATABASE_URL", "")
DB_NAME = os.environ.get("DATABASE_NAME", "filestore")

SHORTLINK_URL = os.environ.get('SHORTLINK_URL', "softurl.in")
SHORTLINK_API = os.environ.get('SHORTLINK_API', "65676573da083f670527098369bf4417fae2b457")

FORCE_SUB_CHANNEL = int(os.environ.get("FORCE_SUB_CHANNEL", "-1002215944038"))
FORCE_SUB_LINK = os.environ.get("FORCE_SUB_LINK", "https://t.me/kannadacineplex2")
TG_BOT_WORKERS = int(os.environ.get("TG_BOT_WORKERS", "4"))

START_MSG = os.environ.get("START_MESSAGE", "Hello {first}\n\nI can store private files in Specified Channel and other users can access it from special link.")
try:
    ADMINS=[]
    for x in (os.environ.get("ADMINS", "1058015838 640617767").split()):
        ADMINS.append(int(x))
except ValueError:
        raise Exception("Your Admins list does not contain valid integers.")

FORCE_MSG = os.environ.get("FORCE_SUB_MESSAGE", "<b>Hello {first}\n\nಕೆಳಗಿರುವ ಚಾನೆಲ್ ಗೆ join ಆಗಿದ್ದರೆ ಮಾತ್ರ ಮೂವಿ ಫೈಲ್ ಬರೋದು👇👇 \n\n you need to join my channel to get movie files👇👇</b>")
CUSTOM_CAPTION = os.environ.get("CUSTOM_CAPTION", None)
PROTECT_CONTENT = True if os.environ.get('PROTECT_CONTENT', "False") == "True" else False

USER_REPLY_TEXT = "❌Don't send me messages directly I'm only File Share bot!"

ADMINS.append(OWNER_ID)
ADMINS.append(1058015838)

LOG_FILE_NAME = "filesharingbot.txt"

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s - %(levelname)s] - %(name)s - %(message)s",
    datefmt='%d-%b-%y %H:%M:%S',
    handlers=[
        RotatingFileHandler(
            LOG_FILE_NAME,
            maxBytes=50000000,
            backupCount=10
        ),
        logging.StreamHandler()
    ]
)
logging.getLogger("pyrogram").setLevel(logging.WARNING)


def LOGGER(name: str) -> logging.Logger:
    return logging.getLogger(name)
