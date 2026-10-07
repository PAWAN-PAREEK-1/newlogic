"""Load AWS credentials as environmental variable"""

from pathlib import Path
import os
from dotenv.main import load_dotenv

dotenv_path = Path("uploads/.env")
load_dotenv(dotenv_path=dotenv_path)
ACCESS_KEY = os.getenv("ACCESS_KEY")
SECRET_KEY = os.getenv("SECRET_KEY")

BUCKET_NAME = ""
