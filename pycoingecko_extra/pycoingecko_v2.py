import time
import math
import logging
import requests
import itertools
import json
import requests 
from typing import List, Set
from collections import defaultdict, deque
from functools import partial
from contextlib import contextmanager
from requests.adapters import HTTPAdapter
from requests.packages.urllib3.util.retry import Retry

from client.swagger_client import ApiClient as ApiClientSwagger 
from client.swagger_client.api import CoingeckoApi as CoinGeckoApiSwagger

from pycoingecko_extra.utils import without_keys, dict_get
from scripts.utils import get_url_base, materialize_url_template
from scripts.swagger import get_api_method_names

logging.basicConfig()
logger = logging.getLogger("CoinGeckoAPIExtra")

RATE_LIMIT_STATUS_CODE = 429

error_msgs = dict(
    exp_limit_reached="Waited for maximum specified time but was still rate limited. Try increasing exp_limit. Queued calls are retained."
)

class CoinGeckoAPIClient(ApiClientSwagger):

    def __init__(self):
        super().__init__()
        # setup HTTP session  
        self.request_timeout = 120
        self.session = requests.Session()
        retries = Retry(total=5, backoff_factor=0.5, status_forcelist=[502, 503, 504])
        self.session.mount('https://', HTTPAdapter(max_retries=retries)) 
        self._include_resp = False

    @contextmanager
    def _include_response(self):
        """Context manager that allows for chaning the return value structure of api calls when necessary

        The main use case for this is for page range queries, where we need the raw response object to be returned from the
        api client. The base api client does not support this so _CoinGeckoAPI__request was overridden.
        """
        self._include_resp = True
        yield
        self._include_resp = False

    def call_api(
        self, 
        resource_path, 
        method,
        path_params,
        query_params,
        header_params,
        **kwargs 
    ):
        args = list(path_params.values()) # dictionaries are ordered from python 3.6 on so this is fine. 
        kwargs = {v[0]: v[1] for v in query_params} 
        url = materialize_url_template(resource_path, args, kwargs)
        logger.debug(f"HTTPS Request: {url}")
        assert method == "GET"
        try:
            response = self.session.get(url, timeout=self.request_timeout)
        except requests.exceptions.RequestException:
            raise
        try:
            response.raise_for_status()
            content = json.loads(response.content.decode("utf-8"))
            if self._include_resp:
                return content, response
            else:
                return content
        except Exception as e:
            try:
                content = json.loads(response.content.decode("utf-8"))
                raise ValueError(content)
            except json.decoder.JSONDecodeError:
                pass
            raise


