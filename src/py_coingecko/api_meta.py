import json
import os
import re
import urllib.parse as urlparse
from urllib.parse import urlencode
from copy import copy

from dotenv import load_dotenv

load_dotenv()


RAW_SPEC_PATH = os.environ["RAW_SPEC_PATH"]
FORMATTED_SPEC_PATH = os.environ["FORMATTED_SPEC_PATH"]
DIFF_SPEC_PATH = os.environ["DIFF_SPEC_PATH"]
SWAGGER_CLIENT_PATH = os.environ["SWAGGER_CLIENT_PATH"]
SWAGGER_CLIENT_NAME = os.environ["SWAGGER_CLIENT_NAME"]
SWAGGER_API_CLIENT_PATH = os.environ["SWAGGER_API_CLIENT_PATH"]
SWAGGER_DATA_PATH = os.environ["SWAGGER_DATA_PATH"]
URL_TO_METHOD_PATH = os.environ["URL_TO_METHOD_PATH"]
TEST_API_CALLS_PATH = os.environ["TEST_API_CALLS_PATH"]
TEST_API_RESPONSES_PATH = os.environ["TEST_API_RESPONSES_PATH"]
SWAGGER_API_DOCS_PATH = os.environ["SWAGGER_API_DOCS_PATH"]
PROCESSED_DOCS_PATH = os.environ["PROCESSED_DOCS_PATH"]
SPEC_CHECK = True


class ApiMeta:

    """GENERIC I/O"""

    def read(self, path, is_json=True):
        with open(path, "r") as f:
            data = f.read()
            if is_json:
                data = json.loads(data)
        return data

    def write(self, path, data, is_json=True):
        with open(path, "w") as f:
            if is_json:
                data = json.dumps(data, indent=4)
            f.write(data)

    """ READS """

    def get_spec_raw(self):
        return self.read(RAW_SPEC_PATH)

    def get_spec_processed(self):
        return self.read(FORMATTED_SPEC_PATH)

    def get_docs_generated(self):
        return self.read(SWAGGER_API_DOCS_PATH, is_json=False)

    def get_api_client_source_code(self):
        return self.read(SWAGGER_API_CLIENT_PATH, is_json=False)

    def get_test_api_calls(self):
        return self.read(TEST_API_CALLS_PATH)

    def get_url_to_method(self):
        return self.read(URL_TO_METHOD_PATH)

    def get_test_api_responses(self):
        return self.read(TEST_API_RESPONSES_PATH)

    """ WRITES """

    def write_spec_processed(self, spec):
        self.write(FORMATTED_SPEC_PATH, spec)

    def write_spec_diff(self, diff):
        self.write(DIFF_SPEC_PATH, diff, is_json=False)

    def write_docs_processed(self, text):
        self.write(PROCESSED_DOCS_PATH, text, is_json=False)

    def write_url_to_method(self, url_to_method):
        self.write(URL_TO_METHOD_PATH, url_to_method)

    def write_test_api_calls(self, test_api_calls):
        self.write(TEST_API_CALLS_PATH, test_api_calls)

    def write_test_api_responses(self, test_api_responses):
        self.write(TEST_API_RESPONSES_PATH, test_api_responses)

    """ OTHER """

    def get_parameters(self, url_template):
        spec = self.get_spec_processed()
        return spec["paths"][url_template]["get"].get("parameters", [])

    def get_url_base(self):
        spec = self.get_spec_processed()
        host = spec["host"]
        basePath = spec["basePath"]
        schemes = spec["schemes"]
        assert len(schemes) == 1
        scheme = schemes[0]
        url_parts = [scheme, host, basePath, "", "", ""]
        url = urlparse.urlunparse(url_parts)
        return url

    def get_api_method_names(self):
        return list(self.get_url_to_method().values())

    def get_paginated_method_names(self):
        url_to_methods = self.get_url_to_method()
        paged_method_names = list()
        for url_template, method_name in url_to_methods.items():
            params = filter(
                lambda p: p["name"] in ["page", "per_page"],
                self.get_parameters(url_template),
            )
            if len(list(params)) == 2:
                paged_method_names.append(method_name)
        return paged_method_names

    def materialize_url_template(self, url_template, path_args, query_args):
        """Converts url template to url to request from api by adding prefix and encoding
        path and query args.

        input:
            url_template = "/coins/{id}/contract/{contract_address}/market_chart/range"
            path_args = ["ethereum", "0x1f9840a85d5aF5bf1D1762F925BDADdC4201F984"]
            query_args = {
                "vs_currency": "eur",
                "from": "1622520000",
                "to": "1638334800"
            }

        output:
            https://api.coingecko.com/api/v3/coins/ethereum/contract/0x1f9840a85d5aF5bf1D1762F925BDADdC4201F984/market_chart/range?vs_currency=eur&from=1622520000&to=1638334800
        """
        url_base = api_meta.get_url_base()
        url_base_parts = list(urlparse.urlparse(url_base))
        # transform /coins/{id}/contract/{contract_address} ---> /coins/{0}/contract/{1}
        path_tokens = re.findall(r"({[^}]*})", url_template)
        url = url_template
        for i, p in enumerate(path_tokens):
            url = url.replace(p, "{" + str(i) + "}")
        # construct full url
        url_parts = list(urlparse.urlparse(url))
        url_parts[0] = url_base_parts[0]
        url_parts[1] = url_base_parts[1]
        # add path_args to path
        url_parts[2] = url_base_parts[2] + url.format(*path_args)
        # add query_args as query string parameters
        query = dict(urlparse.parse_qsl(url_parts[4]))
        query.update(query_args)
        url_parts[4] = urlencode(query)
        url = urlparse.urlunparse(url_parts)
        return url

    def transform_path_query_to_args_kwargs(self, url_template, path_args, query_args):
        """converts set of path_args and query_args to set of args and kwargs
        passed to client api functions.

        - all path args are args
        - query args that required are args
        - query args that are optional are kwargs

        Order matters here
        """
        params = self.get_parameters(url_template)
        args = copy(path_args)
        kwargs = copy(query_args)
        for p in params:
            if p["required"] and p["in"] == "query":
                name = p["name"]
                args.append(kwargs[name])
                del kwargs[name]
        return args, kwargs


api_meta = ApiMeta()