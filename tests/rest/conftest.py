import contextlib
import re
import time
import typing
from typing import List
from unittest import mock

import pytest
import time_machine

from openeo.rest.connection import Connection

API_URL = "https://oeo.test/"


@pytest.fixture(params=["1.0.0"])
def api_version(request):
    return request.param


class _Sleeper:
    def __init__(self):
        self.history = []

    @contextlib.contextmanager
    def patch(self, time_machine: time_machine.TimeMachineFixture) -> typing.Iterator["_Sleeper"]:
        def sleep(seconds):
            # Note: this requires that `time_machine.move_to()` has been called before
            # also see https://github.com/adamchainz/time-machine/issues/247
            time_machine.coordinates.shift(seconds)
            self.history.append(seconds)

        with mock.patch("time.sleep", new=sleep):
            yield self

    def did_sleep(self) -> bool:
        return len(self.history) > 0


@pytest.fixture
def fast_sleep(time_machine) -> typing.Iterator[_Sleeper]:
    """
    Fixture using `time_machine` to make `sleep` instant and update the current time.
    """
    with _Sleeper().patch(time_machine=time_machine) as sleeper:
        yield sleeper


@pytest.fixture
def simple_time(time_machine, fast_sleep):
    """Fixture to set up simple time stepping (and fast sleep) with `time_machine`."""
    time_machine.move_to(1000, tick=False)


@pytest.fixture
def oidc_device_code_flow_checker(time_machine, simple_time, fast_sleep, capsys):
    """Fixture to create a context manager that checks for OIDC device code flow (sleep calls, instruction printing)"""

    @contextlib.contextmanager
    def assert_oidc_device_code_flow(url: str = "https://oidc.test/dc", elapsed: float = 3, check_capsys: bool = True):
        start = time_machine.coordinates.time()
        yield
        assert fast_sleep.did_sleep()
        if check_capsys:
            stdout, _ = capsys.readouterr()
            assert f"Visit {url} and enter" in stdout
            assert re.search(r"\[#+-*\] Authorization pending *\r\[#+-*\] Polling *\r", stdout)
            assert re.search(r"\[#+-*\] Authorized successfully *\r\n", stdout)
        assert time_machine.coordinates.time() - start >= elapsed

    return assert_oidc_device_code_flow


@pytest.fixture
def con120(requests_mock):
    requests_mock.get(API_URL, json={"api_version": "1.2.0"})
    con = Connection(API_URL)
    return con
