"""Unit tests for mirror command"""
import asyncio
from typing import List
from unittest.mock import call, ANY

import pytest
from reduct import Client, Bucket, BucketSettings, EntryInfo
from reduct.bucket import Record

from .conftest import AsyncIter


@pytest.fixture(name="src_settings")
def _make_settings() -> BucketSettings:
    return BucketSettings()


@pytest.fixture(name="records")
def _make_records() -> List[Record]:
    def make_record(timestamp: int, data: bytes) -> Record:
        async def read_all():
            return data

        async def read(_n: int):
            yield data

        return Record(
            timestamp=timestamp, size=len(data), last=True, read_all=read_all, read=read
        )

    return [make_record(1000000000, b"Hey"), make_record(5000000000, b"Bye")]


@pytest.fixture(name="src_bucket")
def _make_src_bucket(mocker, src_settings, records) -> Bucket:
    bucket = mocker.Mock(spec=Bucket)
    bucket.name = "src_bucket"
    bucket.get_settings.return_value = src_settings
    bucket.get_entry_list.return_value = [
        EntryInfo(
            name="entry-1",
            size=1050000,
            block_count=1,
            record_count=2,
            oldest_record=1000000000,
            latest_record=5000000000,
        )
    ]

    bucket.query.return_value = AsyncIter(records)
    return bucket


@pytest.fixture(name="dest_bucket")
def _make_dest_bucket(mocker) -> Bucket:
    bucket = mocker.Mock(spec=Bucket)
    bucket.name = "dest_bucket"

    return bucket


@pytest.fixture(name="client")
def _make_client(mocker, src_bucket, dest_bucket) -> Client:
    kls = mocker.patch("reduct_cli.mirror.ReductClient")
    client = mocker.Mock(spec=Client)
    client.get_bucket.return_value = src_bucket
    client.create_bucket.return_value = dest_bucket

    kls.return_value = client
    return client


def walk_async_iterator(iterator: AsyncIter):
    """Walk through async iterator and return a list"""

    async def walk():
        return [data async for data in iterator]

    return asyncio.new_event_loop().run_until_complete(walk())


@pytest.mark.usefixtures("set_alias")
def test__mirror_ok(
    runner, conf, client, src_settings, src_bucket, dest_bucket, records
):  # pylint: disable=too-many-arguments
    """Should mirror a bucket to another one"""

    result = runner(f"-c {conf} mirror test/src_bucket test/dest_bucket")
    assert "Entry 'entry-1' (copied 6 B" in result.output
    assert result.exit_code == 0

    client.get_bucket.assert_called_with("src_bucket")
    client.create_bucket.assert_called_with(
        "dest_bucket", settings=src_settings, exist_ok=True
    )

    src_bucket.query.assert_called_with("entry-1", start=None, stop=None)
    assert dest_bucket.write.await_args_list[0] == call(
        "entry-1",
        data=ANY,
        content_length=records[0].size,
        timestamp=records[0].timestamp,
    )
    assert walk_async_iterator(dest_bucket.write.await_args_list[0].kwargs["data"]) == [
        b"Hey"
    ]
    assert dest_bucket.write.await_args_list[1] == call(
        "entry-1",
        data=ANY,
        content_length=records[1].size,
        timestamp=records[1].timestamp,
    )
    assert walk_async_iterator(dest_bucket.write.await_args_list[1].kwargs["data"]) == [
        b"Bye"
    ]


@pytest.mark.usefixtures("set_alias", "client")
def test__mirror_ok_with_interval(runner, conf, src_bucket):
    """Should mirror a bucket to another one with time interval"""
    result = runner(
        f"-c {conf} mirror --start 2022-01-02T00:00:01.100300+02:00 "
        f"--stop 2022-02-01T00:00:00+02:00 "
        f"test/src_bucket test/dest_bucket"
    )
    assert "Entry 'entry-1' (copied 6 B" in result.output
    assert result.exit_code == 0

    src_bucket.query.assert_called_with(
        "entry-1", start=1641074401100300, stop=1643666400000000
    )


@pytest.mark.usefixtures("set_alias")
def test__get_error(runner, conf, client):
    """Should print error if something got wrong"""
    client.get_bucket.side_effect = RuntimeError("Oops")
    result = runner(f"-c {conf} mirror test/src_bucket test/dest_bucket")
    assert result.output == "[RuntimeError] Oops\nAborted!\n"
    assert result.exit_code == 1
