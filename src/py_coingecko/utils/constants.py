import os 
from dotenv import load_dotenv

load_dotenv()

POETRY_PROJECT_FILE_PATH    = os.environ["POETRY_PROJECT_FILE_PATH"]
RAW_SPEC_PATH               = os.environ["RAW_SPEC_PATH"]
FORMATTED_SPEC_PATH         = os.environ["FORMATTED_SPEC_PATH"]
DIFF_SPEC_PATH              = os.environ["DIFF_SPEC_PATH"]
SWAGGER_CLIENT_PATH         = os.environ["SWAGGER_CLIENT_PATH"]
SWAGGER_CLIENT_NAME         = os.environ["SWAGGER_CLIENT_NAME"]
SWAGGER_API_CLIENT_PATH     = os.environ["SWAGGER_API_CLIENT_PATH"]
SWAGGER_REQUIREMENTS_PATH   = os.environ["SWAGGER_REQUIREMENTS_PATH"]
SWAGGER_DATA_PATH           = os.environ["SWAGGER_DATA_PATH"]
URL_TO_METHOD_PATH          = os.environ["URL_TO_METHOD_PATH"]
TEST_API_CALLS_PATH         = os.environ["TEST_API_CALLS_PATH"]
TEST_API_RESPONSES_PATH     = os.environ["TEST_API_RESPONSES_PATH"]
SWAGGER_API_DOCS_PATH       = os.environ["SWAGGER_API_DOCS_PATH"]
PROCESSED_DOCS_PATH         = os.environ["PROCESSED_DOCS_PATH"]