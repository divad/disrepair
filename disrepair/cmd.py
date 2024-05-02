from typing import Any

import click

from . import __version__
from .check import Disrepair
from .options import JSON_REPO, SIMPLE_REPO, Options


# We need a function so that each command does not get the same list object.
def get_shared_params() -> list[click.Option]:
    return [
        click.Option(['--json-repo', '-j'], default=JSON_REPO, help='Repository URL for the JSON API'),
        click.Option(['--simple-repo', '-s'], default=SIMPLE_REPO, help='Repository URL for the Simple API'),
        click.Option(['--json-only', '-J'], is_flag=True, help='Only use the JSON API to lookup versions'),
        click.Option(['--simple-only', '-S'], is_flag=True, help='Only use the Simple API to lookup versions'),
    ]


@click.group()
def cli() -> None:
    pass


@cli.command(params=get_shared_params())
@click.argument('filename')
@click.option('--info', '-i', is_flag=True, help='Show likely package changelog/info links')
@click.option('--verbose', '-v', is_flag=True, help='Show all package statuses')
@click.option('--unpinned', '-p', is_flag=True, help='Warn when a package version is not pinned')
@click.pass_context
def check(ctx: click.Context, filename: str, **kwargs: Any) -> None:
    '''
    Check a requirements file for out of date versions
    '''
    opts = Options(**kwargs)
    if opts.simple_only and opts.json_only:
        ctx.fail("--simple-only and --json-only cannot both be set")

    Disrepair(opts).cmd_check(filename)


@cli.command(params=get_shared_params())
@click.argument('filename')
@click.option('--unpinned', '-p', is_flag=True, help='Update unpinned packages to latest')
@click.option('--auto-update', '-a', is_flag=True, help='Update all packages to latest without prompting')
@click.pass_context
def update(ctx: click.Context, filename: str, **kwargs: Any) -> None:
    '''
    Update dependencies in a requirements file to the latest version
    '''
    opts = Options(**kwargs)
    opts.info = True
    if opts.simple_only and opts.json_only:
        ctx.fail("--simple-only and --json-only cannot both be set")

    Disrepair(opts).cmd_update(filename)


@cli.command()
def version() -> None:
    '''
    Prints the version of disrepair
    '''
    click.echo(__version__)
