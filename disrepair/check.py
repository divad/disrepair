#!/usr/bin/env python

import os.path

import click
import requests
from packaging.version import InvalidVersion, Version
from pypi_simple import PyPISimple, UnsupportedContentTypeError, UnsupportedRepoVersionError
from requirements.requirement import Requirement
from rich.console import Console

JSON_REPO = 'https://pypi.org/pypi'
SIMPLE_REPO = "https://pypi.org/simple"


class CheckFailed(Exception):
    pass


class Disrepair:
    errors = []
    updates = []
    pins = []
    skip = []
    up2date = []

    def __init__(self, info, verbose, json_repo, simple_repo, simple_only, json_only, pin_warn):
        self.console = Console()
        self.opt_verbose = verbose
        self.opt_info = info
        self.opt_json_only = json_only
        self.opt_simple_only = simple_only
        self.opt_pin_warn = pin_warn
        self.repo_json = json_repo.rstrip('/')
        self.repo_simple = simple_repo.rstrip('/')

    def error(self, name, err):
        self.errors.append(f"⛔ {name}: {err}")

    def unpinned(self, name, version):
        self.pins.append(f"🟨 {name} ➔ {version}")

    def skipped(self, name, reason):
        if self.opt_verbose:
            self.skip.append(f"⬜ {name}: {reason}")

    def update(self, name, spec, latest, url):
        output = f"🔼 {name} {spec} ➔ {latest}"
        if url and self.opt_info:
            output = f"{output}\n   {url}"
        self.updates.append(output)

    def ok(self, name, version):
        if self.opt_verbose:
            self.up2date.append(f"✅ {name} {version}")

    def print(self):
        if self.updates:
            if self.pins or (self.skip and self.opt_verbose) or (self.up2date and self.opt_verbose) or self.errors:
                self.console.rule("[bold]Updates", align='left')
            for line in self.updates:
                print(line)

        if self.pins:
            self.console.rule("[bold]Unpinned", align='left')
            for line in self.pins:
                print(line)

        if self.opt_verbose:
            if self.skip:
                self.console.rule("[bold]Skipped", align='left')
                for line in self.skip:
                    print(line)

            if self.up2date:
                self.console.rule("[bold]Up to date", align='left')
                for line in self.up2date:
                    print(line)

        if self.errors:
            self.console.rule("[bold]Errors", align='left')
            for line in self.errors:
                print(line)

    def get_pypi_version(self, name: str):
        try:
            r = requests.get(f"{self.repo_json}/{name}/json", timeout=3)
        except requests.Timeout:
            raise CheckFailed("Timeout exceeded when connecting to PyPI")
        except requests.ConnectionError:
            raise CheckFailed("Unable to connect to PyPI")

        if r.status_code == 404:
            return None, None

        if not r.ok:
            raise CheckFailed(f"PyPI return code {r.status_code}")

        data = r.json()
        try:
            ver = data["info"]["version"]
        except KeyError:
            raise CheckFailed("PyPI returned a malformed response")

        if 'info' in data:
            if 'project_urls' in data['info']:
                if data['info']['project_urls']:
                    if 'Changelog' in data['info']['project_urls']:
                        if data['info']['project_urls']['Changelog']:
                            return ver, data['info']['project_urls']['Changelog']

                    if 'Changes' in data['info']['project_urls']:
                        if data['info']['project_urls']['Changes']:
                            return ver, data['info']['project_urls']['Changes']

            if 'docs_url' in data['info']:
                if data['info']['docs_url']:
                    return ver, data['info']['docs_url']

            if 'project_url' in data['info']:
                if data['info']['project_url']:
                    return ver, data['info']['project_url']

            if 'home_page' in data['info']:
                if data['info']['home_page']:
                    return ver, data['info']['home_page']

            if 'package_url' in data['info']:
                if data['info']['package_url']:
                    return ver, data['info']['package_url']

        return ver, ''

    def get_pypi_simple_version(self, name):
        with PyPISimple(endpoint=self.repo_simple) as client:
            try:
                page = client.get_project_page(name, timeout=5)
            except requests.RequestException:
                raise CheckFailed("Connection error")
            except UnsupportedRepoVersionError:
                raise CheckFailed("Unsupported repo version")
            except UnsupportedContentTypeError:
                raise CheckFailed("Unsupported content type")

            if page is None:
                raise CheckFailed("Package not found")

            if not page.packages:
                raise CheckFailed("Package not found")

            # There is not a guarantee that versions are listed in order.
            # We must thus check every version and pick the latest stable version.

            chosen_version = None
            for pkg in page.packages:
                if pkg.version is None:
                    continue
                try:
                    pkg_version_obj = Version(pkg.version)
                except InvalidVersion:
                    continue

                if (
                    not pkg_version_obj.is_devrelease
                    and not pkg_version_obj.is_postrelease
                    and not pkg_version_obj.is_prerelease
                ):

                    if chosen_version is None:
                        chosen_version = pkg.version
                        chosen_version_obj = pkg_version_obj
                    else:
                        if pkg_version_obj > chosen_version_obj:
                            chosen_version = pkg.version
                            chosen_version_obj = pkg_version_obj

            if chosen_version is None:
                raise CheckFailed("Could not find a suitable version")

            # The simple api offers no url :(
            return chosen_version, ''

    def get_version(self, name):
        latest = None
        if not self.opt_simple_only:
            try:
                latest, url = self.get_pypi_version(name)
            except CheckFailed:
                if self.opt_json_only:
                    raise

        if not self.opt_json_only:
            if latest is None:
                latest, url = self.get_pypi_simple_version(name)

        if latest is None:
            raise CheckFailed("Package not found")

        return latest, url

    def check_file(self, filepath, recursed=False):
        filename = os.path.basename(filepath)
        lineno = 0

        with open(filepath, 'r') as fh:
            for line in fh.readlines():
                lineno += 1

                if line.strip() == '':
                    continue

                elif not line or line.startswith('#'):
                    continue

                elif line.startswith('-r') or line.startswith('--requirement'):
                    if recursed:
                        self.error(f"{filename}:{lineno}", 'Will only recurse into files once')
                        continue

                    _, new_filename = line.split()
                    new_file = os.path.join(os.path.dirname(filename or '.'), new_filename)
                    self.check_file(new_file, recursed=True)

                elif line.startswith('-'):
                    # Don't support any other options.
                    continue

                else:
                    try:
                        req = Requirement.parse(line)
                    except Exception as ex:
                        self.error(f"{filename}:{lineno}", f"Could not parse line ({ex})")
                        continue

                    if len(req.specs) == 0:
                        if self.opt_pin_warn:
                            try:
                                latest, url = self.get_version(req.name)
                            except CheckFailed as ex:
                                self.error(req.name, ex)
                                continue
                            self.unpinned(req.name, latest)
                        else:
                            self.skipped(req.name, "Version not pinned")
                        continue

                    if len(req.specs) != 1:
                        self.skipped(req.name, 'Unsupported requirement spec')
                        continue
                    if req.specs[0][0] not in ['==', '>=']:
                        self.skipped(req.name, 'Unsupported requirement spec')
                        continue
                    spec = req.specs[0][1]

                    try:
                        latest, url = self.get_version(req.name)
                    except CheckFailed as ex:
                        self.error(req.name, ex)
                        continue

                    ver_latest = Version(latest)
                    ver_spec = Version(spec)
                    if ver_latest > ver_spec:
                        self.update(req.name, spec, latest, url)

                    elif ver_latest == ver_spec:
                        self.ok(req.name, latest)
                    elif ver_latest < ver_spec:
                        self.error(f"Specified version ({spec}) is higher than latest ({latest})")

    def check(self, filepath):
        with self.console.status("[bold]Checking requirements..."):
            self.check_file(filepath)
        self.print()


@click.command()
@click.argument('filename')
@click.option('--verbose', '-v', is_flag=True, help='Show all package statuses')
@click.option('--info', '-i', is_flag=True, help='Show likely package changelog/info links')
@click.option('--json-repo', '-j', default=JSON_REPO, help='Repository URL for the JSON API')
@click.option('--simple-repo', '-s', default=SIMPLE_REPO, help='Repository URL for the Simple API')
@click.option('--simple-only', '-S', is_flag=True, help='Only use the Simple API to lookup versions')
@click.option('--json-only', '-J', is_flag=True, help='Only use the JSON API to lookup versions')
@click.option('--pin-warn', '-p', is_flag=True, help='Warn when a package version is not pinned')
@click.pass_context
def check(ctx, filename, info, verbose, json_repo, simple_repo, simple_only, json_only, pin_warn):
    if simple_only and json_only:
        ctx.fail("--simple-only and --json-only cannot both be set")

    t = Disrepair(info, verbose, json_repo, simple_repo, simple_only, json_only, pin_warn)
    t.check(filename)


if __name__ == '__main__':
    check()
