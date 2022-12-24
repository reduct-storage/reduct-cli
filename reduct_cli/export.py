"""Export Command"""
import asyncio
from asyncio import new_event_loop as loop
from pathlib import Path
from typing import Optional

import click
from reduct import Client as ReductClient, Bucket, EntryInfo
from rich.progress import Progress

from reduct_cli.utils.error import error_handle
from reduct_cli.utils.helpers import parse_path, get_alias, read_records_with_progress

run = loop().run_until_complete


@click.group()
def export():
    """Commands to export data from a bucket"""


async def _export_entry(path: Path, entry: EntryInfo, bucket: Bucket, progress: Progress, **kwargs) -> None:
    entry_path  = Path(path / entry.name)
    entry_path.mkdir(exist_ok=True)

    async for record in read_records_with_progress(entry, bucket, progress, **kwargs):
        with open(entry_path / f"{record.timestamp}.bin", "wb") as f:
            async for chunk in record.read(n=1024):
                f.write(chunk)


async def _export_bucket(
        client,
        bucket_name: str,
        **kwargs,
) -> None:
    bucket: Bucket = await client.get_bucket(bucket_name)
    folder_path = Path(bucket_name)

    folder_path.mkdir(exist_ok=True)
    with Progress() as progress:
        tasks = [
            _export_entry(folder_path, entry, bucket, progress, **kwargs)
            for entry in await bucket.get_entry_list()
        ]
        await asyncio.gather(*tasks)


@export.command()
@click.argument("path")
@click.option(
    "--start",
    help="Mirror records with timestamps newer than this time point in ISO format",
)
@click.option(
    "--stop",
    help="Mirror records  with timestamps older than this time point in ISO format",
)
@click.pass_context
def folder(ctx, path: str, start: Optional[str], stop: Optional[str]):
    """Export data from bucket to folder"""
    with error_handle():
        alias_name, bucket = parse_path(path)
        alias = get_alias(ctx.obj["config_path"], alias_name)

        client = ReductClient(
            alias["url"], api_token=alias["token"], timeout=ctx.obj["timeout"])
        run(_export_bucket(client, bucket, start=start, stop=stop))