class CoinGeckoAPI(CoinGeckoApiSwagger):

    defaults = dict(exp_limit=8, progress_interval=10, log_level=logging.INFO)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, api_client=CoinGeckoAPIClient(), **without_keys(kwargs, self.defaults.keys()))
        # ensure that we don't override any methods from the base class, except call_api
        # setup wrapper instance fields, for managing queued calls, rate limit behavior, page range queries
        self._reset_state()
        for k, v in self.defaults.items():
            setattr(self, k, kwargs.get(k) or v)
        logger.setLevel(self.log_level)
        # decorate bound methods on base class that correspond to api calls to enable
        # queueing and page range query support for page range query enabled functions
        method_names = get_api_method_names()
        for name in method_names: 
            v = getattr(self, name)
            page_range_query = False # TODO: enable pagination support
            logger.debug(
                f"Decorating: {name:60} page_range_query: {page_range_query}"
            )
            setattr(
                self, name, partial(self._wrap_api_endpoint, v, page_range_query)
            )

    def _validate_page_range(self, page_start, page_end) -> None:
        """Validates user supplied values for page_start and page_end"""
        if not page_start:
            raise ValueError("page_start must be defined")
        if not isinstance(page_start, int):
            raise ValueError("page_start must be int")
        if page_end is not None and not isinstance(page_end, int):
            raise ValueError("page_end was specified but was not an int")
        if page_end is not None and page_end < page_start:
            raise ValueError(f"page_end: {page_end} less than page_start: {page_start}")
        if page_start <= 0:
            raise ValueError(f"page_start: {page_start} was less than or equal to 0")
        if page_end is not None and page_end <= 0:
            raise ValueError(f"page_end: {page_end} was less than or equal to 0")

    def _reset_state(self) -> None:
        """Resets internal state. State is used to support the following functionality
        - queuing
        - page range queries
        - structure of retrurn value from api requests
        """
        self._include_resp = False
        self._queued_calls = defaultdict(list)
        self._page_range_qids = list()
        self._inferpage_end_qids = list()
        logger.debug("Resetting state")

    def _queue_single(self, qid, fn, dup_check, *args, **kwargs) -> None:
        """Queue a single API call. Optionally perform a duplicate check to see if qid is being overwritten"""
        if dup_check and qid in self._queued_calls:
            logger.warning(
                f"Warning: multiple calls queued with identical qid: {qid}. Most recent call will overwrite old call."
            )
        self._queued_calls[qid].append((fn, args, kwargs))

    def _impute_page_range_calls(self):
        """Finds each queued call that is a page range query where page_start is defined and page_end is not included.
        Executes each of these calls to get an HTTP header back containing information on how many pages exist. With
        this information, we queue the remainder of calls. We cache the result of the call we already executed in
        res_cache and return this value.
        """
        res_cache = dict()
        is_page_range_query = True
        include_response = True
        for qid in self._inferpage_end_qids:
            call_list = self._queued_calls[qid]
            if len(call_list) != 1:
                raise ValueError(
                    "Implementation error. inferpage_end was true but more than one call in call_list"
                )
            fn, args, kwargs = call_list[0]
            page_start = kwargs["page"]
            res, response = self._execute_single(
                {}, is_page_range_query, include_response, qid, fn, *args, **kwargs
            )
            res_cache[(qid, page_start)] = res
            per_page = int(response.headers["Per-Page"])
            total = int(response.headers["Total"])
            page_end = math.ceil(total / per_page)
            logger.debug(
                f"page range query: {qid} page_start: {page_start:4} page_end: {page_end:4} per_page: {per_page:4} total: {total}"
            )
            # note: we already queued a request for page_start so we begin at page_start + 1
            logger.debug(f"queueing page: {page_start}")
            for page in range(page_start + 1, page_end + 1):
                logger.debug(f"queueing page: {page}")
                self._queue_single(qid, fn, False, *args, **{**kwargs, "page": page})
        return res_cache

    def _execute_single(
        self, res_cache, is_page_range_query, include_response, qid, fn, *args, **kwargs
    ):
        """Execute a single API call with exponential backoff retries to deal with server side rate limiting.

        - Results in a maximum of exp_limit + 1 request attempts.
        - Checks res_cache prior to making call to see if we cached result for this call during the imputation
        of page range query calls.
        """
        exp = 0
        if is_page_range_query:
            res = res_cache.get((qid, kwargs["page"]), None)
        else:
            res = None
        while res is None and exp < self.exp_limit + 1:
            try:
                if include_response:
                    with self.api_client._include_response():
                        res, response = fn(*args, **kwargs)
                    return res, response
                else:
                    res = fn(*args, **kwargs)
                    return res
            except requests.exceptions.ConnectionError:
                # this is a subclass of requests.exceptions.RequestException that is a failure condition
                raise
            except requests.exceptions.RequestException as e:
                if e.response.status_code == RATE_LIMIT_STATUS_CODE:
                    secs = 2 ** exp
                    logger.info(f"Rate limited: sleeping {secs} seconds")
                    time.sleep(secs)
                    exp += 1
                else:
                    # Any non 429 http respose error code is a failure condition
                    raise e
        if exp == self.exp_limit + 1:
            raise Exception(error_msgs["exp_limit_reached"])
        return res

    def _execute_queued(self):
        """Execute all queued calls

        - Prior to execution, we impute calls for page range queries
        - Logs progress at configurable intervals
        """
        # impute calls related to page range queries where page_end is not specified
        res_cache = self._impute_page_range_calls()
        # execute all queued calls
        results = {qid: list() for qid in self._page_range_qids}
        last_progress = 0
        call_count = 0
        num_calls = sum([len(v) for v in self._queued_calls.values()])
        include_response = False
        logger.info(f"Begin executing {num_calls} queued calls")
        for (qid, call_list) in self._queued_calls.items():
            call_list = deque(call_list)
            is_page_range_query = qid in self._page_range_qids
            for fn, args, kwargs in call_list:
                # make api call (with retries)
                res = self._execute_single(
                    res_cache,
                    is_page_range_query,
                    include_response,
                    qid,
                    fn,
                    *args,
                    **kwargs,
                )
                # store the result in our results cache
                if is_page_range_query:
                    results[qid].append(res)
                else:
                    results[qid] = res
                # log progress
                call_count += 1
                progress = call_count / num_calls * 100
                next_progress = last_progress + self.progress_interval
                if progress >= next_progress:
                    logger.info(f"Progress: {math.floor(progress)}%")
                    last_progress = progress
        return results

    def _queue_page_range_query(self, qid, fn, *args, **kwargs) -> None:
        page, page_start, page_end = dict_get(kwargs, "page", "page_start", "page_end")
        kwargs = without_keys(kwargs, ["page_start", "page_end"])
        if not (page or page_start or page_end) or page:
            # 1. paged endpoint but no paging arguments specified (api uses default of page 1)
            # 2. paged endpoint and single page specified (supported by base api client)
            self._queue_single(qid, fn, True, *args, **kwargs)
        else:
            # one or more of page_start and page_end is defined
            self._validate_page_range(page_start, page_end)
            # mark this qid as representing a page range query
            self._page_range_qids.append(qid)
            # queue a single call per page in range
            if page_end:
                for i, page in enumerate(range(page_start, page_end + 1)):
                    # all queued requests after first are allowed to have same qid, as they are part of a page range query
                    dup_check = i == 0
                    self._queue_single(qid, fn, dup_check, *args, page=page, **kwargs)
            else:
                # when only page_start is specified, we want to queue a request for all available pages
                # this can only be determined at execution time so we queue a single request now and the
                # rest will be queued as a part of execute_many
                self._queue_single(qid, fn, True, *args, page=page_start, **kwargs)
                self._inferpage_end_qids.append(qid)

    def _wrap_api_endpoint(self, fn, page_range_query, *args, **kwargs):
        """Decorator that will be applied to all API endpoints on base class. Adds support for method queueing
        and page range queries.
        """
        qid = kwargs.get("qid")
        if qid:
            qid = str(qid)
            kwargs = without_keys(kwargs, ["qid"])
            if page_range_query:
                self._queue_page_range_query(qid, fn, *args, **kwargs)
            else:
                self._queue_single(qid, fn, True, *args, **kwargs)
        else:
            return fn(*args, **kwargs)

    def execute_queued(self):
        try:
            results = self._execute_queued()
        except BaseException:
            raise
        finally:
            self._reset_state()
        return results
